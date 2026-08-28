#!/usr/bin/env python3
"""Real V0 TTS renderer. One provider (edge-tts), one audio file per
script_manifest.json block, real measured durations written to tts_manifest.json.

Only `block.narration_text` is ever sent to speech -- never the title, the
optional_deck, source_refs, or any URL. The narration text is never rewritten
before synthesis; this module does exactly what it's told to speak.

Not a provider framework: one small function calls the one V0 backend (edge-tts's
Python API). A future backend swap should only require changing this one module
(and the `provider` field in channel config), not the rest of the pipeline.

Per-block timeout: edge-tts talks to a remote service over a websocket, and that
call has been observed to hang indefinitely mid-episode (the process stays alive
but stops producing files). Every synthesis call is therefore bounded by
DEFAULT_SYNTHESIS_TIMEOUT_SEC. A block that exceeds it is recorded as a FAILURE and
the run moves on to the next block -- it never blocks the whole episode forever. A
timed-out (or otherwise failed) synthesis also deletes its own partial .mp3, so a
truncated file can never be mistaken for finished audio by a later resume.

Resume/reuse is evidence-based, not checkpoint-based: for each block, if
`episode_dir/audio/<block_id>.mp3` exists it is PROBED FIRST. If ffprobe reports a
valid positive duration, the file is reused as-is (that measured duration is the
truth, and re-synthesizing it would only cost time) -- this holds even if the
previous run died before recording that block in tts_manifest.json. If the file
does not probe, or probes to a zero/absent duration, it is treated as corrupt
leftover: it is deleted and the block is synthesized again. There is no
content-hash cache and no invalidation logic; script_manifest.json is locked at
ingestion and never edited in place, so "a valid audio file exists for this
block_id" is sufficient grounds for reuse.

tts_manifest.json is checkpointed atomically (write a temp file, then replace)
after EVERY successfully measured block, so an aborted or crashed run still leaves
a truthful record of what has genuinely been rendered so far. Those checkpoints
always carry status "pending". The manifest is only ever written with status
"generated" once every script_manifest.json block is present and measured -- a
partial run reports its failures and stays "pending", never a false "generated".

CLI usage:
    python scripts/tts_render.py episodes/ForeignCarsTH_example-car \\
        --voice th-TH-NiwatNeural --rate +0% --pitch +0Hz --volume +0%

Normally invoked via `python run_episode.py tts <episode_id>`, which reads the
voice/rate/pitch/volume from the episode's channel config instead of requiring
them on the command line every time.
"""
import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media_probe  # noqa: E402
import episode_paths  # noqa: E402

# One narration paragraph is a few seconds of speech; anything past two minutes is
# a hung websocket, not slow synthesis.
DEFAULT_SYNTHESIS_TIMEOUT_SEC = 120.0


class TTSRenderError(RuntimeError):
    pass


def _synthesize(
    text: str, voice: str, rate: str, pitch: str, volume: str, out_path: Path,
    timeout_sec: float = DEFAULT_SYNTHESIS_TIMEOUT_SEC,
) -> None:
    """Renders `text` to out_path via edge-tts's Python API, bounded by timeout_sec.

    Lazy-imports edge_tts so this module can be imported (and py_compiled) without
    the package installed -- only calling this function actually requires it.

    Always raises TTSRenderError on failure (including timeout) rather than hanging,
    and removes any partial output file it left behind so nothing downstream can
    mistake a truncated .mp3 for a finished one.
    """
    try:
        import edge_tts
    except ImportError as e:
        raise TTSRenderError(
            "The 'edge_tts' python package is not installed. Run: pip install -r requirements.txt "
            "(or: pip install edge-tts)"
        ) from e

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
        await asyncio.wait_for(communicate.save(str(out_path)), timeout=timeout_sec)

    try:
        asyncio.run(_run())
    except asyncio.TimeoutError as e:
        _discard_partial(out_path)
        raise TTSRenderError(
            f"edge-tts synthesis timed out after {timeout_sec:g}s for voice={voice!r} "
            f"(the remote service stopped responding; the partial file was discarded)"
        ) from e
    except Exception as e:
        _discard_partial(out_path)
        raise TTSRenderError(f"edge-tts synthesis failed for voice={voice!r}: {e}") from e


def _discard_partial(out_path: Path) -> None:
    """Best-effort removal of an audio file we know is not trustworthy."""
    try:
        out_path.unlink()
    except OSError:
        pass


def _measure(out_path: Path):
    """Returns a positive measured duration for out_path, or None if it does not
    exist / cannot be probed / probes to an unusable duration.

    This is the single definition of "this audio file is real", used both for
    salvaging a file left by an earlier run and for measuring one we just rendered.
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


def render_episode_tts(
    episode_dir: Path, tts_config: dict, resume: bool = True,
    timeout_sec: float = DEFAULT_SYNTHESIS_TIMEOUT_SEC,
) -> dict:
    """Renders (or salvages) one audio file per script_manifest.json block, measures
    each one's real duration, and checkpoints tts_manifest.json after every measured
    block.

    Returns {"manifest": <dict written>, "failures": [(block_id, reason), ...],
    "complete": bool}. Never raises for a per-block synthesis/probe failure -- those
    are collected in `failures` and the manifest is written honestly (status
    "pending", only the successful blocks listed). Raises TTSRenderError only for
    setup problems that make the whole run meaningless (no script_manifest.json, no
    blocks, no voice configured, no ffprobe to measure with).

    Progress for every block is printed to stdout as it happens, so a long episode
    is visibly making progress instead of looking hung.
    """
    episode_dir = Path(episode_dir)
    sm_path = episode_dir / "script_manifest.json"
    if not sm_path.exists():
        raise TTSRenderError(f"No script_manifest.json in {episode_dir} -- run `ingest` first.")
    sm = json.loads(sm_path.read_text(encoding="utf-8"))
    blocks = sm.get("blocks", [])
    if not blocks:
        raise TTSRenderError(f"script_manifest.json in {episode_dir} has no blocks.")

    voice = tts_config.get("voice")
    if not voice:
        raise TTSRenderError("Channel config has no tts.voice set -- see config/channels/<channel_id>.json.")
    rate = tts_config.get("rate", "+0%")
    pitch = tts_config.get("pitch", "+0Hz")
    volume = tts_config.get("volume", "+0%")

    # Checked up front, not per block: without ffprobe nothing can be measured, so
    # every block would fail anyway -- and, worse, the salvage path below would read
    # "unprobeable" as "corrupt" and delete perfectly good audio from a previous run.
    if shutil.which("ffprobe") is None:
        raise TTSRenderError(
            "'ffprobe' was not found on PATH. TTS durations must be MEASURED, not estimated, "
            "so ffprobe is required. Install ffmpeg (which provides ffprobe) and re-run."
        )

    audio_dir = episode_paths.audio_dir(episode_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    tts_manifest_path = episode_dir / "tts_manifest.json"
    episode_id = sm.get("episode_id")

    total = len(blocks)
    rendered_blocks = []
    failures = []
    for i, block in enumerate(blocks, start=1):
        block_id = block.get("block_id")
        text = block.get("narration_text") or ""
        out_path = audio_dir / f"{block_id}.mp3"
        rel_path = episode_paths.relative_to_episode(out_path, episode_dir)
        tag = f"[{i}/{total}] {block_id}"

        # Salvage first: an existing file that genuinely probes is finished work,
        # whether or not the run that made it lived long enough to checkpoint it.
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
                _synthesize(text, voice, rate, pitch, volume, out_path, timeout_sec=timeout_sec)
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

    return {"manifest": manifest, "failures": failures, "complete": complete}


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode_dir")
    parser.add_argument("--voice", required=True)
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--pitch", default="+0Hz")
    parser.add_argument("--volume", default="+0%")
    parser.add_argument("--no-resume", action="store_true", help="Re-synthesize every block even if valid audio already exists")
    parser.add_argument("--timeout", type=float, default=DEFAULT_SYNTHESIS_TIMEOUT_SEC,
                        help=f"Per-block synthesis timeout in seconds (default {DEFAULT_SYNTHESIS_TIMEOUT_SEC:g})")
    args = parser.parse_args()

    tts_config = {"voice": args.voice, "rate": args.rate, "pitch": args.pitch, "volume": args.volume}
    try:
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
