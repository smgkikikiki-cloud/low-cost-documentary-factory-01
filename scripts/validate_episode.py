#!/usr/bin/env python3
"""Deterministic, topic-independent validator for one episode.

Usage:
    python scripts/validate_episode.py <episode_id>
    python scripts/validate_episode.py episodes/<episode_id>   # also accepted

Checks (all topic-independent -- nothing here knows about any specific episode):
  - schema shape for all six files (if the `jsonschema` package is installed;
    skipped with a note otherwise -- it is not a declared project dependency)
  - fact_pack.json: no duplicate claim_ids, unresolved confidence implies
    allowed_in_narration=false, derived_comparison claims reference real
    source_claim_ids and are never more airable than their weakest input, and
    every derived `calculation` string actually evaluates
  - producer_outline.json: thesis_claim_ids / hook_claim_ids / every beat's
    supporting_claim_ids resolve to allowed claims; every unresolved_claim_ids
    entry resolves to a claim that is NOT allowed; visual_request request_id
    values are unique and beat_id-consistent; beat count against the 5-8
    story-density guidance (warning only -- not a hard rule)
  - estimated_runtime_sec against the channel's runtime_policy, if both exist
  - the A4 gate: whether asset_inventory.status + request_coverage currently
    permit Agent A's A4 stage (informational -- False is a normal, correct state
    before Agent B has run)
  - asset_inventory.json: exact_subject_match=true requires
    verification_method=visually_inspected; usable_start_sec/usable_end_sec only
    on visually_inspected assets; found_exact/found_partial/context_only carry
    at least one asset_id, not_found carries none

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


def validate_a4_gate(ai: dict, req_ids: list, report: Report) -> bool:
    covered = {c.get("request_id") for c in ai.get("request_coverage", [])}
    missing = [r for r in req_ids if r not in covered]
    status_ok = ai.get("status") in ("gathered", "approved")
    gate_open = status_ok and not missing
    report.note(
        f"A4 gate: asset_inventory.status={ai.get('status')!r}, "
        f"{len(missing)}/{len(req_ids)} visual_requests uncovered -> A4 permitted = {gate_open}"
    )
    for coverage in ai.get("request_coverage", []):
        status = coverage.get("coverage_status")
        asset_ids = coverage.get("asset_ids") or []
        rid = coverage.get("request_id")
        if status == "not_found" and asset_ids:
            report.error(f"asset_inventory: request {rid!r} is not_found but lists asset_ids {asset_ids}")
        if status in ("found_exact", "found_partial", "context_only") and not asset_ids:
            report.error(f"asset_inventory: request {rid!r} is {status!r} but lists no asset_ids")
    for asset in ai.get("assets", []):
        aid = asset.get("asset_id")
        if asset.get("exact_subject_match") and asset.get("verification_method") != "visually_inspected":
            report.error(
                f"asset_inventory: asset {aid!r} has exact_subject_match=true but "
                f"verification_method={asset.get('verification_method')!r} (requires visually_inspected)"
            )
        if asset.get("verification_method") != "visually_inspected" and (
            "usable_start_sec" in asset or "usable_end_sec" in asset
        ):
            report.error(f"asset_inventory: asset {aid!r} has usable timestamps but was not visually_inspected")

    return gate_open


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
            "is not open -- asset_inventory.status must be gathered/approved with full request_coverage first"
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
    brief_path = ep_dir / "episode_brief.json"

    fp = load(fp_path) if fp_path.exists() else {}
    po = load(po_path) if po_path.exists() else {}
    ai = load(ai_path) if ai_path.exists() else {}
    fs = load(fs_path) if fs_path.exists() else {}

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
            gate_open = validate_a4_gate(ai, req_ids, report)

    if fp_path.exists() and po_path.exists():
        validate_status_transitions(fp, po, fs, gate_open, report)

    if fs_path.exists():
        report.note(f"final_script.status={fs.get('status')!r}, blocks={len(fs.get('blocks', []))}")
    if ai_path.exists():
        report.note(f"asset_inventory.status={ai.get('status')!r}, assets={len(ai.get('assets', []))}")

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
