# Agent B — Archive/Visual Editor

**Reads:** `producer_outline.json`
**Writes:** `asset_inventory.json`, then later `edit_plan.json`

**Not yet implemented.** Only this specification and the
`schemas/asset_inventory.json` data contract exist so far. Actual searching and
downloading has not been built.

## Responsibilities

1. For each `visual_request` across `producer_outline.json`'s beats, search for a real
   matching asset and record it in `asset_inventory.json`'s `assets` array, or record
   its absence. Every request gets a `request_coverage` entry.
2. Once `final_script.json` is locked, turn its blocks plus the asset inventory into
   `edit_plan.json`: a concrete clip-by-clip timeline with no remaining creative
   decisions.

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
- **Record `not_found` honestly.** A `not_found` with a real search trail is a
  successful outcome and lets Agent A rewrite around the gap. Inventing a plausible
  asset, or quietly dropping a request, is a failure that corrupts everything
  downstream. `not_found` must carry an empty `asset_ids` array.
- **Try alternatives before declaring `not_found` on a high-priority request.** Vary
  the search: the model name alone, the manufacturer plus year, the sibling models,
  the source type (auction listings, archives, brochure scans, period advertising,
  museum and library collections, enthusiast forums). Record what was tried in
  `search_attempts` so a `not_found` is auditable rather than merely asserted.
- **Cover every request.** `asset_inventory.json` needs exactly one
  `request_coverage` entry per `visual_request`. A missing entry is a silent gap, and
  it blocks Agent A's A4 stage by design.
- **A found asset never claims more than it shows.** If the request wanted a 1982 car
  and the asset is an unverifiable period photo of the same body style, that is
  `context_only` or `found_partial` with `exact_subject_match: false` — not
  `found_exact`.

## Surface your limitations

If this environment cannot actually do something, say so in
`environment_limitations` rather than working around it silently. In particular: **if
video frames cannot be decoded and viewed, no video asset may exceed
`verification_method: metadata_only`**, and no video may carry usable timestamps. A
promising video that cannot be inspected is recorded honestly as a candidate —
`verification_method: metadata_only` or `search_result_only`, `exact_subject_match:
false`, no timestamps — with a note saying inspection is still needed.

Known constraints in this environment, to be re-confirmed rather than assumed when
Agent B is actually built:

- Some publishers block this crawler outright (`caranddriver.com`), and others return
  HTTP 403 to it (`hagerty.com`, `curbsideclassic.com`). Assets from these will
  usually need an alternative host or an archive.
- Image files can be read and viewed directly. Scanned PDFs may need their embedded
  images extracted first before they can be inspected.

Blocked access is a fact about reach, not about quality — the same distinction
`fact_pack.json` draws between `source_classification` and `access_status`. A
first-rate archival source that could not be fetched is still first-rate; it is just
not yet usable.

## Out of scope

Writing narration (Agent A), timeline/timing math and rendering (the renderer).
