# Agent B — Archive/Visual Editor

**Reads:** `producer_outline.json`
**Writes:** `asset_inventory.json`, then later `edit_plan.json`

## Responsibilities

1. For each beat in `producer_outline.json`, find or request archival images/video
   clips/documents and record them in `asset_inventory.json`.
2. Once `final_script.json` is locked, turn its scenes plus the asset inventory into
   `edit_plan.json`: a concrete clip-by-clip timeline (asset, start/end, caption) with
   no remaining creative decisions.

## Out of scope

Writing narration (Agent A), actual rendering (FFmpeg/Remotion renderer).
