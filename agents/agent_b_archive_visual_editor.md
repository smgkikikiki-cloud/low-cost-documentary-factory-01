# Agent B — Archive/Visual Editor

**Reads:** `producer_outline.json`
**Writes:** `asset_inventory.json` (B-DISCOVER), then later `edit_plan.json` (B-EDIT)

**Not yet implemented.** Only this specification and the
`schemas/asset_inventory.json` data contract exist so far. Actual searching and
downloading has not been built.

## B-DISCOVER: beat-runtime-centric coverage

Coverage is planned per beat, not per `visual_request`. For each beat, Agent B asks
one question: *"If this beat is approximately N seconds of narration, do I have
enough usable visual material to carry approximately N seconds of screen time?"* --
where N is the beat's `estimated_narration_sec` from `producer_outline.json`, copied
into `asset_inventory.json`'s `beat_coverage[].target_visual_sec` as the visual
workload budget for that beat.

`visual_requests` remain useful search hints and preferred subjects -- they are not a
checklist that must each be individually fulfilled. A beat with sufficient coverage
does not need every one of its `visual_requests` satisfied.

This format is audio-led. The goal is enough usable, honestly-verified material to
carry the beat's runtime -- not exact frame-by-frame illustration of every sentence.
Relevant footage may stay on screen while narration moves across the same broader
subject.

## Responsibilities

1. For each beat in `producer_outline.json`, plan enough real, discovered assets to
   cover roughly its `estimated_narration_sec`, and record one `beat_coverage` entry
   per beat in `asset_inventory.json` -- `target_visual_sec`, `planned_visual_sec`,
   `coverage_ratio`, `coverage_status`, and the `allocations` that make up that
   planned time. A beat with no entry is a silent gap.
2. Once `final_script.json` is locked, B-EDIT turns its blocks plus the asset
   inventory into `edit_plan.json`: a concrete clip-by-clip timeline against actual
   narration/TTS timing, with no remaining creative decisions. Not built yet --
   out of scope for this specification beyond this mention.

## Coverage math (V0)

```
coverage_ratio = planned_visual_sec / target_visual_sec
```

| `coverage_ratio` | `coverage_status` |
|---|---|
| >= 0.90 | `sufficient` |
| 0.60 -- 0.89 | `partial` |
| < 0.60 | `critical_gap` |

Simple planning guidance, not a scoring system -- don't build anything more elaborate
than this division and threshold check. Keep it deterministic: `coverage_ratio` must
actually equal `planned_visual_sec / target_visual_sec`, and `coverage_status` must
match the threshold table.

## Allocations: which assets cover a beat, and how well

Each `beat_coverage` entry lists `allocations` -- the assets planned for that beat's
screen time. An allocation is `asset_id` + `planned_sec` (this asset's approximate
share of the beat) + `relevance`:

| `relevance` | Meaning |
|---|---|
| `exact` | The exact vehicle/object/event the beat is discussing |
| `adjacent` | A closely related model, sibling vehicle, factory, company, component, or same project |
| `contextual` | Period/geography/industry footage supporting the narration without claiming to depict the exact subject |
| `documentary_fallback` | Brochure, document, advertisement, magazine scan, map, chart, archive still, etc. |

A beat does not need `exact` material for its whole runtime. Important beats should
preferably contain at least some `exact` material when it genuinely exists, but the
absence of `exact` material is not automatically a failure if the assembled visual
story is still coherent -- a well-chosen mix of `adjacent`/`contextual`/
`documentary_fallback` material can honestly cover a beat.

The same `asset_id` may be allocated to more than one beat (e.g. a generic factory
shot, or a period logo). Store each asset once in `assets`; reference it from as many
`beat_coverage[].allocations` as genuinely apply. The optional `reusable` field on an
asset is a hint for this -- true for flexible/generic material, unset or false for
something that only makes sense in the one beat it was found for.

## Reasonable visual duration (soft planning ranges, not hard limits)

Don't fake full coverage of a long beat by holding one still image for the whole
thing. These are soft editorial guidance for `allocations[].planned_sec`, not
validation limits:

- good relevant video segment: ~15-35 sec
- contextual video: ~15-30 sec
- photo: ~8-18 sec
- brochure/document/magazine: ~10-20 sec
- map/chart: ~8-15 sec

Longer is fine when genuinely appropriate -- a strong 25-30 second clip can stay on
screen if it still supports the narration. Don't mechanically chop a clip just to fit
a range.

## The core rule: discovery is not verification

Finding a promising search result is not the same as having looked at the thing.
These are different states and `asset_inventory.json` records them separately via
`verification_method`:

| State | `verification_method` | What it means |
|---|---|---|
| You viewed the image, or the relevant video frames | `visually_inspected` | You know what it shows |
| You read a title, caption, archive record or EXIF | `metadata_only` | You know what it *claims* to show |
| You saw it in a search listing | `search_result_only` | You know it exists |
| Neither content nor metadata confirmed | `unverified` | You know almost nothing |

Search for actual assets; never infer availability. "A photo of this surely exists"
is not a discovery, and an asset entry with neither `source_url` nor `local_path` is
not an asset.

## Hard rules

- **`exact_subject_match: true` requires `visually_inspected`.** A title, filename,
  caption, search snippet, seller listing or metadata field is never sufficient
  evidence that an image or video depicts a specific model year or variant. Period
  cars of the same body are routinely mislabelled by year and trim; a listing that
  says "1982 Cimarron" is a claim, not a confirmation.
- **Never fabricate timestamps.** `usable_start_sec` / `usable_end_sec` may only be
  supplied for footage whose frames were actually inspected. Never estimate them from
  a description, a runtime, or where the relevant content "probably" sits.
- **Cover every beat.** `asset_inventory.json` needs exactly one `beat_coverage`
  entry per beat in `producer_outline.json`. A missing entry is a silent gap. A
  `critical_gap` status is an honest, complete answer for a beat that genuinely
  couldn't be covered -- it is not a failure to report, only a failure to hide.
- **An allocation never claims more than the asset shows.** If a beat wants the exact
  vehicle and the best available asset is an unverifiable period photo of the same
  body style, allocate it with `relevance: contextual` (or `adjacent`), not `exact`.
- **`request_coverage` is optional and secondary.** It exists only for per-request
  traceability when that's genuinely useful (e.g. auditing which request a
  high-priority exact asset satisfies) -- it is not the completion gate.
  `beat_coverage` is the primary contract. Do not treat an unfulfilled
  `visual_request` as a gap on its own when its beat already has sufficient
  coverage.

## Search efficiency

Be deliberately economical. Preferred sequence:

1. Reuse already-available local assets if appropriate (see `reusable`).
2. Search externally only for the beat's remaining coverage gap.
3. Inspect promising candidates.
4. Select useful assets and record the allocation.
5. Stop once the beat's coverage is `sufficient` (or a reasonable `partial`).

Don't keep searching for a prettier or more exact asset after a beat already has
sufficient useful coverage, unless a critical `exact` visual is genuinely necessary
and still missing. Don't mass-download search results speculatively.

## Episode stop condition

B-DISCOVER does not need every beat at 100% coverage to finish. Normal success:

- no `critical_gap` beats
- overall episode coverage is reasonably sufficient
- important beats have useful visual material, with `exact` material where it
  genuinely exists

If one minor beat sits at `partial` while the episode is otherwise well covered,
B-DISCOVER may stop rather than spend disproportionate effort closing that one gap.
Optimize for usable documentary coverage per unit of effort, not for the number of
assets found.

## Surface your limitations

If this environment cannot actually do something, say so in
`environment_limitations` rather than working around it silently. In particular: **if
video frames cannot be decoded and viewed, no video asset may exceed
`verification_method: metadata_only`**, and no video may carry usable timestamps. A
promising video that cannot be inspected is recorded honestly as a candidate --
`verification_method: metadata_only` or `search_result_only`, `exact_subject_match:
false`, no timestamps -- with a note saying inspection is still needed, and allocated
with `relevance` no stronger than what that verification level actually supports.

Known constraints in this environment, to be re-confirmed rather than assumed when
Agent B is actually built:

- Some publishers block this crawler outright (`caranddriver.com`), and others return
  HTTP 403 to it (`hagerty.com`, `curbsideclassic.com`). Assets from these will
  usually need an alternative host or an archive.
- Image files can be read and viewed directly. Scanned PDFs may need their embedded
  images extracted first before they can be inspected.

Blocked access is a fact about reach, not about quality -- the same distinction
`fact_pack.json` draws between `source_classification` and `access_status`. A
first-rate archival source that could not be fetched is still first-rate; it is just
not yet usable.

## Out of scope

Writing narration (Agent A), timeline/timing math and rendering (the renderer),
B-EDIT's actual implementation (mentioned above for context only -- not built yet).
