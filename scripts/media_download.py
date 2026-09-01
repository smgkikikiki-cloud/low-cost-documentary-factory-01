#!/usr/bin/env python3
"""Deterministic media acquisition: download ONE selected video (via yt-dlp) or ONE
selected direct-URL asset (image/PDF/brochure/etc., via a plain HTTP GET).

Claude (in B-DISCOVER) already decided which URL is worth fetching -- via
scripts/media_search.py's candidates, or a direct URL it already knows about (e.g.
from a script_manifest.json source_ref, or its own web/search capability). This
module only executes the fetch of ONE already-selected item. It never searches, it
never scrapes, it never mass-downloads.

CLI usage:
    python scripts/media_download.py video <url> --out-dir episodes/<id>/media/raw
    python scripts/media_download.py asset <url> --out-dir episodes/<id>/media/raw [--filename NAME]

Importable:
    download_video(url, out_dir, max_height=1080) -> dict
    download_direct_asset(url, out_dir, filename=None) -> dict
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

_USER_AGENT = "low-cost-documentary-factory/1.0 (+deterministic single-asset fetch, not a scraper)"
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


class MediaDownloadError(RuntimeError):
    pass


def _require_yt_dlp() -> None:
    if shutil.which("yt-dlp") is None:
        raise MediaDownloadError(
            "'yt-dlp' was not found on PATH. Install it (pip install yt-dlp, or the standalone binary) "
            "before downloading video."
        )


def download_video(url: str, out_dir, max_height: int = 1080, timeout_sec: int = 1800) -> dict:
    """Downloads exactly ONE video via yt-dlp into out_dir, preferring a source at
    or below max_height (an audio-led documentary doesn't need 4K), letting yt-dlp
    merge separate video/audio formats into one file as needed. Does NOT trim the
    result -- the full original is kept intact; B-DISCOVER's usable_segments refer
    to ranges inside it, recorded separately in asset_inventory.json.

    Returns {"local_path": <str, absolute>, "filename": <str>}.
    """
    _require_yt_dlp()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_template = str(out_dir / "%(id)s.%(ext)s")
    fmt = f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"
    cmd = [
        "yt-dlp",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-simulate",
        "--print", "after_move:filepath",
        "-o", out_template,
        "--",
        url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        raise MediaDownloadError(f"yt-dlp download timed out after {timeout_sec}s for {url}") from e
    if result.returncode != 0:
        raise MediaDownloadError(f"yt-dlp failed for {url}: {result.stderr.strip()[-2000:]}")

    # yt-dlp reports the actual merged path even on an already-downloaded source.
    # Directory-difference guessing previously mistook a successful resume for failure.
    paths = [Path(line.strip()).resolve() for line in result.stdout.splitlines() if line.strip()]
    video_files = [p for p in paths if p.is_relative_to(out_dir.resolve()) and p.is_file()
                   and p.suffix.lower() in _VIDEO_EXTENSIONS]
    if len(set(video_files)) != 1:
        raise MediaDownloadError("yt-dlp did not report exactly one existing output video")
    chosen = video_files[0]
    return {"local_path": str(chosen.resolve()), "filename": chosen.name}


def download_direct_asset(url: str, out_dir, filename: str = None, timeout_sec: int = 120) -> dict:
    """Downloads exactly the given URL (image/PDF/brochure/etc.) into out_dir via a
    plain HTTP GET -- no scraping, no crawling, no link-following. `filename`, if
    given, is used as-is (sanitized); otherwise it's derived from the URL's path.

    Returns {"local_path": <str, absolute>, "filename": <str>, "content_type": <str|None>, "size_bytes": <int>}.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if filename:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    else:
        from urllib.parse import urlparse
        url_path = urlparse(url).path
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(url_path).name) or "asset"

    dest_path = out_dir / safe_name
    if dest_path.exists():
        base, suffix = dest_path.stem, dest_path.suffix
        i = 2
        while dest_path.exists():
            dest_path = out_dir / f"{base}_{i}{suffix}"
            i += 1

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            content_type = resp.headers.get("Content-Type")
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise MediaDownloadError(f"HTTP {e.code} fetching {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise MediaDownloadError(f"Failed to fetch {url}: {e.reason}") from e
    except TimeoutError as e:
        raise MediaDownloadError(f"Timed out fetching {url} after {timeout_sec}s") from e

    dest_path.write_bytes(data)
    return {
        "local_path": str(dest_path.resolve()),
        "filename": dest_path.name,
        "content_type": content_type,
        "size_bytes": len(data),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_video = sub.add_parser("video", help="Download one selected video via yt-dlp")
    p_video.add_argument("url")
    p_video.add_argument("--out-dir", required=True)
    p_video.add_argument("--max-height", type=int, default=1080)

    p_asset = sub.add_parser("asset", help="Download one selected direct-URL asset (image/PDF/etc.)")
    p_asset.add_argument("url")
    p_asset.add_argument("--out-dir", required=True)
    p_asset.add_argument("--filename", default=None)

    args = parser.parse_args()

    try:
        if args.command == "video":
            result = download_video(args.url, args.out_dir, max_height=args.max_height)
        else:
            result = download_direct_asset(args.url, args.out_dir, filename=args.filename)
    except MediaDownloadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
