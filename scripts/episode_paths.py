#!/usr/bin/env python3
"""The one canonical episode-local directory layout, shared by every script that
reads or writes media so the naming never drifts between them.

    episodes/<episode_id>/
        master_script.md
        script_manifest.json
        tts_manifest.json
        asset_inventory.json
        edit_plan.json

        audio/              -- per-block TTS output (tts_render.py)
        media/
            raw/             -- downloaded source videos/images/documents (media_download.py)
            inspection/      -- media_probe.py contact-sheet frames
        render/              -- final.mp4 (render_episode.py)
        temp/                -- intermediate render artifacts, safe to delete

Not a framework -- just the directory names in one place. Every JSON file in the
episode directory should store paths RELATIVE to the episode directory (e.g.
"audio/block_001.mp3", "media/raw/video_014.mp4") so the folder stays portable if
moved or copied elsewhere; these helpers exist to make writing those relative paths
consistent.
"""
from pathlib import Path


def audio_dir(episode_dir: Path) -> Path:
    return episode_dir / "audio"


def media_dir(episode_dir: Path) -> Path:
    return episode_dir / "media"


def media_raw_dir(episode_dir: Path) -> Path:
    return episode_dir / "media" / "raw"


def media_inspection_dir(episode_dir: Path) -> Path:
    return episode_dir / "media" / "inspection"


def render_dir(episode_dir: Path) -> Path:
    return episode_dir / "render"


def temp_dir(episode_dir: Path) -> Path:
    return episode_dir / "temp"


def relative_to_episode(path: Path, episode_dir: Path) -> str:
    """Best-effort relative path for storing in episode JSON. Falls back to the
    absolute path (as a string) if `path` isn't actually under `episode_dir` --
    that's a real situation worth keeping visible, not hiding behind an exception.
    """
    try:
        return str(Path(path).resolve().relative_to(Path(episode_dir).resolve()))
    except ValueError:
        return str(Path(path))
