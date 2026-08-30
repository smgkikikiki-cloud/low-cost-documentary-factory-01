#!/usr/bin/env python3
"""Deterministic capability check for the script-first production pipeline.

Checks what's actually on THIS machine's PATH/Python environment at runtime --
never hardcodes assumptions about any particular sandbox or development machine.
The canonical execution environment is whatever machine runs this (e.g. the user's
Windows production machine with ffmpeg/ffprobe/yt-dlp on PATH); a development
sandbox that lacks some of these is expected to report MISSING for them, and that
is not a bug to work around by rewriting the pipeline.

Checks:
  - Python version (informational; no hard minimum enforced beyond 3.8)
  - ffmpeg on PATH
  - ffprobe on PATH
  - yt-dlp on PATH
  - edge-tts (Python package `edge_tts`, or the `edge-tts` CLI entry point)
  - google-cloud-texttospeech (Python package, OPTIONAL -- only the `google-chirp3`
    TTS provider needs it)
  - google-genai (Python package, OPTIONAL -- only the `gemini-tts` TTS provider
    needs it)
  - jsonschema (Python package)

Optional components are reported but never fail the overall check, so a machine
that only runs the edge-tts backend still reports READY.

This checks PACKAGE AVAILABILITY only. Google/Gemini credentials are deliberately
NOT checked here: Application Default Credentials (google-chirp3) and the
GEMINI_API_KEY environment variable (gemini-tts) are both resolved only at the
moment that backend's synthesis is actually requested (scripts/tts_render.py's
google_client() / gemini_client()), so running preflight -- or the whole edge-tts
pipeline -- never requires a Google login or a Gemini API key.

Never auto-installs anything. Prints READY/MISSING per component with a short
install hint for anything missing, then an overall summary.

CLI usage:
    python run_episode.py preflight
    python scripts/preflight.py
"""
import importlib.util
import shutil
import sys


def _check_binary(name: str, hint: str) -> dict:
    path = shutil.which(name)
    return {"component": name, "ready": path is not None, "detail": path or "not found on PATH", "hint": hint}


def _check_python_package(module_name: str, pip_name: str, hint: str, optional: bool = False) -> dict:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        spec = None
    ready = spec is not None
    return {
        "component": pip_name,
        "ready": ready,
        "detail": f"python module {module_name!r} importable" if ready else f"python module {module_name!r} not found",
        "hint": hint,
        "optional": optional,
    }


def check_python_version() -> dict:
    v = sys.version_info
    ready = v >= (3, 8)
    return {
        "component": "python",
        "ready": ready,
        "detail": f"{v.major}.{v.minor}.{v.micro}",
        "hint": "install Python 3.8 or newer" if not ready else "",
    }


def check_edge_tts() -> dict:
    """edge-tts is usable via either the Python package (preferred, used by
    scripts/tts_render.py) or its CLI entry point -- either satisfies this check.
    """
    has_module = importlib.util.find_spec("edge_tts") is not None
    has_cli = shutil.which("edge-tts") is not None
    ready = has_module or has_cli
    if has_module:
        detail = "python module 'edge_tts' importable"
    elif has_cli:
        detail = "'edge-tts' CLI found on PATH (module not importable -- scripts/tts_render.py needs the module)"
    else:
        detail = "neither the 'edge_tts' python module nor the 'edge-tts' CLI was found"
    return {
        "component": "edge-tts",
        "ready": has_module,  # tts_render.py uses the Python API specifically
        "detail": detail,
        "hint": "pip install -r requirements.txt   (or: pip install edge-tts)",
    }


def run_all() -> list:
    return [
        check_python_version(),
        _check_binary("ffmpeg", "install ffmpeg and ensure it's on PATH (https://ffmpeg.org/download.html)"),
        _check_binary("ffprobe", "installed alongside ffmpeg -- same download as above"),
        _check_binary("yt-dlp", "pip install yt-dlp   (or download the standalone binary and put it on PATH)"),
        check_edge_tts(),
        _check_python_package(
            "google.cloud.texttospeech", "google-cloud-texttospeech",
            "pip install -r requirements.txt   (or: pip install google-cloud-texttospeech). "
            "Credentials are separate and are checked only when Google synthesis runs: "
            "gcloud auth application-default login",
            optional=True,
        ),
        _check_python_package(
            "google.genai", "google-genai",
            "pip install -r requirements.txt   (or: pip install google-genai). "
            "Auth is separate and is checked only when gemini-tts synthesis runs: "
            "set the GEMINI_API_KEY environment variable (get a key at https://aistudio.google.com/apikey)",
            optional=True,
        ),
        _check_python_package("jsonschema", "jsonschema", "pip install -r requirements.txt   (or: pip install jsonschema)"),
    ]


def _main() -> int:
    results = run_all()
    print("=== preflight ===\n")
    all_ready = True
    width = max(len(r["component"]) for r in results)
    for r in results:
        if r["ready"]:
            print(f"  READY    {r['component']:<{width}}  {r['detail']}")
        elif r.get("optional"):
            # Optional: reported honestly, but it does not make the machine
            # not-ready -- only the google-chirp3 provider needs it.
            print(f"  MISSING  {r['component']:<{width}}  {r['detail']}  (optional)")
            print(f"           -> {r['hint']}")
        else:
            all_ready = False
            print(f"  MISSING  {r['component']:<{width}}  {r['detail']}")
            print(f"           -> {r['hint']}")
    print()
    if all_ready:
        optional_missing = [r["component"] for r in results if not r["ready"] and r.get("optional")]
        if optional_missing:
            print(f"READY: all required components available "
                  f"(optional not installed: {', '.join(optional_missing)}).")
        else:
            print("READY: all components available.")
    else:
        missing = [r["component"] for r in results if not r["ready"] and not r.get("optional")]
        print(f"NOT READY: missing {', '.join(missing)}")
    return 0 if all_ready else 1


if __name__ == "__main__":
    sys.exit(_main())
