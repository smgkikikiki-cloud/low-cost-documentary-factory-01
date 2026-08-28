# low-cost-documentary-factory-01

A minimal, low-cost automated documentary content factory.

- **Agent A — Producer/Writer**: turns an episode brief into an outline, then a script.
- **Agent B — Archive/Visual Editor**: sources archival visuals, then builds the edit plan.
- **Renderer**: deterministic FFmpeg/Remotion pass over the edit plan (not built yet).

Episode state is just JSON files on disk — see `CLAUDE.md` for the full pipeline and
`schemas/` for the shape of each file.

## Layout

```
episodes/               one folder per episode (created by the CLI)
agents/                 role specs for Agent A and Agent B
config/channels/        per-channel defaults (language, target audience)
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
`episode_brief.json` (filled in) plus `producer_outline.json`, `asset_inventory.json`,
`final_script.json`, and `edit_plan.json` (empty, `status: "pending"`), ready for
Agent A to pick up.

To add a new channel, add `config/channels/<channel_id>.json` with `language` and
`target_audience`.
