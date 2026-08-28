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
  - jsonschema (Python package)

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


def _check_python_package(module_name: str, pip_name: str, hint: str) -> dict:
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
        _check_python_package("jsonschema", "jsonschema", "pip install -r requirements.txt   (or: pip install jsonschema)"),
    ]


def _main() -> int:
    results = run_all()
    print("=== preflight ===\n")
    all_ready = True
    for r in results:
        if r["ready"]:
            print(f"  READY    {r['component']:<12} {r['detail']}")
        else:
            all_ready = False
            print(f"  MISSING  {r['component']:<12} {r['detail']}")
            print(f"           -> {r['hint']}")
    print()
    if all_ready:
        print("READY: all components available.")
    else:
        missing = [r["component"] for r in results if not r["ready"]]
        print(f"NOT READY: missing {', '.join(missing)}")
    return 0 if all_ready else 1


if __name__ == "__main__":
    sys.exit(_main())
