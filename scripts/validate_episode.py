#!/usr/bin/env python3
"""Deterministic, topic-independent validator for one script-first production episode.

Usage:
    python scripts/validate_episode.py <episode_id>
    python scripts/validate_episode.py episodes/<episode_id>   # also accepted

Pipeline this validates (see CLAUDE.md):
    master_script.md -> script_manifest.json -> tts_manifest.json ->
    asset_inventory.json (B-DISCOVER) -> edit_plan.json (B-EDIT) -> renderer

There is no fact_pack.json/producer_outline.json/final_script.json in this pipeline
-- those belonged to the retired pre-script-first architecture (see legacy/).

Checks (all topic-independent -- nothing here knows about any specific episode):
  - schema shape for all four required files (if the `jsonschema` package is
    installed; skipped with a note otherwise -- it is not a declared project
    dependency)
  - script_manifest.json: no duplicate block_id
  - tts_manifest.json: no duplicate block_id, no block_id unknown to
    script_manifest.json; when status is "generated", EVERY script_manifest block
    must have exactly one measured entry (a partial set must not claim "generated")
  - the B-EDIT gate (block/runtime-centric): every script_manifest.json block has
    EXACTLY ONE block_coverage entry (missing/duplicate/unknown block_ids are all
    errors, never silently collapsed); target_visual_sec matches that block's
    MEASURED duration_sec from tts_manifest.json; planned_visual_sec equals
    sum(allocations[].planned_sec); coverage_ratio/coverage_status are
    mathematically consistent with the V0 thresholds (sufficient >= 0.90,
    partial >= 0.60, critical_gap < 0.60); allocations reference real asset_ids
    (and, for video, a real segment_id on that asset, with planned_sec not
    exceeding that segment's duration); relevance: exact requires the asset's
    exact_subject_match to be true. The gate itself additionally requires TTS to be
    fully "generated" and overall_effective_coverage (sum(min(planned, target)) /
    sum(target) across blocks) >= 0.90 -- see agents/agent_b_archive_visual_editor.md.
    (Informational -- False is a normal, correct state before B-DISCOVER has run.)
  - asset_inventory.json assets: exact_subject_match=true requires
    verification_method=visually_inspected; usable_segments only on
    visually_inspected video assets, with unique segment_ids episode-wide,
    end_sec > start_sec >= 0, and end_sec <= duration_sec when known
  - edit_plan.json, if it has clips: clip_ids unique; block_ids resolve to
    script_manifest.json; asset_ids resolve to asset_inventory.json; video clips
    reference a real segment_id whose usable_segment bounds contain
    [source_start_sec, source_end_sec], and (timeline_end - timeline_start) must
    equal (source_end - source_start) within tolerance -- no silent speed changes;
    non-video clips carry no segment_id/source range; still_treatment never
    appears on a video clip; the ordered clips provide CONTINUOUS coverage of
    [0, total measured narration duration] -- no gaps, no overlaps, beyond a small
    rounding tolerance (checked only once tts_manifest.json is fully "generated")

Exits nonzero only on hard ERRORs. WARNINGs are printed but don't fail the run --
they flag things worth a look, not necessarily defects.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
EPISODES_DIR = ROOT / "episodes"

FILES = ["script_manifest", "tts_manifest", "asset_inventory", "edit_plan"]

RATIO_TOLERANCE = 0.01
TIMELINE_TOLERANCE = 0.5   # seconds, for cumulative block-window / full-coverage checks
DURATION_MATCH_TOLERANCE = 0.15  # seconds, for timeline-duration == source-duration on video clips


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.info.append(msg)

    def ok(self):
        return not self.errors


def resolve_episode_dir(arg: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        return p
    candidate = EPISODES_DIR / arg
    if candidate.is_dir():
        return candidate
    raise SystemExit(f"Episode not found: {arg!r} (looked at {p} and {candidate})")


def load(path: Path):
    # Explicit UTF-8: script_manifest.json (Thai narration_text) and friends must not
    # depend on the platform's default text encoding -- Path.read_text() without
    # encoding= uses locale.getpreferredencoding(False), which on Windows is commonly
    # cp1252 and would silently corrupt multi-byte UTF-8 sequences on decode.
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schemas(ep_dir: Path, report: Report) -> None:
    try:
        import jsonschema
    except ImportError:
        report.note("jsonschema not installed -- skipping schema-shape validation (cross-file checks below still run)")
        return
    for name in FILES:
        schema_path = SCHEMAS_DIR / f"{name}.json"
        doc_path = ep_dir / f"{name}.json"
        if not doc_path.exists():
            report.error(f"{name}.json is missing")
            continue
        schema = load(schema_path)
        doc = load(doc_path)
        try:
            jsonschema.validate(doc, schema)
            report.note(f"schema valid: {name}.json")
        except jsonschema.ValidationError as e:
            report.error(f"{name}.json fails schema: {e.message} (at {list(e.absolute_path)})")


def validate_script_manifest(sm: dict, report: Report) -> dict:
    """Returns block_id -> block dict."""
    blocks = {}
    for b in sm.get("blocks", []):
        bid = b.get("block_id")
        if bid in blocks:
            report.error(f"script_manifest: duplicate block_id {bid!r}")
        blocks[bid] = b
        if not (b.get("narration_text") or "").strip():
            report.warn(f"script_manifest: block {bid!r} has empty narration_text")
    if not blocks:
        report.error("script_manifest: no blocks present")
    return blocks


def validate_tts_manifest(tts: dict, sm_blocks: dict, report: Report):
    """Returns (durations: {block_id: duration_sec}, complete: bool)."""
    entries = tts.get("blocks", [])
    seen = [e.get("block_id") for e in entries]
    dupes = {b for b in seen if seen.count(b) > 1}
    if dupes:
        report.error(f"tts_manifest: duplicate block_id entries: {sorted(dupes)}")

    extra = sorted({b for b in seen if b not in sm_blocks})
    if extra:
        report.error(f"tts_manifest: block_id(s) not present in script_manifest.json: {extra}")

    durations = {}
    for e in entries:
        bid = e.get("block_id")
        if bid in sm_blocks:
            durations[bid] = e.get("duration_sec")

    status = tts.get("status")
    missing = sorted(set(sm_blocks) - set(seen))
    complete = status == "generated" and not missing and not dupes and not extra

    if status == "generated" and missing:
        report.error(
            f"tts_manifest: status is 'generated' but {len(missing)} script_manifest block(s) have no "
            f"measured entry: {missing} -- a partial set must not claim 'generated'"
        )
    elif status == "pending" and missing:
        report.note(f"tts_manifest: {len(missing)}/{len(sm_blocks)} blocks not yet measured (status=pending)")

    report.note(f"tts_manifest: status={status!r}, {len(entries)} measured block(s), complete={complete}")
    return durations, complete


def _num(value):
    """Returns value if it's a real, usable number (int/float, not bool), else None.

    Every arithmetic/comparison site below reads a value out of a JSON file this
    validator does not control -- a malformed episode could contain
    duration_sec: null, duration_sec: "abc", or similar. jsonschema (if installed)
    catches most of this, but this validator must not crash with a Python
    TypeError/ValueError even when jsonschema isn't installed. Coercing through
    this helper turns a bad value into a reported ERROR instead of a stack trace.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _expected_coverage_status(ratio: float) -> str:
    if ratio >= 0.90:
        return "sufficient"
    if ratio >= 0.60:
        return "partial"
    return "critical_gap"


def validate_block_coverage_gate(ai: dict, sm_blocks: dict, tts_durations: dict, tts_complete: bool, report: Report) -> bool:
    """Block/runtime-centric B-EDIT gate (B-DISCOVER V0). See
    schemas/asset_inventory.json's block_coverage and
    agents/agent_b_archive_visual_editor.md for the full contract this enforces:
    target_visual_sec must equal the block's MEASURED tts_manifest duration, exactly
    one entry per block, honest 'exact' relevance, real asset locations/segments,
    and an episode-level overall_effective_coverage >= 0.90 on top of the per-block
    thresholds -- gated additionally on tts_manifest being fully 'generated'.
    """
    assets = {a.get("asset_id"): a for a in ai.get("assets", [])}
    entries = ai.get("block_coverage", [])

    seen_block_ids = [e.get("block_id") for e in entries]
    dupes = {b for b in seen_block_ids if seen_block_ids.count(b) > 1}
    if dupes:
        report.error(f"asset_inventory: duplicate block_coverage entries for block_id(s): {sorted(dupes)}")
    missing = [bid for bid in sm_blocks if bid not in seen_block_ids]
    extra = sorted({bid for bid in seen_block_ids if bid not in sm_blocks})
    if extra:
        report.error(f"asset_inventory: block_coverage references block_id(s) not in script_manifest.json: {extra}")

    segment_owners = {}
    for a in ai.get("assets", []):
        for seg in a.get("usable_segments", []) or []:
            sid = seg.get("segment_id")
            segment_owners.setdefault(sid, []).append(a.get("asset_id"))
    for sid, owners in segment_owners.items():
        if len(owners) > 1:
            report.error(f"asset_inventory: segment_id {sid!r} is not unique across assets (used by {owners})")

    critical_gap_blocks = set()
    total_target = 0.0
    total_effective = 0.0

    for e in entries:
        bid = e.get("block_id")
        target_raw, planned_raw, ratio_raw = e.get("target_visual_sec"), e.get("planned_visual_sec"), e.get("coverage_ratio")
        target, planned, ratio = _num(target_raw), _num(planned_raw), _num(ratio_raw)
        status = e.get("coverage_status")
        allocations = e.get("allocations", [])

        if target_raw is not None and target is None:
            report.error(f"asset_inventory: block_coverage[{bid!r}].target_visual_sec is not a number: {target_raw!r}")
        if planned_raw is not None and planned is None:
            report.error(f"asset_inventory: block_coverage[{bid!r}].planned_visual_sec is not a number: {planned_raw!r}")
        if ratio_raw is not None and ratio is None:
            report.error(f"asset_inventory: block_coverage[{bid!r}].coverage_ratio is not a number: {ratio_raw!r}")

        measured_raw = tts_durations.get(bid)
        measured = _num(measured_raw)
        if measured_raw is not None:
            if measured is None:
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}] cannot verify target_visual_sec -- tts_manifest's "
                    f"duration_sec for this block is not a number: {measured_raw!r}"
                )
            elif target is not None and target != measured:
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}].target_visual_sec={target} does not match "
                    f"tts_manifest's measured duration_sec={measured} for this block"
                )
        elif bid in sm_blocks:
            report.warn(
                f"asset_inventory: block_coverage[{bid!r}] has no matching measured duration in tts_manifest.json "
                f"yet -- target_visual_sec={target_raw!r} cannot be verified"
            )

        alloc_sum = 0.0
        alloc_sum_reliable = True
        for a in allocations:
            ps_raw = a.get("planned_sec")
            ps = _num(ps_raw)
            if ps is None:
                alloc_sum_reliable = False
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}] allocation for asset {a.get('asset_id')!r} has "
                    f"non-numeric planned_sec: {ps_raw!r}"
                )
            else:
                alloc_sum += ps
        if alloc_sum_reliable:
            if planned is None:
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}].planned_visual_sec={planned_raw!r} does not equal "
                    f"sum(allocations[].planned_sec)={alloc_sum}"
                )
            elif abs(planned - alloc_sum) > RATIO_TOLERANCE:
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}].planned_visual_sec={planned} does not equal "
                    f"sum(allocations[].planned_sec)={alloc_sum}"
                )

        if target is not None and target > 0 and planned is not None:
            expected_ratio = planned / target
            if ratio is None or abs(ratio - expected_ratio) > RATIO_TOLERANCE:
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}].coverage_ratio={ratio} does not match "
                    f"planned_visual_sec/target_visual_sec={expected_ratio:.3f}"
                )
        elif target == 0 and ratio != 1.0:
            report.warn(f"asset_inventory: block_coverage[{bid!r}] has target_visual_sec=0, expected coverage_ratio=1.0")

        if ratio is not None:
            expected_status = _expected_coverage_status(ratio)
            if status != expected_status:
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}] coverage_status={status!r} doesn't match "
                    f"coverage_ratio={ratio} (expected {expected_status!r} per V0 thresholds)"
                )

        if status == "critical_gap":
            critical_gap_blocks.add(bid)
        elif not allocations:
            report.error(f"asset_inventory: block_coverage[{bid!r}] has status={status!r} but no allocations")

        for alloc in allocations:
            aid = alloc.get("asset_id")
            asset = assets.get(aid)
            if asset is None:
                report.error(f"asset_inventory: block_coverage[{bid!r}] allocation references missing asset_id {aid!r}")
                continue

            seg_id = alloc.get("segment_id")
            alloc_planned = _num(alloc.get("planned_sec"))
            if asset.get("asset_type") == "video":
                if not seg_id:
                    report.error(
                        f"asset_inventory: block_coverage[{bid!r}] allocation of video asset {aid!r} has no segment_id"
                    )
                else:
                    seg = next((s for s in asset.get("usable_segments", []) or [] if s.get("segment_id") == seg_id), None)
                    if seg is None:
                        report.error(
                            f"asset_inventory: block_coverage[{bid!r}] allocation references segment_id {seg_id!r} "
                            f"not found on asset {aid!r}"
                        )
                    else:
                        seg_end, seg_start = _num(seg.get("end_sec")), _num(seg.get("start_sec"))
                        if seg_end is not None and seg_start is not None and alloc_planned is not None:
                            seg_dur = seg_end - seg_start
                            if alloc_planned > seg_dur + RATIO_TOLERANCE:
                                report.error(
                                    f"asset_inventory: block_coverage[{bid!r}] allocation planned_sec={alloc_planned} "
                                    f"exceeds segment {seg_id!r}'s own duration={seg_dur} on asset {aid!r}"
                                )
            elif seg_id:
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}] allocation references segment_id on non-video "
                    f"asset {aid!r} ({asset.get('asset_type')!r})"
                )

            if alloc.get("relevance") == "exact" and not asset.get("exact_subject_match"):
                report.error(
                    f"asset_inventory: block_coverage[{bid!r}] allocation of asset {aid!r} claims relevance=exact "
                    f"but the asset's exact_subject_match is not true"
                )

        if target is not None:
            total_target += target
            if planned is not None:
                total_effective += min(planned, target)

    overall_effective_coverage = (total_effective / total_target) if total_target > 0 else 1.0

    status_ok = ai.get("status") in ("gathered", "approved")
    gate_open = (
        status_ok
        and tts_complete
        and not missing
        and not dupes
        and not extra
        and not critical_gap_blocks
        and overall_effective_coverage >= 0.90
    )
    report.note(
        f"B-EDIT gate: asset_inventory.status={ai.get('status')!r}, tts_complete={tts_complete}, "
        f"{len(missing)}/{len(sm_blocks)} blocks uncovered, {len(critical_gap_blocks)} critical_gap block(s), "
        f"overall_effective_coverage={overall_effective_coverage:.3f} -> B-EDIT permitted = {gate_open}"
    )

    for asset in ai.get("assets", []):
        aid = asset.get("asset_id")
        if asset.get("exact_subject_match") and asset.get("verification_method") != "visually_inspected":
            report.error(
                f"asset_inventory: asset {aid!r} has exact_subject_match=true but "
                f"verification_method={asset.get('verification_method')!r} (requires visually_inspected)"
            )
        segments = asset.get("usable_segments") or []
        if segments and asset.get("verification_method") != "visually_inspected":
            report.error(f"asset_inventory: asset {aid!r} has usable_segments but was not visually_inspected")
        if segments and asset.get("asset_type") != "video":
            report.error(f"asset_inventory: asset {aid!r} has usable_segments but asset_type is not video")
        duration_raw = asset.get("duration_sec")
        duration = _num(duration_raw)
        if duration_raw is not None and duration is None:
            report.error(f"asset_inventory: asset {aid!r} has non-numeric duration_sec: {duration_raw!r}")
        for seg in segments:
            s0_raw, s1_raw = seg.get("start_sec"), seg.get("end_sec")
            s0, s1 = _num(s0_raw), _num(s1_raw)
            sid = seg.get("segment_id")
            if s0_raw is not None and s0 is None:
                report.error(f"asset_inventory: asset {aid!r} segment {sid!r} has non-numeric start_sec: {s0_raw!r}")
            if s1_raw is not None and s1 is None:
                report.error(f"asset_inventory: asset {aid!r} segment {sid!r} has non-numeric end_sec: {s1_raw!r}")
            if s0 is None or s1 is None or s1 <= s0:
                report.error(f"asset_inventory: asset {aid!r} segment {sid!r} has invalid range [{s0_raw}, {s1_raw}]")
                continue
            if s0 < 0:
                report.error(f"asset_inventory: asset {aid!r} segment {sid!r} has negative start_sec {s0}")
            if duration is not None and s1 > duration + RATIO_TOLERANCE:
                report.error(
                    f"asset_inventory: asset {aid!r} segment {sid!r} end_sec={s1} exceeds asset duration_sec={duration}"
                )

    return gate_open


def validate_edit_plan(ep: dict, sm_blocks: dict, ai: dict, tts_durations: dict, tts_complete: bool, report: Report) -> None:
    """Mathematical/reference integrity only for edit_plan.json -- never an editorial
    quality score. See schemas/edit_plan.json and agents/agent_b_archive_visual_editor.md.
    """
    clips = ep.get("clips", [])
    if not clips:
        return

    clip_ids = [c.get("clip_id") for c in clips]
    dupes = {c for c in clip_ids if clip_ids.count(c) > 1}
    if dupes:
        report.error(f"edit_plan: duplicate clip_id(s): {sorted(dupes)}")

    assets = {a.get("asset_id"): a for a in ai.get("assets", [])}

    # Cumulative per-block timeline window, walked in script_manifest.json's own
    # block order (never tts_manifest's array order). Only meaningful once every
    # block has been measured with genuinely numeric durations.
    block_window = {}
    total_narration_duration = None
    if tts_complete:
        cum = 0.0
        durations_reliable = True
        for bid in sm_blocks:
            dur = _num(tts_durations.get(bid))
            if dur is None:
                report.error(
                    f"edit_plan: cannot compute the narration timeline -- tts_manifest's duration_sec for "
                    f"block {bid!r} is not a number: {tts_durations.get(bid)!r}"
                )
                durations_reliable = False
                break
            block_window[bid] = (cum, cum + dur)
            cum += dur
        if durations_reliable:
            total_narration_duration = cum
        else:
            block_window = {}

    prev_end = None
    for i, c in enumerate(clips):
        cid = c.get("clip_id")
        bid = c.get("block_id")
        aid = c.get("asset_id")
        seg_id = c.get("segment_id")
        still = c.get("still_treatment")
        t0_raw, t1_raw = c.get("timeline_start_sec"), c.get("timeline_end_sec")
        s0_raw, s1_raw = c.get("source_start_sec"), c.get("source_end_sec")
        t0, t1 = _num(t0_raw), _num(t1_raw)
        s0, s1 = _num(s0_raw), _num(s1_raw)

        if bid not in sm_blocks:
            report.error(f"edit_plan: clip {cid!r} references missing block_id {bid!r}")
        asset = assets.get(aid)
        if asset is None:
            report.error(f"edit_plan: clip {cid!r} references missing asset_id {aid!r}")

        if t0_raw is not None and t0 is None:
            report.error(f"edit_plan: clip {cid!r} has non-numeric timeline_start_sec: {t0_raw!r}")
        if t1_raw is not None and t1 is None:
            report.error(f"edit_plan: clip {cid!r} has non-numeric timeline_end_sec: {t1_raw!r}")
        if t0 is None or t1 is None or t1 <= t0:
            report.error(f"edit_plan: clip {cid!r} has invalid timeline range [{t0_raw}, {t1_raw}]")
            # Without a usable [t0, t1], the ordering/gap/window checks below can't
            # run meaningfully for this clip -- skip them rather than crash or emit
            # a cascade of meaningless comparisons against None.
            continue

        if prev_end is not None and t0 < prev_end - TIMELINE_TOLERANCE:
            report.error(
                f"edit_plan: clip {cid!r} timeline_start_sec={t0} overlaps the previous clip's "
                f"timeline_end_sec={prev_end} -- clips must not overlap"
            )
        if i == 0 and total_narration_duration is not None and abs(t0 - 0.0) > TIMELINE_TOLERANCE:
            report.error(f"edit_plan: first clip {cid!r} starts at timeline_start_sec={t0}, expected ~0")
        if (
            prev_end is not None
            and total_narration_duration is not None
            and t0 > prev_end + TIMELINE_TOLERANCE
        ):
            report.error(
                f"edit_plan: gap in visual coverage between {prev_end} and {t0} (clip {cid!r}) -- the timeline "
                f"must be continuously covered"
            )
        prev_end = t1 if prev_end is None else max(prev_end, t1)

        if seg_id and still:
            report.error(f"edit_plan: clip {cid!r} has both segment_id and still_treatment -- a clip is one or the other")

        if asset is not None:
            if asset.get("asset_type") == "video":
                if still:
                    report.error(f"edit_plan: clip {cid!r} uses video asset {aid!r} but has still_treatment set")
                if not seg_id:
                    report.error(f"edit_plan: clip {cid!r} uses video asset {aid!r} but has no segment_id")
                else:
                    seg = next((s for s in asset.get("usable_segments", []) or [] if s.get("segment_id") == seg_id), None)
                    if seg is None:
                        report.error(
                            f"edit_plan: clip {cid!r} references segment_id {seg_id!r} not found on asset {aid!r}"
                        )
                    elif s0_raw is not None and s0 is None:
                        report.error(f"edit_plan: clip {cid!r} has non-numeric source_start_sec: {s0_raw!r}")
                    elif s1_raw is not None and s1 is None:
                        report.error(f"edit_plan: clip {cid!r} has non-numeric source_end_sec: {s1_raw!r}")
                    elif s0 is None or s1 is None:
                        report.error(f"edit_plan: clip {cid!r} is a video clip but missing source_start_sec/source_end_sec")
                    else:
                        if s1 <= s0:
                            report.error(f"edit_plan: clip {cid!r} has source_end_sec ({s1}) <= source_start_sec ({s0})")
                        seg_start, seg_end = _num(seg.get("start_sec")), _num(seg.get("end_sec"))
                        if seg_start is not None and seg_end is not None and (
                            s0 < seg_start - RATIO_TOLERANCE or s1 > seg_end + RATIO_TOLERANCE
                        ):
                            report.error(
                                f"edit_plan: clip {cid!r} source range [{s0}, {s1}] falls outside usable_segment "
                                f"{seg_id!r}'s range [{seg_start}, {seg_end}]"
                            )
                        if s1 > s0:
                            timeline_dur = t1 - t0
                            source_dur = s1 - s0
                            if abs(timeline_dur - source_dur) > DURATION_MATCH_TOLERANCE:
                                report.error(
                                    f"edit_plan: clip {cid!r} timeline duration ({timeline_dur:.2f}s) does not match "
                                    f"source duration ({source_dur:.2f}s) -- no playback-rate changes, looping, or "
                                    f"freeze-frame extension in V0"
                                )
            elif seg_id or s0_raw is not None or s1_raw is not None:
                report.error(
                    f"edit_plan: clip {cid!r} uses non-video asset {aid!r} but sets segment_id/source_start_sec/"
                    f"source_end_sec, which only apply to video"
                )

        if bid in block_window:
            b0, b1 = block_window[bid]
            if t0 < b0 - TIMELINE_TOLERANCE or t1 > b1 + TIMELINE_TOLERANCE:
                report.error(
                    f"edit_plan: clip {cid!r} timeline range [{t0}, {t1}] falls outside its block {bid!r}'s "
                    f"actual narration window [{b0:.2f}, {b1:.2f}] per tts_manifest.json"
                )

    if total_narration_duration is not None and prev_end is not None:
        if abs(prev_end - total_narration_duration) > TIMELINE_TOLERANCE:
            report.error(
                f"edit_plan: last clip ends at timeline_end_sec={prev_end}, but total measured narration "
                f"duration is {total_narration_duration:.2f} -- the timeline must cover it fully"
            )


def validate_production_readiness(ep: dict, gate_open: bool, report: Report) -> None:
    """Cheap sanity check that edit_plan isn't ahead of what the B-EDIT gate allows."""
    if ep.get("clips") and not gate_open:
        report.error(
            "edit_plan.json has clips but the B-EDIT gate is not open -- asset_inventory.status must be "
            "gathered/approved, tts_manifest.json must be fully 'generated', every block covered exactly "
            "once, no critical_gap blocks, and overall_effective_coverage >= 0.90 first"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode", help="episode_id (under episodes/) or a path to an episode folder")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress info notes, show only warnings/errors")
    args = parser.parse_args()

    ep_dir = resolve_episode_dir(args.episode)
    report = Report()

    validate_schemas(ep_dir, report)

    sm_path = ep_dir / "script_manifest.json"
    tts_path = ep_dir / "tts_manifest.json"
    ai_path = ep_dir / "asset_inventory.json"
    ep_path = ep_dir / "edit_plan.json"

    sm = load(sm_path) if sm_path.exists() else {}
    tts = load(tts_path) if tts_path.exists() else {}
    ai = load(ai_path) if ai_path.exists() else {}
    ep_doc = load(ep_path) if ep_path.exists() else {}

    sm_blocks = {}
    tts_durations = {}
    tts_complete = False
    gate_open = False

    if sm_path.exists():
        sm_blocks = validate_script_manifest(sm, report)
    if tts_path.exists() and sm_blocks:
        tts_durations, tts_complete = validate_tts_manifest(tts, sm_blocks, report)
    from tts_gemini_chunks import alignment_gate
    chunk_gate = alignment_gate(ep_dir)
    if chunk_gate:
        tts_complete = False
        report.note(f"{chunk_gate}: old block timings cannot authorize Gemini discovery/editing")
        if ai.get("status") in ("gathered", "approved") or ep_doc.get("status") in ("planned", "approved", "rendered"):
            report.error("Gemini chunk selection requires measured block alignment before visual production")
    if ai_path.exists() and sm_blocks:
        gate_open = validate_block_coverage_gate(ai, sm_blocks, tts_durations, tts_complete, report)
    if ep_path.exists() and sm_blocks and ai_path.exists():
        validate_edit_plan(ep_doc, sm_blocks, ai, tts_durations, tts_complete, report)
        validate_production_readiness(ep_doc, gate_open, report)

    if sm_path.exists():
        report.note(f"script_manifest: title={sm.get('title')!r}, {len(sm_blocks)} block(s), sha256={str(sm.get('script_sha256'))[:12]}...")
    if ai_path.exists():
        report.note(f"asset_inventory.status={ai.get('status')!r}, assets={len(ai.get('assets', []))}")
    if ep_path.exists():
        report.note(f"edit_plan.status={ep_doc.get('status')!r}, clips={len(ep_doc.get('clips', []))}")

    print(f"=== validate_episode: {ep_dir.name} ===\n")
    if not args.quiet:
        for m in report.info:
            print(f"  note   {m}")
    for m in report.warnings:
        print(f"  WARN   {m}")
    for m in report.errors:
        print(f"  ERROR  {m}")
    print(f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if not report.ok() else 0


if __name__ == "__main__":
    sys.exit(main())
