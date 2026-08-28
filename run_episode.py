#!/usr/bin/env python3
"""CLI for the documentary content factory.

Usage:
    python run_episode.py init --channel ForeignCarsTH \\
        --topic "Cadillac Cimarron" \\
        --quirk "Cadillac's infamous attempt to turn the GM J-car into a luxury compact"
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES_DIR = ROOT / "episodes"
CHANNELS_DIR = ROOT / "config" / "channels"


def slugify(text: str) -> str:
    """Slugify a topic for use in a folder name.

    Latin text slugifies normally. Non-Latin scripts (Thai, Japanese, Cyrillic, ...)
    have no ASCII form here, so rather than collapsing to an empty string we fall
    back to a short hash of the original topic -- deterministic, so re-running init
    with the same topic still resolves to the same episode folder.
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


def init_episode(channel_id: str, topic: str, quirk: str) -> Path:
    channel = load_channel(channel_id)
    episode_id = f"{channel_id}_{slugify(topic)}"
    episode_dir = EPISODES_DIR / episode_id

    if episode_dir.exists():
        raise SystemExit(f"Episode folder already exists: {episode_dir.relative_to(ROOT)}")

    episode_dir.mkdir(parents=True)

    episode_brief = {
        "episode_id": episode_id,
        "channel_id": channel_id,
        "research_language": channel["research_language"],
        "working_language": channel["working_language"],
        "output_language": channel["output_language"],
        "narration_register": channel["narration_register"],
        "topic": topic,
        "quirk": quirk,
        "target_audience": channel["target_audience"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        # The CLI populates every brief field from the channel config and the
        # command line, so the brief is complete on creation -- there is no further
        # authoring step before Agent A can pick it up.
        "status": "ready_for_producer",
    }
    _write(episode_dir / "episode_brief.json", episode_brief)

    _write(episode_dir / "fact_pack.json", {
        "episode_id": episode_id,
        "status": "pending",
        "research_language": channel["research_language"],
        "working_language": channel["working_language"],
        "quirk_lead": {
            "text": quirk,
            "note": "Research lead only -- not a verified fact. Must not be assumed as the thesis until supported by claims in this fact pack.",
        },
        "claims": [],
    })
    _write(episode_dir / "producer_outline.json", {
        "episode_id": episode_id,
        "status": "pending",
        "thesis": "",
        "beats": [],
    })
    _write(episode_dir / "asset_inventory.json", {
        "episode_id": episode_id,
        "status": "pending",
        "assets": [],
        "beat_coverage": [],
    })
    _write(episode_dir / "final_script.json", {
        "episode_id": episode_id,
        "output_language": channel["output_language"],
        "status": "pending",
        "blocks": [],
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
    parser = argparse.ArgumentParser(description="Documentary content factory CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new episode folder")
    init_parser.add_argument("--channel", required=True, help="Channel ID, e.g. ForeignCarsTH")
    init_parser.add_argument("--topic", required=True, help="Episode topic")
    init_parser.add_argument("--quirk", required=True, help="Episode quirk/angle")

    args = parser.parse_args()

    if args.command == "init":
        episode_dir = init_episode(args.channel, args.topic, args.quirk)
        print(f"Initialized episode at {episode_dir.relative_to(ROOT)}")
        for f in sorted(episode_dir.iterdir()):
            print(f"  {f.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
