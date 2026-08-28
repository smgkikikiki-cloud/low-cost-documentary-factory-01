#!/usr/bin/env python3
"""CLI for the script-first documentary production repository.

Usage:
    python run_episode.py ingest --channel ForeignCarsTH \\
        --topic "Jeep Wrangler YJ" \\
        --script /path/to/master_script.md

An upstream OpenAI writer researches the topic and produces a complete, editorially
locked Thai master script OUTSIDE this repository. `ingest` is the entry point into
production: it creates the episode directory, preserves master_script.md verbatim,
deterministically parses it into script_manifest.json (no LLM), and creates pending
stubs for the files production fills in next (tts_manifest.json, asset_inventory.json,
edit_plan.json). There is no quirk, fact_pack, or producer_outline in this pipeline --
those belonged to the retired pre-script-first architecture (see legacy/).
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import ingest_script  # noqa: E402

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
    return json.loads(channel_path.read_text())


def ingest_episode(channel_id: str, topic: str, script_path: Path) -> Path:
    channel = load_channel(channel_id)
    episode_id = f"{channel_id}_{slugify(topic)}"
    episode_dir = EPISODES_DIR / episode_id

    if episode_dir.exists():
        raise SystemExit(f"Episode folder already exists: {episode_dir.relative_to(ROOT)}")
    if not script_path.exists():
        raise SystemExit(f"No such script file: {script_path}")

    episode_dir.mkdir(parents=True)

    manifest = ingest_script.ingest(
        script_path=script_path,
        episode_dir=episode_dir,
        episode_id=episode_id,
        channel_id=channel_id,
        language=channel["output_language"],
        topic=topic,
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

    return episode_dir


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Script-first documentary production CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest a locked upstream master script and start a new production episode",
    )
    ingest_parser.add_argument("--channel", required=True, help="Channel ID, e.g. ForeignCarsTH")
    ingest_parser.add_argument("--topic", required=True, help="Episode topic (record-keeping only)")
    ingest_parser.add_argument("--script", required=True, help="Path to the locked master_script.md")

    args = parser.parse_args()

    if args.command == "ingest":
        episode_dir = ingest_episode(args.channel, args.topic, Path(args.script))
        print(f"Ingested episode at {episode_dir.relative_to(ROOT)}")
        for f in sorted(episode_dir.iterdir()):
            print(f"  {f.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
