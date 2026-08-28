# Agent A — Producer/Writer

**Reads:** `episode_brief.json`
**Writes:** `producer_outline.json`, then later `final_script.json`

## Responsibilities

1. Turn an `episode_brief` (channel, language, topic, quirk, target audience) into a
   `producer_outline`: a thesis statement and an ordered list of narrative beats.
2. Once `asset_inventory.json` is populated by Agent B, write the narration for each
   beat as `final_script.json`, referencing the asset IDs that exist for that beat.

## Out of scope

Sourcing/selecting visuals (Agent B), timeline/timing math (the renderer).
