#!/usr/bin/env python3
"""Deterministic video-candidate metadata search via yt-dlp. No AI search engine,
no scraping framework -- this shells out to the `yt-dlp` binary and returns
structured metadata for candidates, WITHOUT downloading any media.

Claude (in B-DISCOVER) decides what to search for and which candidate, if any, is
worth downloading -- this module only executes a given query and reports what
yt-dlp found.

CLI usage:
    python scripts/media_search.py "Volvo 480 pop-up headlights" --max-results 5

Importable:
    search_video_candidates(query, max_results=5) -> list[dict]
"""
import argparse
import json
import shutil
import subprocess
import sys


class MediaSearchError(RuntimeError):
    pass


def _require_yt_dlp() -> None:
    if shutil.which("yt-dlp") is None:
        raise MediaSearchError(
            "'yt-dlp' was not found on PATH. Install it (pip install yt-dlp, or the standalone binary) "
            "before searching for video candidates."
        )


def search_video_candidates(query: str, max_results: int = 5, timeout_sec: int = 180) -> list:
    """Runs `yt-dlp --skip-download --dump-json "ytsearchN:query"` and returns a
    list of candidate metadata dicts. Never downloads any media -- --skip-download
    resolves each result's real metadata (including duration) without fetching the
    video/audio itself.

    Each returned dict: title, webpage_url, duration_sec, uploader, upload_date,
    thumbnail_url, description_snippet. A field is None if yt-dlp didn't return it
    for that result -- never guessed or invented.
    """
    _require_yt_dlp()
    if max_results < 1:
        raise MediaSearchError("max_results must be >= 1")

    cmd = ["yt-dlp", "--skip-download", "--dump-json", "--no-warnings", f"ytsearch{max_results}:{query}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        raise MediaSearchError(f"yt-dlp search timed out after {timeout_sec}s for query {query!r}") from e

    if result.returncode != 0 and not result.stdout.strip():
        raise MediaSearchError(f"yt-dlp search failed for query {query!r}: {result.stderr.strip()[-2000:]}")

    candidates = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        description = entry.get("description")
        candidates.append({
            "title": entry.get("title"),
            "webpage_url": entry.get("webpage_url") or entry.get("original_url") or entry.get("url"),
            "duration_sec": entry.get("duration"),
            "uploader": entry.get("uploader") or entry.get("channel"),
            "upload_date": entry.get("upload_date"),
            "thumbnail_url": entry.get("thumbnail"),
            "description_snippet": (description[:300] if description else None),
        })
    return candidates


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--max-results", type=int, default=5)
    args = parser.parse_args()

    try:
        candidates = search_video_candidates(args.query, args.max_results)
    except MediaSearchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(candidates, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
