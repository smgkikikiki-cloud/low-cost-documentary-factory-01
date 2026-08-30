# low-cost-documentary-factory-01

A minimal, low-cost, **script-first** documentary production repository.

**Claude does not write the documentary.** An upstream OpenAI writer, outside this
repository, researches the topic and produces one complete, editorially locked Thai
master script. This repository turns that locked script into a finished video:

- **Deterministic ingestion** (`scripts/ingest_script.py`) — no LLM — turns
  `master_script.md` into `script_manifest.json`.
- **TTS** (`scripts/tts_render.py`, edge-tts | Google Chirp 3: HD | Gemini TTS) renders each block's narration and its
  *measured* duration becomes `tts_manifest.json`.
- **Claude — B-DISCOVER/B-EDIT** (`agents/agent_b_archive_visual_editor.md`) finds and
  verifies real archival visuals against the locked narration
  (`asset_inventory.json`, using `scripts/media_search.py`/`media_download.py`/
  `media_probe.py`), then assembles a concrete, deterministic timeline
  (`edit_plan.json`). Claude decides only what is shown and how — never what is said.
- **FFmpeg renderer** (`scripts/render_episode.py`) executes `edit_plan.json`
  exactly, with no remaining creative decisions.

Claude Code itself performs B-DISCOVER and B-EDIT by reading/writing the JSON files
directly — there is no separate orchestrator invoking a model. Everything else above
is real, deterministic Python.

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
episodes/<id>/          master_script.md, script_manifest.json, tts_manifest.json,
                         asset_inventory.json, edit_plan.json,
                         + audio/<tts_fingerprint>/ media/ render/ temp/
                         temp/ (gitignored -- see .gitignore)
agents/                 the one active Claude production role spec (B-DISCOVER/B-EDIT)
config/channels/        minimal per-channel identity (channel_id, output_language, tts,
                         optional tts_profiles). Never any credentials.
schemas/                JSON Schema for every active episode state file
scripts/ingest_script.py     deterministic master_script.md -> script_manifest.json
scripts/preflight.py         checks ffmpeg/ffprobe/yt-dlp/edge-tts/jsonschema on PATH
                             (+ optional google-cloud-texttospeech)
scripts/tts_render.py        narration renderer (edge-tts | google-chirp3 | gemini-tts), one file per block
scripts/tts_audition.py      Chirp 3: HD voice audition, writes only to temp/audition/
scripts/media_search.py      yt-dlp candidate metadata search (no download)
scripts/media_download.py    download one selected video or direct-URL asset
scripts/media_probe.py       deterministic ffprobe/ffmpeg helper (probe, contact sheets)
scripts/render_episode.py    the real FFmpeg renderer -> render/final.mp4
scripts/validate_episode.py  deterministic cross-file validator
scripts/episode_paths.py     the one shared episode-local directory layout
asset_library/          minimal flat-file convention for cross-episode asset reuse
run_episode.py          CLI
legacy/                 the retired pre-script-first architecture -- see legacy/README.md
```

## Setup

Required external tools on PATH: `ffmpeg`, `ffprobe`, `yt-dlp`.

```bash
pip install -r requirements.txt
python run_episode.py preflight
```

`preflight` reports READY/MISSING for each component with an install hint — it never
installs anything for you.

## Usage

```bash
python run_episode.py ingest --channel ForeignCarsTH \
    --topic "Jeep Wrangler YJ" \
    --script /path/to/master_script.md

python run_episode.py tts ForeignCarsTH_jeep-wrangler-yj            # channel's active tts config
python run_episode.py tts ForeignCarsTH_jeep-wrangler-yj --profile google-chirp3
python run_episode.py tts ForeignCarsTH_jeep-wrangler-yj --profile gemini-tts   # needs $GEMINI_API_KEY

# Claude performs B-DISCOVER (writes asset_inventory.json)
# Claude performs B-EDIT (writes edit_plan.json)

python run_episode.py validate ForeignCarsTH_jeep-wrangler-yj
python run_episode.py render ForeignCarsTH_jeep-wrangler-yj
python run_episode.py status ForeignCarsTH_jeep-wrangler-yj
```

`ingest` creates `episodes/ForeignCarsTH_jeep-wrangler-yj/` containing a verbatim copy
of the master script, its deterministically-parsed `script_manifest.json`, and empty
(`status: "pending"`) stubs for `tts_manifest.json`, `asset_inventory.json`, and
`edit_plan.json`. `status` reports the next incomplete stage (`SCRIPT INGESTED` /
`TTS REQUIRED` / `B-DISCOVER REQUIRED` / `B-EDIT REQUIRED` / `READY TO RENDER` /
`RENDERED`) by reading the episode's own JSON files.

To add a new channel, add `config/channels/<channel_id>.json` with `channel_id`,
`output_language`, and a `tts` block (`provider`, `voice`, `rate`, `pitch`,
`volume`).

## What moved to `legacy/`

An earlier version of this repository had Claude itself research and write narration
(`fact_pack.json` → `producer_outline.json` → `final_script.json`, an "Agent A" role).
That architecture, its schemas, and its five test episodes were retired in the
script-first migration and moved to `legacy/` for historical reference. See
`legacy/README.md`. Nothing in the active pipeline reads from or depends on anything
under `legacy/`.
