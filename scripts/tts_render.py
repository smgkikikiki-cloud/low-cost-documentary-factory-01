#!/usr/bin/env python3
"""Real V0 TTS renderer. One provider (edge-tts), one audio file per
script_manifest.json block, real measured durations written to tts_manifest.json.

Only `block.narration_text` is ever sent to speech -- never the title, the
optional_deck, source_refs, or any URL. The narration text is never rewritten
before synthesis; this module does exactly what it's told to speak.

Not a provider framework: one small function calls the one V0 backend (edge-tts's
Python API). A future backend swap should only require changing this one module
(and the `provider` field in channel config), not the rest of the pipeline.

Resume/reuse: if `episode_dir/audio/<block_id>.mp3` already exists, it is reused
(re-probed for its real duration, not re-synthesized) rather than paying to
re-render it. This is deliberately simple -- there is no content-hash cache, no
invalidation logic. Since script_manifest.json is locked at ingestion and never
edited in place, "the audio file for this block_id already exists in this episode
directory" is sufficient grounds for reuse.

tts_manifest.json is only ever written with status: "generated" when EVERY
script_manifest.json block rendered and measured successfully. A partial run writes
status: "pending" with whatever succeeded, and the failures are reported -- never a
false "generated". The write itself is atomic (write to a temp file, then replace)
so a crash mid-write can't corrupt the manifest that's already on disk.

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media_probe  # noqa: E402
import episode_paths  # noqa: E402


class TTSRenderError(RuntimeError):
    pass


def _synthesize(text: str, voice: str, rate: str, pitch: str, volume: str, out_path: Path) -> None:
    """Renders `text` to out_path via edge-tts's Python API. Lazy-imports edge_tts
    so this module can be imported (and py_compiled) without the package installed
    -- only calling this function actually requires it.
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
        await communicate.save(str(out_path))

    try:
        asyncio.run(_run())
    except Exception as e:
        raise TTSRenderError(f"edge-tts synthesis failed for voice={voice!r}: {e}") from e


def render_episode_tts(episode_dir: Path, tts_config: dict, resume: bool = True) -> dict:
    """Renders (or reuses) one audio file per script_manifest.json block, measures
    each one's real duration, and atomically writes tts_manifest.json.

    Returns {"manifest": <dict written>, "failures": [(block_id, reason), ...],
    "complete": bool}. Never raises for a per-block synthesis/probe failure -- those
    are collected in `failures` and the manifest is written honestly (status
    "pending", only the successful blocks listed). Raises TTSRenderError only for
    setup problems that make the whole run meaningless (no script_manifest.json, no
    blocks, no voice configured).
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

    audio_dir = episode_paths.audio_dir(episode_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    tts_manifest_path = episode_dir / "tts_manifest.json"
    already_rendered = set()
    if tts_manifest_path.exists():
        try:
            existing_doc = json.loads(tts_manifest_path.read_text(encoding="utf-8"))
            already_rendered = {b.get("block_id") for b in existing_doc.get("blocks", [])}
        except (json.JSONDecodeError, OSError):
            already_rendered = set()

    rendered_blocks = []
    failures = []
    for block in blocks:
        block_id = block.get("block_id")
        text = block.get("narration_text") or ""
        out_path = audio_dir / f"{block_id}.mp3"
        rel_path = episode_paths.relative_to_episode(out_path, episode_dir)

        reused = resume and out_path.exists() and block_id in already_rendered
        if not reused:
            if not text.strip():
                failures.append((block_id, "empty narration_text -- nothing to synthesize"))
                continue
            try:
                _synthesize(text, voice, rate, pitch, volume, out_path)
            except TTSRenderError as e:
                failures.append((block_id, str(e)))
                continue

        try:
            info = media_probe.probe(str(out_path))
        except media_probe.MediaProbeError as e:
            failures.append((block_id, f"could not measure rendered audio: {e}"))
            continue

        duration = info.get("duration_sec")
        if not duration or duration <= 0:
            failures.append((block_id, f"probed duration is not usable: {duration!r}"))
            continue

        rendered_blocks.append({"block_id": block_id, "audio_path": rel_path, "duration_sec": duration})

    all_ok = not failures and len(rendered_blocks) == len(blocks)
    manifest = {
        "episode_id": sm.get("episode_id"),
        "status": "generated" if all_ok else "pending",
        "blocks": rendered_blocks,
    }

    # Atomic write: readers never observe a half-written tts_manifest.json.
    tmp_path = tts_manifest_path.with_name(tts_manifest_path.name + ".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(tts_manifest_path)

    return {"manifest": manifest, "failures": failures, "complete": all_ok}


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode_dir")
    parser.add_argument("--voice", required=True)
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--pitch", default="+0Hz")
    parser.add_argument("--volume", default="+0%")
    parser.add_argument("--no-resume", action="store_true", help="Re-synthesize every block even if audio already exists")
    args = parser.parse_args()

    tts_config = {"voice": args.voice, "rate": args.rate, "pitch": args.pitch, "volume": args.volume}
    try:
        result = render_episode_tts(Path(args.episode_dir), tts_config, resume=not args.no_resume)
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
