#!/usr/bin/env python3
"""Real, executable FFmpeg renderer for a validated edit_plan.json. Not a second
specification -- this actually shells out to ffmpeg and produces
episodes/<episode_id>/render/final.mp4.

Requires the edit_plan to already pass scripts/validate_episode.py with zero
errors (this module runs that validation itself first and refuses to render
otherwise, rather than guessing how to interpret an invalid plan).

Pipeline:
  1. Validate (script_manifest + tts_manifest + asset_inventory + edit_plan).
  2. Narration audio: concatenate each block's TTS audio in script_manifest.json's
     own block order (never tts_manifest's array order) into one AAC track.
  3. Visual clips: for each edit_plan.json clip, in order --
       video clip  -> trim [source_start_sec, source_end_sec] from the source at
                       normal playback rate (no speed changes -- the validator
                       already required timeline duration == source duration),
                       normalize to 1920x1080/30fps/H.264, strip audio (the
                       narration track is the only audio in the final file).
       still clip  -> hold the image for (timeline_end - timeline_start) seconds
                       with the requested still_treatment, normalized the same way.
     Every normalization scales to FIT inside 1920x1080 preserving aspect ratio and
     pads the remainder with black (letterbox/pillarbox) -- archival footage or
     photos with a different aspect ratio are never cropped to fill the frame.
  4. Concatenate the normalized visual clips (same codec/resolution/fps, so a
     lossless concat) into one visual track, then mux it with the narration audio
     track into render/final.mp4.
  5. Clean up temp/ on success; leave it (with logs) on failure for debugging.

Output format (boring V0 standard, broadly compatible): 1920x1080, 30fps, H.264
(yuv420p), AAC audio, MP4 container.

Still treatments (static, slow_zoom_in, slow_zoom_out, pan_left, pan_right) are
implemented with ffmpeg's zoompan filter on top of the same letterboxed/pillarboxed
1920x1080 canvas every clip uses -- deliberately subtle motion, no transition
engine, no motion-graphics system.

CLI usage:
    python scripts/render_episode.py episodes/ForeignCarsTH_example-car

NOTE: this module's ffmpeg subprocess calls are real, complete code, but have not
been executed in this development environment -- ffmpeg/ffprobe are not installed
here (see scripts/preflight.py). They are written to run against the exact
edit_plan.json contract scripts/validate_episode.py enforces, but have not been
exercised against a real render. See the pipeline's first real end-to-end test.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode_paths  # noqa: E402
import validate_episode  # noqa: E402

WIDTH, HEIGHT, FPS = 1920, 1080, 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
PIX_FMT = "yuv420p"
PRESET = "veryfast"

# The visible motion range for zoompan-based still treatments. Deliberately
# subtle -- this is a documentary, not a motion-graphics reel.
_ZOOM_MAX = 1.12


class RenderError(RuntimeError):
    pass


def _require_binaries() -> None:
    for name in ("ffmpeg", "ffprobe"):
        if shutil.which(name) is None:
            raise RenderError(f"'{name}' was not found on PATH. Run `python run_episode.py preflight` for setup help.")


def _run_ffmpeg(cmd: list, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"$ {' '.join(cmd)}\n")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired as e:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("TIMED OUT\n")
        raise RenderError(f"ffmpeg timed out running: {' '.join(cmd)}") from e

    with open(log_path, "a", encoding="utf-8") as log:
        log.write(result.stdout)
        log.write(result.stderr)
        log.write(f"\n[exit code {result.returncode}]\n\n")

    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip()[-2000:]
        raise RenderError(f"ffmpeg failed (see {log_path} for the full log): {tail}")


def _normalize_filter(extra: str = None) -> str:
    """The shared letterbox/pillarbox-preserving normalization every clip gets:
    fit inside WIDTHxHEIGHT preserving aspect ratio, pad the remainder with black,
    fix the sample aspect ratio, force the output frame rate. `extra`, if given, is
    inserted BEFORE the scale/pad (e.g. a zoompan stage for a still).
    """
    base = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS}"
    return f"{extra},{base}" if extra else base


def _still_filter(treatment: str, duration_sec: float) -> str:
    """Builds the full filter graph for one still/document clip: normalize to the
    padded 1920x1080 canvas first, then (for anything but 'static') apply a subtle
    zoompan pan/zoom on top of that canvas -- so the resting frame always shows the
    complete image, and the effect only crops gently into the padded canvas at a
    max zoom of 1.12x.
    """
    frames = max(1, round(duration_sec * FPS))
    canvas = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"

    if treatment == "static" or frames < 2:
        return f"{canvas},fps={FPS}"

    incr = (_ZOOM_MAX - 1.0) / frames

    if treatment == "slow_zoom_in":
        z = f"min(zoom+{incr:.6f},{_ZOOM_MAX})"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif treatment == "slow_zoom_out":
        z = f"if(eq(on,0),{_ZOOM_MAX},max(zoom-{incr:.6f},1.0))"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif treatment == "pan_left":
        z = f"{_ZOOM_MAX}"
        x = f"(iw-iw/zoom)*(1-on/{max(frames-1,1)})"
        y = "ih/2-(ih/zoom/2)"
    elif treatment == "pan_right":
        z = f"{_ZOOM_MAX}"
        x = f"(iw-iw/zoom)*on/{max(frames-1,1)}"
        y = "ih/2-(ih/zoom/2)"
    else:
        raise RenderError(f"Unknown still_treatment: {treatment!r}")

    zoompan = f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    return f"{canvas},{zoompan}"


def _render_video_clip(local_path: Path, source_start: float, source_end: float, out_path: Path, log_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-v", "warning",
        "-ss", str(source_start), "-to", str(source_end),
        "-i", str(local_path),
        "-an",
        "-vf", _normalize_filter(),
        "-c:v", VIDEO_CODEC, "-pix_fmt", PIX_FMT, "-preset", PRESET,
        str(out_path),
    ]
    _run_ffmpeg(cmd, log_path)


def _render_still_clip(local_path: Path, treatment: str, duration_sec: float, out_path: Path, log_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-v", "warning",
        "-loop", "1", "-i", str(local_path),
        "-t", str(duration_sec),
        "-vf", _still_filter(treatment, duration_sec),
        "-r", str(FPS),
        "-c:v", VIDEO_CODEC, "-pix_fmt", PIX_FMT, "-preset", PRESET,
        str(out_path),
    ]
    _run_ffmpeg(cmd, log_path)


def _concat_demuxer(file_paths: list, out_path: Path, log_path: Path, extra_args: list) -> None:
    """Concatenates already-same-codec files via ffmpeg's concat demuxer (lossless
    where extra_args is ["-c", "copy"], or re-encoding to a shared target format
    where it's not -- e.g. muxing narration audio, whose inputs are all the same
    mp3 codec from edge-tts).
    """
    list_path = out_path.with_name(out_path.stem + "_filelist.txt")
    lines = []
    for p in file_paths:
        escaped = str(Path(p).resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = ["ffmpeg", "-y", "-v", "warning", "-f", "concat", "-safe", "0", "-i", str(list_path)] + extra_args + [str(out_path)]
    _run_ffmpeg(cmd, log_path)


def _resolve_asset_path(asset: dict, episode_dir: Path) -> Path:
    local_path = asset.get("local_path")
    if not local_path:
        raise RenderError(f"Asset {asset.get('asset_id')!r} has no local_path -- it must be downloaded before rendering.")
    p = Path(local_path)
    return p if p.is_absolute() else (episode_dir / p)


def render_episode(episode_dir: Path) -> Path:
    episode_dir = Path(episode_dir)
    from tts_gemini_chunks import alignment_gate
    if alignment_gate(episode_dir):
        raise RenderError("Gemini chunk selection has no measured block alignment; rendering is blocked.")

    # 1. Validate everything first. Refuse to render an invalid plan rather than
    # guessing how to interpret it -- checked before even requiring ffmpeg on PATH,
    # so a bad edit_plan is reported clearly regardless of what's installed.
    report = validate_episode.Report()
    sm = validate_episode.load(episode_dir / "script_manifest.json")
    tts = validate_episode.load(episode_dir / "tts_manifest.json")
    ai = validate_episode.load(episode_dir / "asset_inventory.json")
    ep = validate_episode.load(episode_dir / "edit_plan.json")

    sm_blocks = validate_episode.validate_script_manifest(sm, report)
    tts_durations, tts_complete = validate_episode.validate_tts_manifest(tts, sm_blocks, report)
    gate_open = validate_episode.validate_block_coverage_gate(ai, sm_blocks, tts_durations, tts_complete, report)
    validate_episode.validate_edit_plan(ep, sm_blocks, ai, tts_durations, tts_complete, report)
    validate_episode.validate_production_readiness(ep, gate_open, report)

    if report.errors:
        raise RenderError(
            "edit_plan.json (or an input it depends on) fails validation -- refusing to guess. "
            "Run `python run_episode.py validate <episode_id>` for the full report. First errors:\n"
            + "\n".join(f"  - {m}" for m in report.errors[:10])
        )
    if not ep.get("clips"):
        raise RenderError("edit_plan.json has no clips -- nothing to render.")

    # Validation passed -- now confirm we can actually render.
    _require_binaries()

    temp = episode_paths.temp_dir(episode_dir)
    render_dir = episode_paths.render_dir(episode_dir)
    temp.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)
    log_path = temp / "render.log"

    # 2. Narration audio, in script_manifest.json's own block order -- never
    # tts_manifest's array order.
    tts_by_block = {b["block_id"]: b for b in tts.get("blocks", [])}
    audio_paths = []
    for bid in sm_blocks:
        entry = tts_by_block.get(bid)
        audio_path = Path(entry["audio_path"])
        audio_paths.append(audio_path if audio_path.is_absolute() else episode_dir / audio_path)

    narration_path = temp / "narration.m4a"
    _concat_demuxer(
        audio_paths, narration_path, log_path,
        extra_args=["-ar", "44100", "-ac", "2", "-c:a", AUDIO_CODEC, "-b:a", "192k"],
    )

    # 3. Visual clips, in edit_plan.json's order (already validated continuous).
    assets_by_id = {a.get("asset_id"): a for a in ai.get("assets", [])}
    clip_paths = []
    for i, clip in enumerate(ep["clips"]):
        clip_out = temp / f"clip_{i:04d}.mp4"
        asset = assets_by_id[clip["asset_id"]]
        local_path = _resolve_asset_path(asset, episode_dir)
        if not local_path.exists():
            raise RenderError(f"Asset {clip['asset_id']!r}'s local_path does not exist: {local_path}")

        if clip.get("segment_id"):
            _render_video_clip(local_path, clip["source_start_sec"], clip["source_end_sec"], clip_out, log_path)
        else:
            duration = clip["timeline_end_sec"] - clip["timeline_start_sec"]
            treatment = clip.get("still_treatment", "static")
            _render_still_clip(local_path, treatment, duration, clip_out, log_path)

        clip_paths.append(clip_out)

    # 4. Concatenate the normalized visual clips (same codec/res/fps -> lossless
    # concat), then mux with the narration audio.
    visual_track = temp / "visual_track.mp4"
    _concat_demuxer(clip_paths, visual_track, log_path, extra_args=["-c", "copy"])

    final_path = render_dir / "final.mp4"
    mux_cmd = [
        "ffmpeg", "-y", "-v", "warning",
        "-i", str(visual_track),
        "-i", str(narration_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "copy",
        "-shortest",
        str(final_path),
    ]
    _run_ffmpeg(mux_cmd, log_path)

    # 5. Success -- record it and clean up intermediates.
    ep["status"] = "rendered"
    ep_path = episode_dir / "edit_plan.json"
    tmp_ep_path = ep_path.with_name(ep_path.name + ".tmp")
    tmp_ep_path.write_text(json.dumps(ep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_ep_path.replace(ep_path)

    shutil.rmtree(temp, ignore_errors=True)

    return final_path


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode_dir")
    args = parser.parse_args()

    try:
        final_path = render_episode(Path(args.episode_dir))
    except RenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Rendered {final_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
