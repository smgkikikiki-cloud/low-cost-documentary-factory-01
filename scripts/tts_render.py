#!/usr/bin/env python3
"""Real V0 TTS renderer. One audio file per script_manifest.json block, real
measured durations written to tts_manifest.json.

Block backends: edge-tts and google-chirp3. Gemini uses the separate
scripts/tts_gemini_chunks.py renderer, selected by run_episode.py, because a
Gemini performance can span multiple original blocks. This module still resolves
Gemini config for fingerprint inspection, but refuses block-level Gemini rendering.

Only `block.narration_text` is ever sent to speech -- never the title, the
optional_deck, source_refs, or any URL. The narration text is never rewritten,
re-punctuated, or marked up before synthesis; this module does exactly what it's
told to speak.

CONFIG-SCOPED AUDIO. Rendered audio lives in a directory keyed to the effective
synthesis configuration:

    audio/<provider>_<8-hex-fingerprint>/block_001.mp3

The fingerprint (see tts_config_fingerprint) covers exactly the fields that
materially change how the audio sounds -- provider, voice, language, speaking
rate/pace, pitch, volume, input/markup mode, audio encoding. Switching provider,
voice, pace, or markup mode therefore renders into a DIFFERENT directory, so
Edge/Niwat audio can never be silently reused as if it were Google/Chirp audio.
Audio for other configurations is left exactly where it is, never deleted --
switching back is just switching the config back. Files directly under `audio/`
with no subdirectory are pre-fingerprint legacy output; they are never
auto-reused (nothing records which config produced them) and never deleted. If
you know which config made them, `--adopt-legacy-audio` copies them into that
config's directory explicitly.

tts_manifest.json always records the CURRENT config's real relative audio_path,
so the renderer picks up whatever was last rendered. No schema change is needed
for any of this -- audio_path was always just a path.

Per-block timeout: both backends talk to a remote service, and edge-tts has been
observed to hang indefinitely mid-episode (process alive, no new files). Every
synthesis call is bounded by DEFAULT_SYNTHESIS_TIMEOUT_SEC. A block that exceeds
it is recorded as a FAILURE, its partial file is deleted, and the run continues
to the next block -- one bad block never blocks the whole episode.

Resume/reuse is evidence-based, not checkpoint-based: for each block, if
`<config audio dir>/<block_id>.mp3` exists it is PROBED FIRST. If ffprobe reports
a valid positive duration, the file is reused as-is -- even if the previous run
died before recording that block in tts_manifest.json. If the file does not
probe, or probes to a zero/absent duration, it is treated as corrupt leftover:
deleted, and the block synthesized again. There is no content-hash cache;
script_manifest.json is locked at ingestion and never edited in place, so "a
valid audio file exists for this block_id under this config's directory" is
sufficient grounds for reuse.

tts_manifest.json is checkpointed atomically (write a temp file, then replace)
after EVERY successfully measured block, always with status "pending", so an
aborted run keeps every block it genuinely finished. "generated" is written only
once every script_manifest.json block is present and measured.

CLI usage:
    python scripts/tts_render.py episodes/ForeignCarsTH_example-car \\
        --provider edge-tts --voice th-TH-NiwatNeural
    python scripts/tts_render.py episodes/ForeignCarsTH_example-car \\
        --provider google-chirp3 --voice th-TH-Chirp3-HD-Charon \\
        --language-code th-TH --speaking-rate 1.0

Normally invoked via `python run_episode.py tts <episode_id> [--profile NAME]`,
which reads the synthesis config from the episode's channel config instead of
requiring it on the command line every time.
"""
import argparse
import asyncio
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media_probe  # noqa: E402
import episode_paths  # noqa: E402

# Request wall-clock budget; independent of generated audio duration.
DEFAULT_SYNTHESIS_TIMEOUT_SEC = 120.0

PROVIDER_EDGE = "edge-tts"
PROVIDER_GOOGLE = "google-chirp3"
PROVIDER_GEMINI = "gemini-tts"
SUPPORTED_PROVIDERS = (PROVIDER_EDGE, PROVIDER_GOOGLE, PROVIDER_GEMINI)



class TTSRenderError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Effective config + fingerprint
# --------------------------------------------------------------------------

def resolve_tts_config(tts_config: dict) -> dict:
    """Normalize a channel's `tts` block into the EFFECTIVE synthesis config:
    every field that materially affects the audio, with defaults filled in.

    Defaults are resolved here rather than at the call site so that an omitted
    field and an explicitly-written default produce the same config -- and
    therefore the same fingerprint, and therefore no pointless re-render.

    Only audio-affecting fields are kept. Anything else in the channel config
    (comments, notes, bookkeeping) is deliberately ignored so it can't churn the
    fingerprint and orphan a directory of perfectly good audio.
    """
    if not isinstance(tts_config, dict):
        raise TTSRenderError("tts config must be a JSON object -- see config/channels/<channel_id>.json")

    provider = tts_config.get("provider", PROVIDER_EDGE)
    voice = tts_config.get("voice")
    if not voice:
        raise TTSRenderError("tts config has no 'voice' set -- see config/channels/<channel_id>.json.")

    if provider == PROVIDER_EDGE:
        return {
            "provider": PROVIDER_EDGE,
            "voice": voice,
            # edge-tts encodes the locale in the voice name itself; carried anyway
            # so the fingerprint is comparable across providers.
            "language_code": tts_config.get("language_code") or _locale_from_voice(voice),
            "rate": tts_config.get("rate", "+0%"),
            "pitch": tts_config.get("pitch", "+0Hz"),
            "volume": tts_config.get("volume", "+0%"),
            "input_mode": tts_config.get("input_mode", "text"),
            "audio_encoding": "mp3",
        }

    if provider == PROVIDER_GOOGLE:
        language_code = tts_config.get("language_code") or _locale_from_voice(voice)
        if not language_code:
            raise TTSRenderError(
                f"provider {PROVIDER_GOOGLE!r} needs a 'language_code' (e.g. \"th-TH\") in the tts config."
            )
        try:
            speaking_rate = float(tts_config.get("speaking_rate", 1.0))
        except (TypeError, ValueError):
            raise TTSRenderError(f"speaking_rate must be a number, got {tts_config.get('speaking_rate')!r}")
        # Google's documented Chirp 3: HD pace range.
        if not 0.25 <= speaking_rate <= 2.0:
            raise TTSRenderError(f"speaking_rate {speaking_rate} is outside Google's supported 0.25-2.0 range.")
        input_mode = tts_config.get("input_mode", "text")
        if input_mode not in ("text", "ssml"):
            raise TTSRenderError(f"input_mode must be 'text' or 'ssml', got {input_mode!r}")
        return {
            "provider": PROVIDER_GOOGLE,
            "voice": voice,
            "language_code": language_code,
            "speaking_rate": speaking_rate,
            "input_mode": input_mode,
            "audio_encoding": "mp3",
        }

    if provider == PROVIDER_GEMINI:
        from tts_gemini_chunks import config, ChunkError
        try:
            return config(tts_config)
        except (ChunkError, ValueError, TypeError) as exc:
            raise TTSRenderError(str(exc)) from exc

    raise TTSRenderError(
        f"Unknown tts provider {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}."
    )


def audio_file_extension(cfg: dict) -> str:
    """The file extension this config's backend actually produces. gemini-tts
    returns raw PCM (wrapped as .wav here); the other two backends return MP3.
    """
    return "wav" if cfg["provider"] == PROVIDER_GEMINI else "mp3"


def _locale_from_voice(voice: str):
    """Best-effort locale prefix from a voice name ('th-TH-Chirp3-HD-Charon' ->
    'th-TH'). Returns None if the name doesn't start with one, in which case the
    caller must have an explicit language_code.
    """
    m = re.match(r"^([a-z]{2,3}-[A-Z]{2})", voice or "")
    return m.group(1) if m else None


def tts_config_fingerprint(tts_config: dict) -> str:
    """Deterministic `<provider>_<8 hex>` directory name for an effective config.

    Stable across runs and machines (plain sha256 over a canonical JSON dump with
    sorted keys), and guaranteed to change whenever any audio-affecting field
    changes. The provider prefix is only there so the directory is readable on
    disk; the hash is what actually separates configurations.
    """
    effective = resolve_tts_config(tts_config)
    if effective["provider"] == PROVIDER_GEMINI:
        from tts_gemini_chunks import digest
        return "gemini-chunks_" + digest(effective)[:16]
    canonical = json.dumps(effective, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    safe_provider = re.sub(r"[^A-Za-z0-9._-]+", "_", effective["provider"])
    return f"{safe_provider}_{digest}"


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

def _synthesize(cfg: dict, text: str, out_path: Path, timeout_sec: float) -> None:
    """Render `text` to out_path with the configured backend, bounded by
    timeout_sec. Always raises TTSRenderError on failure (including timeout)
    rather than hanging, and removes any partial output file it left behind so a
    truncated .mp3 can never be mistaken for finished audio.
    """
    try:
        if cfg["provider"] == PROVIDER_EDGE:
            _synthesize_edge(cfg, text, out_path, timeout_sec)
        elif cfg["provider"] == PROVIDER_GOOGLE:
            _synthesize_google(cfg, text, out_path, timeout_sec)
        else:
            raise TTSRenderError("Gemini requires the multi-block chunk renderer; use run_episode.py tts --profile gemini-tts")
    except TTSRenderError:
        _discard_partial(out_path)
        raise
    except Exception as e:  # defensive: a backend raising something unexpected
        _discard_partial(out_path)
        raise TTSRenderError(f"{cfg['provider']} synthesis failed for voice={cfg['voice']!r}: {e}") from e


def _synthesize_edge(cfg: dict, text: str, out_path: Path, timeout_sec: float) -> None:
    """edge-tts via its Python API. Lazy-imports edge_tts so this module imports
    (and py_compiles) without the package installed.
    """
    try:
        import edge_tts
    except ImportError as e:
        raise TTSRenderError(
            "The 'edge_tts' python package is not installed. Run: pip install -r requirements.txt "
            "(or: pip install edge-tts)"
        ) from e

    async def _run():
        communicate = edge_tts.Communicate(
            text, cfg["voice"], rate=cfg["rate"], pitch=cfg["pitch"], volume=cfg["volume"],
        )
        await asyncio.wait_for(communicate.save(str(out_path)), timeout=timeout_sec)

    try:
        asyncio.run(_run())
    except asyncio.TimeoutError as e:
        raise TTSRenderError(
            f"synthesis timed out after {timeout_sec:g}s (edge-tts, voice={cfg['voice']!r}); "
            f"the partial file was discarded"
        ) from e
    except Exception as e:
        raise TTSRenderError(f"edge-tts synthesis failed for voice={cfg['voice']!r}: {e}") from e


def google_client(timeout_sec: float = DEFAULT_SYNTHESIS_TIMEOUT_SEC):
    """Build a Google Cloud Text-to-Speech client using Application Default
    Credentials ONLY. No API keys, no service-account paths, no project IDs are
    read from or written to this repository -- ADC is entirely a property of the
    machine running this.

    Raises TTSRenderError with an actionable message if the client package is
    missing or ADC can't be resolved.
    """
    try:
        from google.cloud import texttospeech
    except ImportError as e:
        raise TTSRenderError(
            "The 'google-cloud-texttospeech' python package is not installed. "
            "Run: pip install -r requirements.txt   (or: pip install google-cloud-texttospeech)"
        ) from e

    try:
        return texttospeech.TextToSpeechClient()
    except Exception as e:
        raise TTSRenderError(
            f"Could not create a Google Text-to-Speech client via Application Default Credentials: {e}\n"
            f"  Fix on the production machine (nothing is stored in this repository):\n"
            f"    1. gcloud auth application-default login\n"
            f"    2. gcloud auth application-default set-quota-project <YOUR_PROJECT_ID>\n"
            f"    3. enable the Cloud Text-to-Speech API for that project\n"
            f"  (or set GOOGLE_APPLICATION_CREDENTIALS to a service-account key file OUTSIDE this repo)"
        ) from e


def _synthesize_google(cfg: dict, text: str, out_path: Path, timeout_sec: float) -> None:
    """Google Cloud TTS (Chirp 3: HD), MP3 out, with a real per-request timeout.

    The whole response is buffered in memory and written in one shot, so a failed
    request leaves no file at all rather than a truncated one.
    """
    from google.cloud import texttospeech  # import guarded by google_client() above

    client = cfg.get("_client") or google_client(timeout_sec)

    if cfg["input_mode"] == "ssml":
        synthesis_input = texttospeech.SynthesisInput(ssml=text)
    else:
        synthesis_input = texttospeech.SynthesisInput(text=text)

    voice_params = texttospeech.VoiceSelectionParams(
        language_code=cfg["language_code"],
        name=cfg["voice"],
    )
    # Chirp 3: HD supports speaking_rate but NOT pitch -- pitch is deliberately not
    # sent, rather than sent as a no-op that would silently drift from the config.
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=cfg["speaking_rate"],
    )

    try:
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice_params, audio_config=audio_config,
            timeout=timeout_sec,
        )
    except Exception as e:
        if _is_deadline_exceeded(e):
            raise TTSRenderError(
                f"synthesis timed out after {timeout_sec:g}s "
                f"(google-chirp3, voice={cfg['voice']!r})"
            ) from e
        raise TTSRenderError(
            f"google-chirp3 synthesis failed for voice={cfg['voice']!r}: {type(e).__name__}: {e}"
        ) from e

    if not response.audio_content:
        raise TTSRenderError(f"google-chirp3 returned empty audio for voice={cfg['voice']!r}")
    out_path.write_bytes(response.audio_content)


def _is_deadline_exceeded(exc: Exception) -> bool:
    """True if `exc` is google-api-core's deadline/timeout error, without making
    google.api_core an import-time dependency of this module.
    """
    for klass in type(exc).__mro__:
        if klass.__name__ in ("DeadlineExceeded", "RetryError", "_MultiCallState"):
            return True
    return isinstance(exc, TimeoutError)


def list_google_voices(language_code: str) -> list:
    """Real voice names available for `language_code`, straight from Google's
    catalog. Used to VERIFY a configured/auditioned voice name instead of
    trusting a name copied out of documentation or a blog post.
    """
    client = google_client()
    response = client.list_voices(language_code=language_code)
    out = []
    for v in response.voices:
        out.append({
            "name": v.name,
            "ssml_gender": getattr(v.ssml_gender, "name", str(v.ssml_gender)),
            "natural_sample_rate_hertz": v.natural_sample_rate_hertz,
        })
    return sorted(out, key=lambda d: d["name"])


# --------------------------------------------------------------------------
# File handling
# --------------------------------------------------------------------------

def _discard_partial(out_path: Path) -> None:
    """Best-effort removal of an audio file we know is not trustworthy."""
    try:
        out_path.unlink()
    except OSError:
        pass


def _measure(out_path: Path):
    """Returns a positive measured duration for out_path, or None if it does not
    exist / cannot be probed / probes to an unusable duration.

    The single definition of "this audio file is real", used both for salvaging a
    file left by an earlier run and for measuring one we just rendered.
    """
    if not out_path.exists():
        return None
    try:
        info = media_probe.probe(str(out_path))
    except media_probe.MediaProbeError:
        return None
    duration = info.get("duration_sec")
    if not duration or duration <= 0:
        return None
    return duration


def _build_manifest(episode_id, rendered_blocks: list, complete: bool) -> dict:
    return {
        "episode_id": episode_id,
        "status": "generated" if complete else "pending",
        "blocks": rendered_blocks,
    }


def _write_manifest_atomic(tts_manifest_path: Path, manifest: dict) -> None:
    """Atomic write: readers never observe a half-written tts_manifest.json, and an
    abort between blocks leaves the last checkpoint intact.
    """
    tmp_path = tts_manifest_path.with_name(tts_manifest_path.name + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(tts_manifest_path)


def legacy_flat_audio(episode_dir: Path) -> list:
    """Pre-fingerprint audio sitting directly in `audio/` (no config subdirectory).

    Nothing on disk records which provider/voice produced these, so they are never
    auto-reused -- that is exactly the unsafe cross-config reuse this module now
    prevents. They are reported, never deleted, and can be adopted explicitly via
    adopt_legacy_audio() when the operator knows which config made them.
    """
    d = episode_paths.audio_dir(episode_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".mp3")


def adopt_legacy_audio(episode_dir: Path, tts_config: dict) -> list:
    """Explicitly COPY pre-fingerprint `audio/*.mp3` into the current config's
    directory, for an operator who knows those files were produced by this exact
    configuration. Never called automatically, and never moves or deletes the
    originals -- rollback stays available.

    Returns the list of destination paths that were created.
    """
    if tts_config.get("provider") == PROVIDER_GEMINI:
        raise TTSRenderError("Legacy block MP3 files cannot be adopted as Gemini chunks")
    fingerprint = tts_config_fingerprint(tts_config)
    dest_dir = episode_paths.audio_config_dir(Path(episode_dir), fingerprint)
    dest_dir.mkdir(parents=True, exist_ok=True)
    adopted = []
    for src in legacy_flat_audio(Path(episode_dir)):
        dest = dest_dir / src.name
        if dest.exists():
            continue
        shutil.copy2(src, dest)
        adopted.append(dest)
    return adopted


# --------------------------------------------------------------------------
# Main render loop
# --------------------------------------------------------------------------

def render_episode_tts(
    episode_dir: Path, tts_config: dict, resume: bool = True,
    timeout_sec: float = DEFAULT_SYNTHESIS_TIMEOUT_SEC,
) -> dict:
    """Renders (or salvages) one audio file per script_manifest.json block under
    this configuration's own audio directory, measures each one's real duration,
    and checkpoints tts_manifest.json after every measured block.

    Returns {"manifest": <dict written>, "failures": [(block_id, reason), ...],
    "complete": bool, "fingerprint": str, "audio_dir": Path}. Never raises for a
    per-block synthesis/probe failure -- those are collected in `failures` and the
    manifest is written honestly (status "pending", only the successful blocks
    listed). Raises TTSRenderError only for setup problems that make the whole run
    meaningless (no script_manifest.json, no blocks, bad/unknown tts config, no
    ffprobe to measure with, no Google credentials when Google is the provider) --
    all of which are detected BEFORE any audio file or manifest is touched.

    Progress for every block is printed to stdout as it happens, flushed, so a long
    episode is visibly making progress on Windows CMD instead of looking hung.
    """
    if tts_config.get("provider") == PROVIDER_GEMINI:
        raise TTSRenderError("Gemini produces multi-block chunks; use run_episode.py tts EPISODE --profile gemini-tts")
    episode_dir = Path(episode_dir)
    sm_path = episode_dir / "script_manifest.json"
    if not sm_path.exists():
        raise TTSRenderError(f"No script_manifest.json in {episode_dir} -- run `ingest` first.")
    sm = json.loads(sm_path.read_text(encoding="utf-8"))
    blocks = sm.get("blocks", [])
    if not blocks:
        raise TTSRenderError(f"script_manifest.json in {episode_dir} has no blocks.")

    cfg = resolve_tts_config(tts_config)
    fingerprint = tts_config_fingerprint(tts_config)

    # Everything below this point either succeeds or leaves the episode untouched.
    # Checked up front, not per block: without ffprobe nothing can be measured, so
    # every block would fail anyway -- and, worse, the salvage path would read
    # "unprobeable" as "corrupt" and delete good audio from a previous run.
    if shutil.which("ffprobe") is None:
        raise TTSRenderError(
            "'ffprobe' was not found on PATH. TTS durations must be MEASURED, not estimated, "
            "so ffprobe is required. Install ffmpeg (which provides ffprobe) and re-run. "
            "No audio or manifest was modified."
        )

    # Same reasoning for Google/Gemini auth: resolve credentials once, before
    # touching anything, so an auth problem can never leave a half-rendered episode.
    if cfg["provider"] == PROVIDER_GOOGLE:
        cfg["_client"] = google_client(timeout_sec)

    audio_ext = audio_file_extension(cfg)
    audio_dir = episode_paths.audio_config_dir(episode_dir, fingerprint)
    audio_dir.mkdir(parents=True, exist_ok=True)
    tts_manifest_path = episode_dir / "tts_manifest.json"
    episode_id = sm.get("episode_id")

    print(f"tts: provider={cfg['provider']} voice={cfg['voice']} "
          f"-> {episode_paths.relative_to_episode(audio_dir, episode_dir)}/", flush=True)
    orphans = legacy_flat_audio(episode_dir)
    if orphans:
        print(f"  note: {len(orphans)} pre-fingerprint file(s) sit directly in audio/ and are being IGNORED "
              f"(nothing records which config produced them). They are not deleted. If you know they came "
              f"from THIS config, adopt them with: python scripts/tts_render.py <episode_dir> "
              f"--adopt-legacy-audio ...", flush=True)

    total = len(blocks)
    rendered_blocks = []
    failures = []
    for i, block in enumerate(blocks, start=1):
        block_id = block.get("block_id")
        text = block.get("narration_text") or ""
        out_path = audio_dir / f"{block_id}.{audio_ext}"
        rel_path = episode_paths.relative_to_episode(out_path, episode_dir)
        tag = f"[{i}/{total}] {block_id}"

        # Salvage first: an existing file under THIS config's directory that
        # genuinely probes is finished work, whether or not the run that made it
        # lived long enough to checkpoint it.
        duration = _measure(out_path) if resume else None
        if duration is not None:
            print(f"{tag} reused {duration:.1f}s", flush=True)
        else:
            # Either nothing is there, or what's there is corrupt/truncated leftover
            # (a killed run, a timed-out synthesis). Never reuse it, never leave it.
            if out_path.exists():
                _discard_partial(out_path)

            if not text.strip():
                reason = "empty narration_text -- nothing to synthesize"
                failures.append((block_id, reason))
                print(f"{tag} FAILED: {reason}", flush=True)
                continue

            print(f"{tag} generating...", flush=True)
            try:
                _synthesize(cfg, text, out_path, timeout_sec)
            except TTSRenderError as e:
                failures.append((block_id, str(e)))
                print(f"{tag} FAILED: {e}", flush=True)
                continue

            duration = _measure(out_path)
            if duration is None:
                reason = "rendered audio could not be measured (missing, unprobeable, or zero-length)"
                _discard_partial(out_path)
                failures.append((block_id, reason))
                print(f"{tag} FAILED: {reason}", flush=True)
                continue
            print(f"{tag} generated {duration:.1f}s", flush=True)

        rendered_blocks.append({"block_id": block_id, "audio_path": rel_path, "duration_sec": duration})

        # Checkpoint after every measured block, always as "pending" -- an abort here
        # loses no measured work, and can never leave a premature "generated".
        _write_manifest_atomic(tts_manifest_path, _build_manifest(episode_id, rendered_blocks, complete=False))

    complete = not failures and len(rendered_blocks) == total
    manifest = _build_manifest(episode_id, rendered_blocks, complete=complete)
    _write_manifest_atomic(tts_manifest_path, manifest)

    if complete:
        (episode_dir / "tts_chunks.json").unlink(missing_ok=True)
    return {
        "manifest": manifest, "failures": failures, "complete": complete,
        "fingerprint": fingerprint, "audio_dir": audio_dir,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode_dir")
    parser.add_argument("--provider", default=PROVIDER_EDGE, choices=list(SUPPORTED_PROVIDERS))
    parser.add_argument("--voice", required=True)
    parser.add_argument("--language-code", default=None, help="e.g. th-TH (required for google-chirp3 if the voice name has no locale prefix)")
    parser.add_argument("--rate", default="+0%", help="edge-tts only")
    parser.add_argument("--pitch", default="+0Hz", help="edge-tts only")
    parser.add_argument("--volume", default="+0%", help="edge-tts only")
    parser.add_argument("--speaking-rate", type=float, default=1.0, help="google-chirp3 only (0.25-2.0)")
    parser.add_argument("--input-mode", default="text", choices=["text", "ssml"], help="google-chirp3 only")
    parser.add_argument("--no-resume", action="store_true", help="Re-synthesize every block even if valid audio already exists")
    parser.add_argument("--timeout", type=float, default=DEFAULT_SYNTHESIS_TIMEOUT_SEC,
                        help=f"Per-block synthesis timeout in seconds (default {DEFAULT_SYNTHESIS_TIMEOUT_SEC:g})")
    parser.add_argument("--adopt-legacy-audio", action="store_true",
                        help="Copy pre-fingerprint audio/*.mp3 into this config's directory and exit. "
                             "Only do this if you know those files were produced by exactly this config.")
    parser.add_argument("--print-fingerprint", action="store_true", help="Print this config's audio directory name and exit")
    args = parser.parse_args()

    tts_config = {
        "provider": args.provider, "voice": args.voice, "language_code": args.language_code,
        "rate": args.rate, "pitch": args.pitch, "volume": args.volume,
        "speaking_rate": args.speaking_rate, "input_mode": args.input_mode,
    }
    tts_config = {k: v for k, v in tts_config.items() if v is not None}

    try:
        if args.print_fingerprint:
            print(tts_config_fingerprint(tts_config))
            return 0

        if args.adopt_legacy_audio:
            adopted = adopt_legacy_audio(Path(args.episode_dir), tts_config)
            print(f"Adopted {len(adopted)} legacy file(s) into "
                  f"audio/{tts_config_fingerprint(tts_config)}/ (originals left in place):")
            for p in adopted:
                print(f"  {p}")
            return 0

        result = render_episode_tts(
            Path(args.episode_dir), tts_config,
            resume=not args.no_resume, timeout_sec=args.timeout,
        )
    except TTSRenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"tts_manifest.json: status={result['manifest']['status']!r}, "
          f"{len(result['manifest']['blocks'])} block(s) rendered/measured")
    for block_id, reason in result["failures"]:
        print(f"  FAILED  {block_id}: {reason}", file=sys.stderr)
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    sys.exit(_main())
