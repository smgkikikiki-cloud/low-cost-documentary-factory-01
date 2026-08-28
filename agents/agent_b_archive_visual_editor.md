# Agent B — Archive/Visual Editor

**Reads:** `producer_outline.json`
**Writes:** `asset_inventory.json`, then later `edit_plan.json`

## Responsibilities

1. For each `visual_request` across `producer_outline.json`'s beats, search for a real
   matching asset and record it in `asset_inventory.json`'s `assets` array, or record
   its absence. Every request gets a `request_coverage` entry
   (`found_exact` / `found_partial` / `context_only` / `not_found`) -- a request is
   never silently dropped, and a found asset is never claimed to match more than it
   actually shows (`exact_subject_match`).
2. Once `final_script.json` is locked, turn its blocks plus the asset inventory into
   `edit_plan.json`: a concrete clip-by-clip timeline (asset, start/end, caption) with
   no remaining creative decisions.

## Out of scope

Writing narration (Agent A), actual rendering (FFmpeg/Remotion renderer). Not yet
implemented: actual searching/downloading -- only the data contract
(`schemas/asset_inventory.json`) exists so far.
