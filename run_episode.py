#!/usr/bin/env python3
"""CLI for the script-first documentary production repository.

Usage:
    python run_episode.py preflight
    python run_episode.py ingest --channel ForeignCarsTH --topic "Jeep Wrangler YJ" --script /path/to/master_script.md
    python run_episode.py tts <episode_id> [--profile google-chirp3]
    # Claude performs B-DISCOVER (writes asset_inventory.json)
    # Claude performs B-EDIT (writes edit_plan.json)
    python run_episode.py validate <episode_id>
    python run_episode.py render <episode_id>
    python run_episode.py status <episode_id>

An upstream OpenAI writer researches the topic and produces a complete, editorially
locked Thai master script OUTSIDE this repository. `ingest` is the entry point into
production: it creates the episode directory, preserves master_script.md verbatim,
deterministically parses it into script_manifest.json (no LLM), and creates pending
stubs for the files production fills in next (tts_manifest.json, asset_inventory.json,
edit_plan.json). There is no quirk, fact_pack, or producer_outline in this pipeline --
those belonged to the retired pre-script-first architecture (see legacy/).

This is deliberately NOT a full orchestrator: `tts`, `validate`, and `render` are
real deterministic commands. B-DISCOVER and B-EDIT are performed by the Claude Code
session itself (reading/writing the JSON files directly) -- there is no Python code
here that invokes a model.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import ingest_script  # noqa: E402
import preflight as preflight_mod  # noqa: E402
import tts_render  # noqa: E402
import validate_episode  # noqa: E402
import episode_paths  # noqa: E402
import tts_gemini_chunks  # noqa: E402

ROOT = Path(__file__).resolve().parent
EPISODES_DIR = ROOT / "episodes"
CHANNELS_DIR = ROOT / "config" / "channels"


def slugify(text: str) -> str:
    """Slugify a topic for use in a folder name.

    Latin text slugifies normally. Non-Latin scripts (Thai, Japanese, Cyrillic, ...)
    have no ASCII form here, so rather than collapsing to an empty string we fall
    back to a short hash of the original topic -- deterministic, so re-running
    ingest with the same topic still resolves to the same episode folder.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    if slug:
        return slug
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]
    return f"topic-{digest}"


def load_channel(channel_id: str) -> dict:
    channel_path = CHANNELS_DIR / f"{channel_id}.json"
    if not channel_path.exists():
        raise SystemExit(
            f"Unknown channel '{channel_id}': no config at {channel_path.relative_to(ROOT)}"
        )
    return json.loads(channel_path.read_text(encoding="utf-8"))


def resolve_episode_dir(episode_id: str) -> Path:
    p = Path(episode_id)
    if p.is_dir():
        return p
    candidate = EPISODES_DIR / episode_id
    if candidate.is_dir():
        return candidate
    raise SystemExit(f"Episode not found: {episode_id!r} (looked at {p} and {candidate})")


def ingest_episode(channel_id: str, topic: str, script_path: Path) -> Path:
    channel = load_channel(channel_id)
    episode_id = f"{channel_id}_{slugify(topic)}"
    episode_dir = EPISODES_DIR / episode_id

    if episode_dir.exists():
        raise SystemExit(f"Episode folder already exists: {episode_dir.relative_to(ROOT)}")
    if not script_path.exists():
        raise SystemExit(f"No such script file: {script_path}")

    # Atomicity: parse/validate the script BEFORE creating anything on disk. A
    # malformed script (no title, no narration) raises here, so it never leaves a
    # half-created episode directory that would block a later retry with the same
    # episode_id -- see scripts/ingest_script.py's parse_and_validate().
    raw_bytes, script_sha256, title, optional_deck, blocks = ingest_script.parse_and_validate(script_path)

    episode_dir.mkdir(parents=True)
    try:
        manifest = ingest_script.write_episode_files(
            episode_dir, raw_bytes, script_sha256, title, optional_deck, blocks,
            episode_id=episode_id, channel_id=channel_id,
            language=channel["output_language"], topic=topic,
        )
        _write(episode_dir / "script_manifest.json", manifest)

        _write(episode_dir / "tts_manifest.json", {
            "episode_id": episode_id,
            "status": "pending",
            "blocks": [],
        })
        _write(episode_dir / "asset_inventory.json", {
            "episode_id": episode_id,
            "status": "pending",
            "assets": [],
            "block_coverage": [],
        })
        _write(episode_dir / "edit_plan.json", {
            "episode_id": episode_id,
            "status": "pending",
            "clips": [],
        })
    except Exception:
        # Belt-and-suspenders: parse_and_validate already ruled out the common
        # failure (malformed script), but if something else goes wrong mid-write
        # (disk full, permissions, ...), don't leave a half-written directory behind.
        shutil.rmtree(episode_dir, ignore_errors=True)
        raise

    return episode_dir


def select_tts_config(channel: dict, profile: str = None) -> dict:
    """The channel's active `tts` block, or one of its named `tts_profiles`.

    Profiles exist so a voice/provider change is a one-word switch with a working
    rollback -- the previous configuration stays in the file rather than being
    overwritten. `tts` remains the single source of truth for what production
    uses when no profile is named.
    """
    if profile:
        profiles = channel.get("tts_profiles") or {}
        if profile not in profiles:
            available = ", ".join(sorted(profiles)) or "(none defined)"
            raise SystemExit(
                f"Channel {channel.get('channel_id')!r} has no tts profile {profile!r}. Available: {available}"
            )
        return profiles[profile]

    tts_config = channel.get("tts")
    if not tts_config:
        raise SystemExit(
            f"Channel {channel.get('channel_id')!r} has no 'tts' config -- "
            f"see config/channels/{channel.get('channel_id')}.json"
        )
    return tts_config


def run_tts(episode_dir: Path, profile: str = None, dry_run=False, timeout_sec=120) -> int:
    sm = json.loads((episode_dir / "script_manifest.json").read_text(encoding="utf-8"))
    channel = load_channel(sm["channel_id"])
    tts_config = select_tts_config(channel, profile)

    if tts_config.get("provider") == "gemini-tts":
        try:
            result = tts_gemini_chunks.render_chunks(episode_dir, tts_config, dry_run=dry_run, timeout_sec=timeout_sec)
        except (tts_gemini_chunks.ChunkError, OSError, ValueError, KeyError, TypeError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if dry_run:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(f"Chunk manifest: {result['manifest_path']}")
        print(f"Chunks: {result['manifest']['status']}; BLOCK ALIGNMENT REQUIRED before B-DISCOVER.")
        print("Existing tts_manifest.json was preserved; its old block timings do not authorize Gemini discovery.")
        for chunk_id, reason in result["failures"]:
            print(f"  FAILED {chunk_id}: {reason}", file=sys.stderr)
        return 0 if result["complete"] else 1
    if dry_run:
        print("error: --dry-run currently supports Gemini chunk planning only", file=sys.stderr)
        return 1

    try:
        result = tts_render.render_episode_tts(episode_dir, tts_config, timeout_sec=timeout_sec)
    except tts_render.TTSRenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"tts_manifest.json: status={result['manifest']['status']!r}, "
          f"{len(result['manifest']['blocks'])}/{len(sm['blocks'])} block(s) rendered/measured")
    for block_id, reason in result["failures"]:
        print(f"  FAILED  {block_id}: {reason}", file=sys.stderr)
    return 0 if result["complete"] else 1


def run_validate(episode_dir: Path, quiet: bool) -> int:
    # Delegate to scripts/validate_episode.py's own CLI entry point so the two
    # commands can never drift out of sync with each other.
    argv_backup = sys.argv
    try:
        sys.argv = ["validate_episode.py", str(episode_dir)] + (["-q"] if quiet else [])
        return validate_episode.main()
    finally:
        sys.argv = argv_backup


def run_render(episode_dir: Path) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    import render_episode  # noqa: E402 (imported lazily -- pulls in validate_episode + needs ffmpeg only when actually called)

    try:
        final_path = render_episode.render_episode(episode_dir)
    except render_episode.RenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Rendered {final_path}")
    return 0


def compute_status(episode_dir: Path) -> str:
    """Derives the next incomplete stage by reading the JSON files directly and
    reusing validate_episode.py's own logic -- no separate state machine, no state
    stored anywhere but the files themselves.
    """
    sm_path = episode_dir / "script_manifest.json"
    if not sm_path.exists():
        return "NOT INGESTED"
    sm = validate_episode.load(sm_path)
    silent = validate_episode.Report()
    sm_blocks = validate_episode.validate_script_manifest(sm, silent)

    chunk_gate = tts_gemini_chunks.alignment_gate(episode_dir)
    if chunk_gate:
        return chunk_gate

    tts_path = episode_dir / "tts_manifest.json"
    tts = validate_episode.load(tts_path) if tts_path.exists() else {}
    tts_durations, tts_complete = validate_episode.validate_tts_manifest(tts, sm_blocks, validate_episode.Report())
    if not tts.get("blocks"):
        return "SCRIPT INGESTED"
    if not tts_complete:
        return "TTS REQUIRED"

    ai_path = episode_dir / "asset_inventory.json"
    ai = validate_episode.load(ai_path) if ai_path.exists() else {}
    gate_open = validate_episode.validate_block_coverage_gate(ai, sm_blocks, tts_durations, tts_complete, validate_episode.Report())
    if not gate_open:
        return "B-DISCOVER REQUIRED"

    ep_path = episode_dir / "edit_plan.json"
    ep = validate_episode.load(ep_path) if ep_path.exists() else {}
    final_mp4 = episode_paths.render_dir(episode_dir) / "final.mp4"
    if ep.get("status") == "rendered" and final_mp4.exists():
        return "RENDERED"
    if not ep.get("clips"):
        return "B-EDIT REQUIRED"

    edit_report = validate_episode.Report()
    validate_episode.validate_edit_plan(ep, sm_blocks, ai, tts_durations, tts_complete, edit_report)
    validate_episode.validate_production_readiness(ep, gate_open, edit_report)
    if edit_report.errors:
        return "B-EDIT REQUIRED"
    return "READY TO RENDER"


def _write(path: Path, data: dict) -> None:
    # Explicit UTF-8: episode JSON (e.g. script_manifest.json's Thai narration_text)
    # must not depend on the platform's default text encoding -- Path.write_text()
    # without encoding= uses locale.getpreferredencoding(False), which on Windows is
    # commonly cp1252 and cannot represent Thai characters at all.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Script-first documentary production CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("preflight", help="Check ffmpeg/ffprobe/yt-dlp/edge-tts/jsonschema availability")

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest a locked upstream master script and start a new production episode",
    )
    ingest_parser.add_argument("--channel", required=True, help="Channel ID, e.g. ForeignCarsTH")
    ingest_parser.add_argument("--topic", required=True, help="Episode topic (record-keeping only)")
    ingest_parser.add_argument("--script", required=True, help="Path to the locked master_script.md")

    tts_parser = subparsers.add_parser("tts", help="Render narration audio and measure real durations")
    tts_parser.add_argument("episode", help="episode_id or path to the episode folder")
    tts_parser.add_argument("--dry-run", action="store_true", help="Plan Gemini chunks without credentials, API calls or file changes")
    tts_parser.add_argument("--timeout", type=float, default=120, help="Wall-clock timeout per request; independent of the 120s audio cap")
    tts_parser.add_argument("--profile", default=None,
                            help="Use a named entry from the channel's tts_profiles (e.g. google-chirp3) "
                                 "instead of its active 'tts' config")

    validate_parser = subparsers.add_parser("validate", help="Run the deterministic cross-file validator")
    validate_parser.add_argument("episode", help="episode_id or path to the episode folder")
    validate_parser.add_argument("-q", "--quiet", action="store_true")

    render_parser = subparsers.add_parser("render", help="Render the validated edit_plan.json to final.mp4")
    render_parser.add_argument("episode", help="episode_id or path to the episode folder")

    status_parser = subparsers.add_parser("status", help="Show the next incomplete production stage")
    status_parser.add_argument("episode", help="episode_id or path to the episode folder")

    args = parser.parse_args()

    if args.command == "preflight":
        return preflight_mod._main()

    if args.command == "ingest":
        episode_dir = ingest_episode(args.channel, args.topic, Path(args.script))
        print(f"Ingested episode at {episode_dir.relative_to(ROOT)}")
        for f in sorted(episode_dir.iterdir()):
            print(f"  {f.relative_to(ROOT)}")
        return 0

    if args.command == "tts":
        return run_tts(resolve_episode_dir(args.episode), args.profile, args.dry_run, args.timeout)

    if args.command == "validate":
        return run_validate(resolve_episode_dir(args.episode), args.quiet)

    if args.command == "render":
        return run_render(resolve_episode_dir(args.episode))

    if args.command == "status":
        episode_dir = resolve_episode_dir(args.episode)
        print(compute_status(episode_dir))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
