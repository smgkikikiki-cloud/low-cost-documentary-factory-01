#!/usr/bin/env python3
"""Deterministic, topic-independent validator for one episode.

Usage:
    python scripts/validate_episode.py <episode_id>
    python scripts/validate_episode.py episodes/<episode_id>   # also accepted

Checks (all topic-independent -- nothing here knows about any specific episode):
  - schema shape for all six required files, plus tts_manifest.json if present (if
    the `jsonschema` package is installed; skipped with a note otherwise -- it is not
    a declared project dependency)
  - fact_pack.json: no duplicate claim_ids, unresolved confidence implies
    allowed_in_narration=false, derived_comparison claims reference real
    source_claim_ids and are never more airable than their weakest input, and
    every derived `calculation` string actually evaluates
  - producer_outline.json: thesis_claim_ids / hook_claim_ids / every beat's
    supporting_claim_ids resolve to allowed claims; every unresolved_claim_ids
    entry resolves to a claim that is NOT allowed; visual_request request_id
    values are unique and beat_id-consistent; beat count against the 5-8 (or 8-12
    for act-structured outlines) story-density guidance (warning only)
  - estimated_runtime_sec against the channel's runtime_policy, if both exist
  - the A4 gate (beat/runtime-centric, B-DISCOVER V0): every producer_outline.json
    beat has EXACTLY ONE beat_coverage entry (missing/duplicate/unknown beat_ids are
    all errors, never silently collapsed); target_visual_sec matches the outline
    beat's estimated_narration_sec when present; planned_visual_sec equals
    sum(allocations[].planned_sec); coverage_ratio and coverage_status are
    mathematically consistent with the V0 thresholds (sufficient >= 0.90,
    partial >= 0.60, critical_gap < 0.60); allocations reference real asset_ids (and,
    for video, a real segment_id on that asset, with planned_sec not exceeding that
    segment's duration); relevance: exact requires the asset's exact_subject_match to
    be true. The gate itself additionally requires overall_effective_coverage
    (sum(min(planned, target)) / sum(target) across beats) >= 0.90 -- see
    agents/agent_a_producer_writer.md. (informational -- False is a normal, correct
    state before Agent B has run.) request_coverage, if present, is optional/
    secondary and only checked for its own found_*/not_found-vs-asset_ids
    consistency.
  - asset_inventory.json assets: exact_subject_match=true requires
    verification_method=visually_inspected; usable_segments only on
    visually_inspected video assets, with unique segment_ids episode-wide,
    end_sec > start_sec >= 0, and end_sec <= duration_sec when known
  - edit_plan.json, if it has clips: clip_ids unique; block_ids resolve to
    final_script.json; asset_ids resolve to asset_inventory.json; video clips
    reference a real segment_id whose usable_segment bounds contain
    [source_start_sec, source_end_sec]; non-video clips carry no segment_id/source
    range; timeline_end_sec > timeline_start_sec; clips are ordered by
    timeline_start_sec with no overlap; and, when tts_manifest.json gives measured
    per-block durations, each clip's timeline range stays inside its block's
    cumulative timing window (block N starts where block N-1 ended, in
    final_script.json's block order)

Exits nonzero only on hard ERRORs. WARNINGs are printed but don't fail the run --
they flag things worth a human/Agent-A look, not necessarily defects.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
EPISODES_DIR = ROOT / "episodes"
CHANNELS_DIR = ROOT / "config" / "channels"

FILES = ["episode_brief", "fact_pack", "producer_outline", "asset_inventory", "final_script", "edit_plan"]
OPTIONAL_FILES = ["tts_manifest"]


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
    return json.loads(path.read_text())


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

    for name in OPTIONAL_FILES:
        doc_path = ep_dir / f"{name}.json"
        if not doc_path.exists():
            continue
        schema = load(SCHEMAS_DIR / f"{name}.json")
        doc = load(doc_path)
        try:
            jsonschema.validate(doc, schema)
            report.note(f"schema valid: {name}.json")
        except jsonschema.ValidationError as e:
            report.error(f"{name}.json fails schema: {e.message} (at {list(e.absolute_path)})")


def validate_fact_pack(fp: dict, report: Report) -> dict:
    claims = {}
    for c in fp.get("claims", []):
        cid = c.get("claim_id")
        if cid in claims:
            report.error(f"fact_pack: duplicate claim_id {cid!r}")
        claims[cid] = c

    for cid, c in claims.items():
        if c.get("confidence") == "unresolved" and c.get("allowed_in_narration"):
            report.error(f"fact_pack: {cid} is confidence=unresolved but allowed_in_narration=true")

        for s in c.get("sources", []):
            if "wikipedia.org" in s.get("url", "") and s.get("source_classification") != "reference_source":
                report.warn(
                    f"fact_pack: {cid} grades a Wikipedia source as "
                    f"{s.get('source_classification')!r}, expected reference_source"
                )

        if c.get("claim_type") == "derived_comparison":
            src_ids = c.get("source_claim_ids") or []
            if not src_ids:
                report.error(f"fact_pack: {cid} is derived_comparison with no source_claim_ids")
            for sid in src_ids:
                if sid not in claims:
                    report.error(f"fact_pack: {cid} references missing source_claim_id {sid!r}")
                    continue
                if c.get("allowed_in_narration") and not claims[sid].get("allowed_in_narration"):
                    report.error(
                        f"fact_pack: {cid} is allowed_in_narration=true but input {sid!r} is not "
                        f"-- a derived claim can never be stronger than its weakest input"
                    )
            calc = c.get("calculation")
            if calc:
                try:
                    eval(calc, {"__builtins__": {}}, {})
                except Exception as e:
                    report.error(f"fact_pack: {cid}.calculation does not evaluate: {calc!r} ({e})")

    return claims


def validate_outline(po: dict, claims: dict, report: Report) -> list:
    allowed = {cid for cid, c in claims.items() if c.get("allowed_in_narration")}

    def check_ids(label, idlist, must_be_allowed):
        for cid in idlist or []:
            if cid not in claims:
                report.error(f"producer_outline: {label} references missing claim_id {cid!r}")
            elif must_be_allowed and cid not in allowed:
                report.error(f"producer_outline: {label} references {cid!r} which is not allowed_in_narration")
            elif not must_be_allowed and cid in allowed:
                report.warn(f"producer_outline: {label} lists {cid!r} as unresolved but it IS allowed_in_narration")

    check_ids("thesis_claim_ids", po.get("thesis_claim_ids"), True)
    check_ids("hook_claim_ids", po.get("hook_claim_ids"), True)

    beats = po.get("beats", [])
    uses_acts = any("act" in b for b in beats)
    if uses_acts:
        if not (8 <= len(beats) <= 12):
            report.warn(
                f"producer_outline: {len(beats)} beats, outside the 8-12 act-structured "
                f"story-density guidance (not a hard error -- may be justified by the evidence)"
            )
    elif not (5 <= len(beats) <= 8):
        report.warn(
            f"producer_outline: {len(beats)} beats, outside the 5-8 story-density guidance "
            f"(not a hard error -- may be justified by the evidence)"
        )

    req_ids = []
    for b in beats:
        bid = b.get("beat_id")
        check_ids(f"{bid}.supporting_claim_ids", b.get("supporting_claim_ids"), True)
        check_ids(f"{bid}.unresolved_claim_ids", b.get("unresolved_claim_ids"), False)
        for vr in b.get("visual_requests", []):
            req_ids.append(vr.get("request_id"))
            if vr.get("beat_id") != bid:
                report.error(
                    f"producer_outline: visual_request {vr.get('request_id')!r} has "
                    f"beat_id {vr.get('beat_id')!r}, expected {bid!r}"
                )
    if len(req_ids) != len(set(req_ids)):
        dupes = {r for r in req_ids if req_ids.count(r) > 1}
        report.error(f"producer_outline: duplicate visual_request request_id values: {dupes}")

    if uses_acts:
        validate_acts(beats, report)

    return req_ids


def validate_acts(beats: list, report: Report) -> None:
    """Checks for channels using the fixed 4-act structure (act present on beats).

    Topic-independent: only looks at act numbers and estimated_narration_sec, never
    at beat content.
    """
    for b in beats:
        if "act" not in b:
            report.error(f"producer_outline: {b.get('beat_id')!r} has no 'act' but other beats do -- all beats must carry act when the outline uses act structure")

    acts_seen = [b["act"] for b in beats if "act" in b]
    if set(acts_seen) != {1, 2, 3, 4}:
        report.error(f"producer_outline: acts present are {sorted(set(acts_seen))}, expected exactly {{1, 2, 3, 4}} (no empty act)")

    if acts_seen != sorted(acts_seen):
        report.error("producer_outline: beats are not in act order (acts must appear 1, 2, 3, 4 in sequence)")

    sec_by_act = {}
    missing_sec = False
    for b in beats:
        if "act" not in b:
            continue
        sec = b.get("estimated_narration_sec")
        if sec is None:
            missing_sec = True
        else:
            sec_by_act[b["act"]] = sec_by_act.get(b["act"], 0) + sec
    if missing_sec:
        report.warn("producer_outline: some act-structured beats have no estimated_narration_sec")
    elif sec_by_act:
        act3_sec = sec_by_act.get(3, 0)
        others = [sec_by_act.get(a, 0) for a in (1, 2, 4)]
        if any(act3_sec < o for o in others):
            report.warn(
                f"producer_outline: act 3 narration ({act3_sec}s) is not the longest act "
                f"(others: {dict((a, sec_by_act.get(a, 0)) for a in (1, 2, 4))}) -- act 3 is usually "
                f"the main body and should normally be the longest, though this isn't a hard rule"
            )


def validate_runtime(po: dict, episode_brief: dict, report: Report) -> None:
    channel_id = episode_brief.get("channel_id")
    channel_path = CHANNELS_DIR / f"{channel_id}.json"
    if not channel_path.exists():
        report.note(f"no channel config found at {channel_path}, skipping runtime-policy check")
        return
    channel = load(channel_path)
    rp = channel.get("runtime_policy")
    sec = po.get("estimated_runtime_sec")
    if not rp or sec is None:
        report.note("no runtime_policy on channel or no estimated_runtime_sec on outline, skipping runtime check")
        return
    minutes = sec / 60
    normal = rp.get("normal_range_minutes", [])
    longform = rp.get("longform_range_minutes", [])
    in_normal = len(normal) == 2 and normal[0] <= minutes <= normal[1]
    in_longform = len(longform) == 2 and longform[0] <= minutes <= longform[1]
    if in_normal:
        report.note(f"runtime {minutes:.1f}min is within normal_range_minutes {normal}")
    elif in_longform:
        if not po.get("runtime_rationale"):
            report.warn(
                f"runtime {minutes:.1f}min is in longform_range_minutes {longform} "
                f"but no runtime_rationale is given to justify it"
            )
        else:
            report.note(f"runtime {minutes:.1f}min is within longform_range_minutes {longform}, rationale present")
    else:
        report.warn(
            f"runtime {minutes:.1f}min falls outside both normal_range_minutes {normal} "
            f"and longform_range_minutes {longform}"
        )
    if sec == 480:
        report.warn("estimated_runtime_sec is exactly 480 -- verify this was actually estimated, not left at an old default")


def _expected_coverage_status(ratio: float) -> str:
    if ratio >= 0.90:
        return "sufficient"
    if ratio >= 0.60:
        return "partial"
    return "critical_gap"


def validate_a4_gate(ai: dict, beats: list, report: Report) -> bool:
    """Beat/runtime-centric A4 gate (B-DISCOVER V0). See schemas/asset_inventory.json's
    beat_coverage and agents/agent_b_archive_visual_editor.md for the full contract
    this enforces: target_visual_sec must follow the outline, planned_visual_sec must
    equal the sum of its allocations, exactly one entry per beat, honest 'exact'
    relevance, real asset locations/segments, and an episode-level
    overall_effective_coverage >= 0.90 on top of the per-beat thresholds.
    """
    assets = {a.get("asset_id"): a for a in ai.get("assets", [])}
    outline_beat_ids = [b.get("beat_id") for b in beats]
    outline_target = {b.get("beat_id"): b.get("estimated_narration_sec") for b in beats}
    entries = ai.get("beat_coverage", [])

    # 3. exactly one entry per beat -- check the raw list, never a beat_id-keyed dict
    # that would silently collapse a duplicate into "the last one wins".
    seen_beat_ids = [e.get("beat_id") for e in entries]
    dupes = {b for b in seen_beat_ids if seen_beat_ids.count(b) > 1}
    if dupes:
        report.error(f"asset_inventory: duplicate beat_coverage entries for beat_id(s): {sorted(dupes)}")
    missing = [bid for bid in outline_beat_ids if bid not in seen_beat_ids]
    extra = sorted({bid for bid in seen_beat_ids if bid not in outline_beat_ids})
    if extra:
        report.error(f"asset_inventory: beat_coverage references beat_id(s) not in producer_outline.json: {extra}")

    # Global segment_id uniqueness across the whole file.
    segment_owners = {}
    for a in ai.get("assets", []):
        for seg in a.get("usable_segments", []) or []:
            sid = seg.get("segment_id")
            segment_owners.setdefault(sid, []).append(a.get("asset_id"))
    for sid, owners in segment_owners.items():
        if len(owners) > 1:
            report.error(f"asset_inventory: segment_id {sid!r} is not unique across assets (used by {owners})")

    critical_gap_beats = set()
    total_target = 0.0
    total_effective = 0.0

    for e in entries:
        bid = e.get("beat_id")
        target = e.get("target_visual_sec")
        planned = e.get("planned_visual_sec")
        ratio = e.get("coverage_ratio")
        status = e.get("coverage_status")
        allocations = e.get("allocations", [])

        # 1. target must follow Agent A.
        outline_est = outline_target.get(bid)
        if outline_est is not None:
            if target != outline_est:
                report.error(
                    f"asset_inventory: beat_coverage[{bid!r}].target_visual_sec={target} does not match "
                    f"producer_outline beat.estimated_narration_sec={outline_est}"
                )
        elif bid in outline_target and not e.get("notes"):
            report.warn(
                f"asset_inventory: beat_coverage[{bid!r}] has no matching estimated_narration_sec in the "
                f"outline and no notes explaining the fallback target_visual_sec"
            )

        # 2. planned_visual_sec must equal sum(allocations.planned_sec).
        alloc_sum = sum(a.get("planned_sec") or 0 for a in allocations)
        if planned is None or abs(planned - alloc_sum) > 0.01:
            report.error(
                f"asset_inventory: beat_coverage[{bid!r}].planned_visual_sec={planned} does not equal "
                f"sum(allocations[].planned_sec)={alloc_sum}"
            )

        if target is not None and target > 0 and planned is not None:
            expected_ratio = planned / target
            if ratio is None or abs(ratio - expected_ratio) > 0.01:
                report.error(
                    f"asset_inventory: beat_coverage[{bid!r}].coverage_ratio={ratio} does not match "
                    f"planned_visual_sec/target_visual_sec={expected_ratio:.3f}"
                )
        elif target == 0 and ratio != 1.0:
            report.warn(f"asset_inventory: beat_coverage[{bid!r}] has target_visual_sec=0, expected coverage_ratio=1.0")

        if ratio is not None:
            expected_status = _expected_coverage_status(ratio)
            if status != expected_status:
                report.error(
                    f"asset_inventory: beat_coverage[{bid!r}] coverage_status={status!r} doesn't match "
                    f"coverage_ratio={ratio} (expected {expected_status!r} per V0 thresholds)"
                )

        if status == "critical_gap":
            critical_gap_beats.add(bid)
        elif not allocations:
            report.error(f"asset_inventory: beat_coverage[{bid!r}] has status={status!r} but no allocations")

        for alloc in allocations:
            aid = alloc.get("asset_id")
            asset = assets.get(aid)
            if asset is None:
                report.error(f"asset_inventory: beat_coverage[{bid!r}] allocation references missing asset_id {aid!r}")
                continue

            seg_id = alloc.get("segment_id")
            planned_sec = alloc.get("planned_sec") or 0
            if asset.get("asset_type") == "video":
                if not seg_id:
                    report.error(
                        f"asset_inventory: beat_coverage[{bid!r}] allocation of video asset {aid!r} has no segment_id"
                    )
                else:
                    seg = next((s for s in asset.get("usable_segments", []) or [] if s.get("segment_id") == seg_id), None)
                    if seg is None:
                        report.error(
                            f"asset_inventory: beat_coverage[{bid!r}] allocation references segment_id {seg_id!r} "
                            f"not found on asset {aid!r}"
                        )
                    else:
                        seg_dur = (seg.get("end_sec") or 0) - (seg.get("start_sec") or 0)
                        if planned_sec > seg_dur + 0.01:
                            report.error(
                                f"asset_inventory: beat_coverage[{bid!r}] allocation planned_sec={planned_sec} exceeds "
                                f"segment {seg_id!r}'s own duration={seg_dur} on asset {aid!r}"
                            )
            elif seg_id:
                report.error(
                    f"asset_inventory: beat_coverage[{bid!r}] allocation references segment_id on non-video "
                    f"asset {aid!r} ({asset.get('asset_type')!r})"
                )

            # 5. relevance: exact must be honest.
            if alloc.get("relevance") == "exact" and not asset.get("exact_subject_match"):
                report.error(
                    f"asset_inventory: beat_coverage[{bid!r}] allocation of asset {aid!r} claims relevance=exact "
                    f"but the asset's exact_subject_match is not true"
                )

        if target is not None:
            total_target += target
            if planned is not None:
                total_effective += min(planned, target)

    # 4. episode-level effective coverage -- min() so excess in one beat can't paper
    # over a shortfall in another.
    overall_effective_coverage = (total_effective / total_target) if total_target > 0 else 1.0

    status_ok = ai.get("status") in ("gathered", "approved")
    gate_open = (
        status_ok
        and not missing
        and not dupes
        and not extra
        and not critical_gap_beats
        and overall_effective_coverage >= 0.90
    )
    report.note(
        f"A4 gate: asset_inventory.status={ai.get('status')!r}, "
        f"{len(missing)}/{len(outline_beat_ids)} beats uncovered, {len(critical_gap_beats)} critical_gap beat(s), "
        f"overall_effective_coverage={overall_effective_coverage:.3f} -> A4 permitted = {gate_open}"
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
        duration = asset.get("duration_sec")
        for seg in segments:
            s0, s1 = seg.get("start_sec"), seg.get("end_sec")
            sid = seg.get("segment_id")
            if s0 is None or s1 is None or s1 <= s0:
                report.error(f"asset_inventory: asset {aid!r} segment {sid!r} has invalid range [{s0}, {s1}]")
            if s0 is not None and s0 < 0:
                report.error(f"asset_inventory: asset {aid!r} segment {sid!r} has negative start_sec {s0}")
            if duration is not None and s1 is not None and s1 > duration + 0.01:
                report.error(
                    f"asset_inventory: asset {aid!r} segment {sid!r} end_sec={s1} exceeds asset duration_sec={duration}"
                )

    for coverage in ai.get("request_coverage", []) or []:
        status = coverage.get("coverage_status")
        rids = coverage.get("asset_ids") or []
        rid = coverage.get("request_id")
        if status == "not_found" and rids:
            report.error(f"asset_inventory: request {rid!r} is not_found but lists asset_ids {rids}")
        if status in ("found_exact", "found_partial", "context_only") and not rids:
            report.error(f"asset_inventory: request {rid!r} is {status!r} but lists no asset_ids")

    return gate_open


def validate_edit_plan(ep: dict, fs: dict, ai: dict, tts: dict, report: Report) -> None:
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

    block_ids = {b.get("block_id") for b in fs.get("blocks", [])}
    assets = {a.get("asset_id"): a for a in ai.get("assets", [])}

    # Cumulative per-block timeline window from tts_manifest's MEASURED durations,
    # walked in final_script.json's own block order (never tts_manifest's array order).
    block_window = {}
    if tts and tts.get("blocks"):
        durations = {b.get("block_id"): b.get("duration_sec") for b in tts.get("blocks", [])}
        cum = 0.0
        for b in fs.get("blocks", []):
            bid = b.get("block_id")
            dur = durations.get(bid)
            if dur is None:
                continue
            block_window[bid] = (cum, cum + dur)
            cum += dur

    prev_end = None
    for c in clips:
        cid = c.get("clip_id")
        bid = c.get("block_id")
        aid = c.get("asset_id")
        seg_id = c.get("segment_id")
        t0, t1 = c.get("timeline_start_sec"), c.get("timeline_end_sec")
        s0, s1 = c.get("source_start_sec"), c.get("source_end_sec")

        if bid not in block_ids:
            report.error(f"edit_plan: clip {cid!r} references missing block_id {bid!r}")
        asset = assets.get(aid)
        if asset is None:
            report.error(f"edit_plan: clip {cid!r} references missing asset_id {aid!r}")

        if t0 is None or t1 is None or t1 <= t0:
            report.error(f"edit_plan: clip {cid!r} has invalid timeline range [{t0}, {t1}]")
        if prev_end is not None and t0 is not None and t0 < prev_end - 0.01:
            report.error(
                f"edit_plan: clip {cid!r} timeline_start_sec={t0} precedes the previous clip's "
                f"timeline_end_sec={prev_end} -- clips must be ordered with no overlap"
            )
        if t1 is not None:
            prev_end = t1 if prev_end is None else max(prev_end, t1)

        if asset is not None:
            if asset.get("asset_type") == "video":
                if not seg_id:
                    report.error(f"edit_plan: clip {cid!r} uses video asset {aid!r} but has no segment_id")
                else:
                    seg = next((s for s in asset.get("usable_segments", []) or [] if s.get("segment_id") == seg_id), None)
                    if seg is None:
                        report.error(
                            f"edit_plan: clip {cid!r} references segment_id {seg_id!r} not found on asset {aid!r}"
                        )
                    elif s0 is None or s1 is None:
                        report.error(f"edit_plan: clip {cid!r} is a video clip but missing source_start_sec/source_end_sec")
                    else:
                        if s1 <= s0:
                            report.error(f"edit_plan: clip {cid!r} has source_end_sec ({s1}) <= source_start_sec ({s0})")
                        seg_start, seg_end = seg.get("start_sec"), seg.get("end_sec")
                        if s0 < seg_start - 0.01 or s1 > seg_end + 0.01:
                            report.error(
                                f"edit_plan: clip {cid!r} source range [{s0}, {s1}] falls outside usable_segment "
                                f"{seg_id!r}'s range [{seg_start}, {seg_end}]"
                            )
            elif seg_id or s0 is not None or s1 is not None:
                report.error(
                    f"edit_plan: clip {cid!r} uses non-video asset {aid!r} but sets segment_id/source_start_sec/"
                    f"source_end_sec, which only apply to video"
                )

        if bid in block_window:
            b0, b1 = block_window[bid]
            if t0 is not None and t1 is not None and (t0 < b0 - 0.5 or t1 > b1 + 0.5):
                report.error(
                    f"edit_plan: clip {cid!r} timeline range [{t0}, {t1}] falls outside its block {bid!r}'s "
                    f"actual narration window [{b0:.2f}, {b1:.2f}] per tts_manifest.json"
                )


def validate_status_transitions(fp: dict, po: dict, fs: dict, gate_open: bool, report: Report) -> None:
    """Cheap sanity checks that a later stage isn't ahead of what an earlier stage's status allows."""
    if po.get("beats") and fp.get("status") != "verified":
        report.error(
            f"producer_outline has {len(po['beats'])} beat(s) but fact_pack.status={fp.get('status')!r}, "
            f"expected 'verified' before A-PRE builds an outline from it"
        )
    fs_has_content = fs.get("status") != "pending" or bool(fs.get("blocks"))
    if fs_has_content and not gate_open:
        report.error(
            "final_script.json has content (status != pending or non-empty blocks) but the A-FINAL gate "
            "is not open -- asset_inventory.status must be gathered/approved with every beat covered exactly "
            "once, no critical_gap beats, and overall_effective_coverage >= 0.90 first"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("episode", help="episode_id (under episodes/) or a path to an episode folder")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress info notes, show only warnings/errors")
    args = parser.parse_args()

    ep_dir = resolve_episode_dir(args.episode)
    report = Report()

    validate_schemas(ep_dir, report)

    fp_path = ep_dir / "fact_pack.json"
    po_path = ep_dir / "producer_outline.json"
    ai_path = ep_dir / "asset_inventory.json"
    fs_path = ep_dir / "final_script.json"
    ep_path = ep_dir / "edit_plan.json"
    tts_path = ep_dir / "tts_manifest.json"
    brief_path = ep_dir / "episode_brief.json"

    fp = load(fp_path) if fp_path.exists() else {}
    po = load(po_path) if po_path.exists() else {}
    ai = load(ai_path) if ai_path.exists() else {}
    fs = load(fs_path) if fs_path.exists() else {}
    ep_doc = load(ep_path) if ep_path.exists() else {}
    tts = load(tts_path) if tts_path.exists() else {}

    claims = {}
    req_ids = []
    gate_open = False
    if fp_path.exists():
        claims = validate_fact_pack(fp, report)
    if po_path.exists() and claims:
        req_ids = validate_outline(po, claims, report)
        if brief_path.exists():
            validate_runtime(po, load(brief_path), report)
        if ai_path.exists():
            gate_open = validate_a4_gate(ai, po.get("beats", []), report)

    if fp_path.exists() and po_path.exists():
        validate_status_transitions(fp, po, fs, gate_open, report)

    if ep_path.exists() and fs_path.exists() and ai_path.exists():
        validate_edit_plan(ep_doc, fs, ai, tts, report)

    if fs_path.exists():
        report.note(f"final_script.status={fs.get('status')!r}, blocks={len(fs.get('blocks', []))}")
    if ai_path.exists():
        report.note(f"asset_inventory.status={ai.get('status')!r}, assets={len(ai.get('assets', []))}")
    if ep_path.exists():
        report.note(f"edit_plan.status={ep_doc.get('status')!r}, clips={len(ep_doc.get('clips', []))}")
    if tts_path.exists():
        report.note(f"tts_manifest.status={tts.get('status')!r}, blocks={len(tts.get('blocks', []))}")
    else:
        report.note("no tts_manifest.json found -- skipping B-EDIT actual-timing checks")

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
