# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repository.

## What this is

A minimal, low-cost automated documentary content factory. Two LLM agents produce a
script and an asset list; a deterministic renderer (added later) turns those into
video. No servers, no database, no dashboard — episode state lives entirely in flat
JSON files on disk.

## Pipeline

```
episode_brief.json  --Agent A-->  producer_outline.json
producer_outline.json  --Agent B-->  asset_inventory.json
producer_outline.json + asset_inventory.json  --Agent A-->  final_script.json
final_script.json + asset_inventory.json  --Agent B-->  edit_plan.json
edit_plan.json  --Renderer (not yet built)-->  video
```

- **Agent A (Producer/Writer)** — `agents/agent_a_producer_writer.md`. Writes
  `producer_outline.json` and `final_script.json`.
- **Agent B (Archive/Visual Editor)** — `agents/agent_b_archive_visual_editor.md`.
  Writes `asset_inventory.json` and `edit_plan.json`.
- **Renderer** — FFmpeg/Remotion, not implemented yet. Will consume `edit_plan.json`
  only; it makes no creative decisions.

Every stage file has a `status` field (`pending` → in-progress → done/locked); a stage
is only safe to run once its inputs' status says so.

## Layout

- `episodes/<episode_id>/` — one folder per episode, holding the five JSON state
  files above. `episode_id` is `<channel_id>_<slugified-topic>`.
- `agents/` — role specs for Agent A and Agent B (prompts, not code, for now).
- `config/channels/<channel_id>.json` — per-channel defaults (`language`,
  `target_audience`) used when initializing an episode.
- `schemas/` — JSON Schema (draft-07) for every episode state file. Validate against
  these before an agent hands off to the next stage.
- `run_episode.py` — CLI. Currently one command: `init`.

## Conventions

- Keep episode state as plain JSON matching `schemas/*.json` — no new state stores.
- Don't add infrastructure (DB, Docker, cloud, dashboard, scraping) or new agents
  beyond A and B unless explicitly asked; this project is intentionally minimal.
- The renderer is deterministic and out of scope until it's explicitly requested —
  don't start implementing FFmpeg/Remotion code speculatively.

## CLI

```bash
python run_episode.py init --channel <channel_id> --topic "<topic>" --quirk "<quirk>"
```

Looks up `config/channels/<channel_id>.json` for `language`/`target_audience`,
creates `episodes/<channel_id>_<topic-slug>/`, and writes `episode_brief.json` plus
empty (`status: pending`) stubs for the other four state files.
