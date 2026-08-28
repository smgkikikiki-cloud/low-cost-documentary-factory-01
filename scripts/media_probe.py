#!/usr/bin/env python3
"""Deterministic media-inspection helper for Agent B (B-DISCOVER).

Thin wrapper around ffprobe/ffmpeg -- no computer vision, no embeddings, no
scene-understanding model. It gives Agent B two things it needs to honestly fill in
asset_inventory.json's video fields (duration_sec, usable_segments) without watching
every frame of a long source video:

  1. probe(path)              -- duration/dimensions/fps/codec via ffprobe
  2. coarse_contact_sheet(...) -- a handful of frames spread across the WHOLE video,
                                   for a first pass ("where does anything interesting
                                   happen?")
  3. fine_contact_sheet(...)  -- a handful of frames spread across ONE time window,
                                   for a closer look once the coarse pass suggests a
                                   region is worth recording as a usable_segment

Frame counts are adaptive (target ~20-30 frames, never below a minimum interval)
rather than a hardcoded "every 5 seconds" rule, so a 2-minute clip and a 20-minute
clip both get a sensible, bounded number of frames to look at.

Contact-sheet frames are written into a subdirectory of `out_dir` scoped to the
source file (its filename stem plus a short hash of its resolved path), never
directly into `out_dir` itself -- so inspecting several different source videos
into the same base inspection directory (e.g.
`episodes/<id>/media/inspection/`) can never let one video's frames overwrite
another's, regardless of generic `coarse_000...`/`fine_000...` naming. A `fine`
pass is further scoped under its own `[start_sec, end_sec]` window subdirectory
(e.g. `fine_0055.00_0085.00/`), so a later fine pass over a DIFFERENT window of the
SAME source can't overwrite an earlier window's evidence either. Re-inspecting the
exact same source (a `coarse` pass, or a `fine` pass over the exact same window)
intentionally overwrites its own previous frames -- ffmpeg's `-y` -- since that's
just a fresher look at the same evidence, not a collision.

This tool only produces evidence for Agent B to look at. It never writes
asset_inventory.json itself, and it never invents timestamps -- usable_segments must
still be recorded by hand (by the agent, after actually viewing the frames this
produces), never derived automatically from this tool's output.

Requires ffprobe and ffmpeg on PATH. Neither is required to import this module --
only to actually call probe()/contact sheet functions, which raise a clear
FileNotFoundError-derived error if the binaries are missing.

CLI usage:
    python scripts/media_probe.py probe <path>
    python scripts/media_probe.py contact-sheet <path> --out-dir DIR [--target-frames 25] [--min-interval 1.0]
    python scripts/media_probe.py contact-sheet <path> --out-dir DIR --start 55 --end 85 [--target-frames 12] [--min-interval 0.5]

--out-dir is a shared BASE directory (e.g. episodes/<id>/media/inspection) -- pass
the same one for every video you inspect in an episode. Frames actually land under
a per-source subdirectory of it, so different videos never collide; see
_source_scoped_dir().
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


class MediaProbeError(RuntimeError):
    pass


def _require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise MediaProbeError(
            f"'{name}' was not found on PATH. This environment does not have it installed; "
            f"install ffmpeg (which provides both ffprobe and ffmpeg) before calling this function."
        )


def probe(path: str) -> dict:
    """Return duration_sec, width, height, fps, codec_name, format_name for a media file.

    Raises MediaProbeError if ffprobe is missing or the file can't be probed.
    """
    _require_binary("ffprobe")
    p = Path(path)
    if not p.exists():
        raise MediaProbeError(f"No such file: {path}")

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,format_name",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json",
        str(p),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
    except subprocess.CalledProcessError as e:
        raise MediaProbeError(f"ffprobe failed on {path}: {e.stderr.strip()}") from e
    except subprocess.TimeoutExpired as e:
        raise MediaProbeError(f"ffprobe timed out on {path}") from e

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

    fps = None
    if video_stream and video_stream.get("r_frame_rate"):
        num, _, den = video_stream["r_frame_rate"].partition("/")
        try:
            den_f = float(den) if den else 1.0
            fps = float(num) / den_f if den_f else None
        except ValueError:
            fps = None

    return {
        "path": str(p),
        "duration_sec": float(fmt["duration"]) if fmt.get("duration") else None,
        "format_name": fmt.get("format_name"),
        "width": video_stream.get("width") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "fps": fps,
        "codec_name": video_stream.get("codec_name") if video_stream else None,
    }


def compute_sample_interval(duration_sec: float, target_frames: int = 25, min_interval_sec: float = 1.0) -> float:
    """Adaptive sampling interval: spread ~target_frames frames across duration_sec,
    but never sample more densely than min_interval_sec apart.

    Pure arithmetic, no I/O -- deterministic and unit-testable without ffmpeg.
    """
    if duration_sec <= 0 or target_frames <= 0:
        return min_interval_sec
    return max(duration_sec / target_frames, min_interval_sec)


def _source_scoped_dir(path: str, base_out_dir: str) -> Path:
    """Deterministic, collision-safe subdirectory of base_out_dir for this source
    file's inspection frames: <stem>_<8-char-hash-of-resolved-path>/. The same
    source path always maps to the same subdirectory (so re-inspecting it only
    overwrites its own old frames); two different source files never collide, even
    if they happen to share a filename stem, because the hash is over the full
    resolved path.
    """
    resolved = str(Path(path).resolve())
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(path).stem) or "source"
    short_hash = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]
    return Path(base_out_dir) / f"{safe_stem}_{short_hash}"


def _extract_frames(path: str, timestamps: list, out_dir: str, prefix: str, window_subdir: str = None) -> list:
    _require_binary("ffmpeg")
    out = _source_scoped_dir(path, out_dir)
    if window_subdir:
        out = out / window_subdir
    out.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    for i, ts in enumerate(timestamps):
        frame_path = out / f"{prefix}_{i:03d}_t{ts:07.2f}.jpg"
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(ts),
            "-i", str(path),
            "-frames:v", "1",
            "-q:v", "3",
            str(frame_path),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        except subprocess.CalledProcessError as e:
            raise MediaProbeError(f"ffmpeg frame extraction failed at t={ts}s on {path}: {e.stderr.strip()}") from e
        except subprocess.TimeoutExpired as e:
            raise MediaProbeError(f"ffmpeg timed out extracting frame at t={ts}s on {path}") from e
        frame_paths.append({"timestamp_sec": ts, "frame_path": str(frame_path)})
    return frame_paths


def coarse_contact_sheet(path: str, out_dir: str, target_frames: int = 25, min_interval_sec: float = 1.0) -> list:
    """Sample frames across the FULL duration of the video for a first-pass look.

    Frames are written under a subdirectory of out_dir scoped to this source file
    (see _source_scoped_dir) -- passing the same base out_dir (e.g.
    episodes/<id>/media/inspection) for every video you inspect is safe; different
    sources never overwrite each other.

    Returns a list of {timestamp_sec, frame_path}. Does not write asset_inventory.json
    or record any usable_segments -- that remains a judgment call made after actually
    looking at these frames.
    """
    info = probe(path)
    duration = info["duration_sec"]
    if not duration or duration <= 0:
        raise MediaProbeError(f"Could not determine a usable duration for {path}")

    interval = compute_sample_interval(duration, target_frames, min_interval_sec)
    timestamps = []
    t = 0.0
    while t < duration:
        timestamps.append(round(min(t, max(duration - 0.05, 0)), 2))
        t += interval

    return _extract_frames(path, timestamps, out_dir, prefix="coarse")


def fine_contact_sheet(
    path: str, start_sec: float, end_sec: float, out_dir: str,
    target_frames: int = 12, min_interval_sec: float = 0.5,
) -> list:
    """Sample frames across ONE time window for a closer look, after a coarse pass
    suggested that window contains useful material.

    Frames are written under the same per-source subdirectory as coarse_contact_sheet
    (see _source_scoped_dir) -- safe to pass the same base out_dir across many
    inspections of many different source videos -- AND further under a
    window-scoped subdirectory keyed to [start_sec, end_sec] (e.g.
    fine_0055.00_0085.00/), so a later fine pass over a DIFFERENT window of the same
    source never overwrites an earlier window's frames. Re-running the exact same
    window again intentionally overwrites its own previous frames.

    Returns a list of {timestamp_sec, frame_path}.
    """
    if end_sec <= start_sec:
        raise MediaProbeError(f"end_sec ({end_sec}) must exceed start_sec ({start_sec})")

    window = end_sec - start_sec
    interval = compute_sample_interval(window, target_frames, min_interval_sec)
    timestamps = []
    t = start_sec
    while t < end_sec:
        timestamps.append(round(min(t, end_sec - 0.02), 2))
        t += interval

    window_subdir = f"fine_{start_sec:07.2f}_{end_sec:07.2f}"
    return _extract_frames(path, timestamps, out_dir, prefix="fine", window_subdir=window_subdir)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Print duration/dimensions/fps/codec as JSON")
    p_probe.add_argument("path")

    p_sheet = sub.add_parser("contact-sheet", help="Extract a coarse or fine contact sheet of frames")
    p_sheet.add_argument("path")
    p_sheet.add_argument("--out-dir", required=True)
    p_sheet.add_argument("--start", type=float, default=None, help="Window start (sec). Omit for a coarse full-video pass.")
    p_sheet.add_argument("--end", type=float, default=None, help="Window end (sec). Required if --start is given.")
    p_sheet.add_argument("--target-frames", type=int, default=None)
    p_sheet.add_argument("--min-interval", type=float, default=None)

    args = parser.parse_args()

    try:
        if args.command == "probe":
            print(json.dumps(probe(args.path), indent=2))
        elif args.command == "contact-sheet":
            if args.start is not None:
                if args.end is None:
                    parser.error("--end is required when --start is given")
                frames = fine_contact_sheet(
                    args.path, args.start, args.end, args.out_dir,
                    target_frames=args.target_frames or 12,
                    min_interval_sec=args.min_interval if args.min_interval is not None else 0.5,
                )
            else:
                frames = coarse_contact_sheet(
                    args.path, args.out_dir,
                    target_frames=args.target_frames or 25,
                    min_interval_sec=args.min_interval if args.min_interval is not None else 1.0,
                )
            print(json.dumps(frames, indent=2))
    except MediaProbeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
