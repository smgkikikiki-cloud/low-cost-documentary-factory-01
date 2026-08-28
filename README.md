# low-cost-documentary-factory-01

A minimal, low-cost automated documentary content factory.

- **Agent A — Producer/Researcher/Writer**: collects and adversarially verifies
  evidence (`fact_pack.json`), architects the story (`producer_outline.json`), then
  writes the final localized narration (`final_script.json`) once real visuals exist.
- **Agent B — Archive/Visual Editor**: finds real archival visuals against the
  outline's requests (`asset_inventory.json`), then builds the edit plan.
- **Renderer**: deterministic FFmpeg/Remotion pass over the edit plan (not built yet).

Episode state is just JSON files on disk — see `CLAUDE.md` for the full pipeline and
invariants, and `schemas/` for the shape of each file.

## Pipeline

```
episode_brief -> Agent A (evidence) -> fact_pack
              -> Agent A (story architecture) -> producer_outline
              -> Agent B (real asset discovery) -> asset_inventory
              -> Agent A (final localized narration) -> final_script -> TTS later
              -> Agent B (edit planning) -> edit_plan -> deterministic renderer later
```

Key invariant: **`final_script.json` must not be written before `asset_inventory.json`
exists.** The outline may request useful visuals; it must never assume they exist.

## Layout

```
episodes/               one folder per episode (created by the CLI)
agents/                 role specs for Agent A and Agent B
config/channels/        per-channel defaults (research/working/output language, etc.)
schemas/                JSON Schema for every episode state file
run_episode.py          CLI
```

## Usage

```bash
python run_episode.py init --channel ForeignCarsTH \
    --topic "Cadillac Cimarron" \
    --quirk "Cadillac's infamous attempt to turn the GM J-car into a luxury compact"
```

This creates `episodes/ForeignCarsTH_cadillac-cimarron/` containing
`episode_brief.json` (filled in, with the channel's language settings snapshotted)
plus empty (`status: "pending"`) stubs for `fact_pack.json`, `producer_outline.json`,
`asset_inventory.json`, `final_script.json`, and `edit_plan.json`, ready for Agent A
to pick up.

To add a new channel, add `config/channels/<channel_id>.json` with
`research_language`, `working_language`, `output_language`, `narration_register`, and
`target_audience`.
