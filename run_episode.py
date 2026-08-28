#!/usr/bin/env python3
"""CLI for the documentary content factory.

Usage:
    python run_episode.py init --channel ForeignCarsTH \\
        --topic "Cadillac Cimarron" \\
        --quirk "Cadillac's infamous attempt to turn the GM J-car into a luxury compact"
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES_DIR = ROOT / "episodes"
CHANNELS_DIR = ROOT / "config" / "channels"


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


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
        "language": channel["language"],
        "topic": topic,
        "quirk": quirk,
        "target_audience": channel["target_audience"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
    }
    _write(episode_dir / "episode_brief.json", episode_brief)

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
    })
    _write(episode_dir / "final_script.json", {
        "episode_id": episode_id,
        "status": "pending",
        "scenes": [],
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
