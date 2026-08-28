# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repository.

## What this is

A minimal, low-cost automated documentary content factory. Two LLM agents research,
plan, and script an episode and locate its visuals; a deterministic renderer (added
later) turns those into video. No servers, no database, no dashboard — episode state
lives entirely in flat JSON files on disk.

## Pipeline

```
episode_brief.json
    |  Agent A (A1 evidence collection + A2 adversarial verification)
    v
fact_pack.json
    |  Agent A (A3 story architecture)
    v
producer_outline.json
    |  Agent B (real asset discovery)
    v
asset_inventory.json
    |  Agent A (A4 localized final writing)
    v
final_script.json                    -- TTS later
    |  Agent B (edit planning)
    v
edit_plan.json                       -- deterministic renderer later
```

- **Agent A (Producer/Researcher/Writer)** — `agents/agent_a_producer_writer.md`. One
  agent, four internal modes (A1-A4). Writes `fact_pack.json` and
  `producer_outline.json`, then later `final_script.json`.
- **Agent B (Archive/Visual Editor)** — `agents/agent_b_archive_visual_editor.md`.
  Writes `asset_inventory.json` and `edit_plan.json`.
- **Renderer** — FFmpeg/Remotion, not implemented yet. Will consume `edit_plan.json`
  only; it makes no creative decisions.

Every stage file has a `status` field; a stage is only safe to run once its inputs'
status says so.

## Pipeline invariants

1. **Evidence before narrative.** Nothing gets written into `producer_outline.json`
   or `final_script.json` that isn't traceable to a `fact_pack.json` claim_id.
2. **The quirk is a lead, not a conclusion.** `episode_brief.json`'s `quirk` seeds
   research; it must never be auto-promoted into the thesis or into a claim without
   independent verification (see `fact_pack.json`'s `quirk_lead`).
3. **Fact pack before outline.** `fact_pack.json` must reach `status: "verified"`
   (A2's adversarial pass done) before `producer_outline.json` is built from it.
4. **Real asset inventory before final script.** `final_script.json` (A4) must not be
   written until Agent B has produced `asset_inventory.json` for the episode. The
   outline may *request* visuals (`visual_requests`); it must never assume they exist.
5. **Final narration language comes from channel config.** `final_script.json`'s
   `output_language` must match the channel's `output_language`, snapshotted onto
   `episode_brief.json` at init time. Localization happens inside A4 as natural
   spoken narration, not a literal translation pass.
6. **No separate Translation Agent.** Localization is a mode of Agent A, not a
   third agent.
7. **Every factual script claim traces back to the fact pack.** Each
   `final_script.json` block's `supporting_claim_ids` must resolve to
   `fact_pack.json` claims with `allowed_in_narration: true`. Only pure transitions/
   banter that assert no fact may have an empty list.
8. **Rendering is deterministic and comes much later.** Don't build FFmpeg/Remotion
   code speculatively.
9. **Two AI agents, not more.** Keep the architecture at Agent A + Agent B unless a
   demonstrated bottleneck later proves a third agent is necessary — research,
   fact-checking, translation, and QA are internal stages of Agent A, not separate
   agents.

## Layout

- `episodes/<episode_id>/` — one folder per episode, holding the six JSON state
  files above. `episode_id` is `<channel_id>_<slugified-topic>`.
- `agents/` — role specs for Agent A and Agent B (prompts, not code, for now).
- `config/channels/<channel_id>.json` — per-channel defaults (`research_language`,
  `working_language`, `output_language`, `narration_register`, `target_audience`)
  used when initializing an episode.
- `schemas/` — JSON Schema (draft-07) for every episode state file. Validate against
  these before an agent hands off to the next stage.
- `run_episode.py` — CLI. Currently one command: `init`.

## Language architecture

Research and audience language are separate concepts, both snapshotted onto
`episode_brief.json` at init time so an episode stays reproducible even if the
channel config later changes:

- `research_language` — what language(s) Agent A may research in (`"auto"` means any).
- `working_language` — the internal language `fact_pack.json` normalized claims are
  written in, for consistency across an episode researched in multiple languages.
- `output_language` — the language `final_script.json` narration MUST be written in.
- `narration_register` — style guidance for A4 (e.g. `"natural_spoken_thai"`).

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

Looks up `config/channels/<channel_id>.json`, creates
`episodes/<channel_id>_<topic-slug>/`, and writes `episode_brief.json` (with the
channel's language settings snapshotted in) plus empty (`status: pending`) stubs for
`fact_pack.json`, `producer_outline.json`, `asset_inventory.json`,
`final_script.json`, and `edit_plan.json`.
