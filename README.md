# low-cost-documentary-factory-01

A minimal, low-cost, **script-first** documentary production repository.

**Claude does not write the documentary.** An upstream OpenAI writer, outside this
repository, researches the topic and produces one complete, editorially locked Thai
master script. This repository turns that locked script into a finished video:

- **Deterministic ingestion** (`scripts/ingest_script.py`) — no LLM — turns
  `master_script.md` into `script_manifest.json`.
- **TTS** (not yet built) renders each block's narration and its *measured* duration
  becomes `tts_manifest.json`.
- **Claude — B-DISCOVER/B-EDIT** (`agents/agent_b_archive_visual_editor.md`) finds and
  verifies real archival visuals against the locked narration
  (`asset_inventory.json`), then assembles a concrete, deterministic timeline
  (`edit_plan.json`). Claude decides only what is shown and how — never what is said.
- **FFmpeg renderer** (not yet built) executes `edit_plan.json` exactly, with no
  remaining creative decisions.

Episode state is just JSON files on disk — see `CLAUDE.md` for the full pipeline and
invariants, and `schemas/` for the shape of each file.

## Pipeline

```
master_script.md -> ingest_script.py -> script_manifest.json
                  -> TTS -> tts_manifest.json (MEASURED, not estimated)
                  -> Claude B-DISCOVER -> asset_inventory.json
                  -> Claude B-EDIT -> edit_plan.json
                  -> FFmpeg renderer -> final.mp4
```

Key invariant: **`edit_plan.json` must not be written until `asset_inventory.json`
reaches `gathered`/`approved`, `tts_manifest.json` is fully `generated`, every
`script_manifest.json` block has exactly one `block_coverage` entry with no
`critical_gap`, and episode-level `overall_effective_coverage >= 0.90`.** Coverage is
planned per block against that block's *measured* narration duration, never a
per-request checklist.

## Layout

```
episodes/               one folder per episode (created by `ingest`)
agents/                 the one active Claude production role spec (B-DISCOVER/B-EDIT)
config/channels/        minimal per-channel identity (channel_id, output_language)
schemas/                JSON Schema for every active episode state file
scripts/ingest_script.py   deterministic master_script.md -> script_manifest.json
scripts/media_probe.py     deterministic ffprobe/ffmpeg helper
scripts/validate_episode.py  deterministic cross-file validator
asset_library/          minimal flat-file convention for cross-episode asset reuse
run_episode.py          CLI
legacy/                 the retired pre-script-first architecture -- see legacy/README.md
```

## Usage

```bash
python run_episode.py ingest --channel ForeignCarsTH \
    --topic "Jeep Wrangler YJ" \
    --script /path/to/master_script.md
```

This creates `episodes/ForeignCarsTH_jeep-wrangler-yj/` containing a verbatim copy of
the master script, its deterministically-parsed `script_manifest.json`, and empty
(`status: "pending"`) stubs for `tts_manifest.json`, `asset_inventory.json`, and
`edit_plan.json`, ready for TTS and then Claude's B-DISCOVER to pick up.

To add a new channel, add `config/channels/<channel_id>.json` with `channel_id` and
`output_language`.

## What moved to `legacy/`

An earlier version of this repository had Claude itself research and write narration
(`fact_pack.json` → `producer_outline.json` → `final_script.json`, an "Agent A" role).
That architecture, its schemas, and its five test episodes were retired in the
script-first migration and moved to `legacy/` for historical reference. See
`legacy/README.md`. Nothing in the active pipeline reads from or depends on anything
under `legacy/`.
