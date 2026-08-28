# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repository.

## What this is

A minimal, low-cost, **script-first** documentary production repository. An upstream
OpenAI writer, outside this repository, researches a topic and produces one complete,
editorially locked Thai documentary script. This repository turns that locked script
into a finished video: deterministic ingestion, TTS timing measurement, Claude-driven
visual discovery and edit planning, and a deterministic FFmpeg render. No servers, no
database, no dashboard — episode state lives entirely in flat JSON files on disk.

**Read this before assuming Claude writes any narration in this repository — it
doesn't, anymore. See "Who does what" below.**

## Who does what

| Role | Where | Responsibility |
|---|---|---|
| **Upstream OpenAI writer** | Outside this repository | Research, sourcing, thesis, story selection, pacing, structure, final Thai narration. Input: a vehicle/topic name + hook. Output: one locked `master_script.md`. |
| **Deterministic ingestion** | `scripts/ingest_script.py` | Turns `master_script.md` into `script_manifest.json`. No LLM. |
| **TTS** | Not yet built | Renders each block's narration to audio; its measured duration becomes `tts_manifest.json`. |
| **Claude (B-DISCOVER / B-EDIT)** | `agents/agent_b_archive_visual_editor.md` | Finds and verifies real visual material (`asset_inventory.json`), then assembles it into a concrete timeline (`edit_plan.json`). Decides only what is shown and how, never what is said. |
| **FFmpeg renderer** | Not yet built | Executes `edit_plan.json` exactly. No creative decisions. |

Once `master_script.md` is ingested, its narration is **editorially locked**. Claude
must never rewrite it, summarize it, improve its Thai, change its thesis, reorder its
story, add facts, or remove facts — and must not fact-check it as a prerequisite to
production. Editorial responsibility belongs upstream; visual honesty (never showing
an image as something it doesn't depict) belongs to Claude.

There is **no active Agent A** in this repository. A prior architecture had Claude
itself research and write narration (`fact_pack.json` → `producer_outline.json` →
`final_script.json`); that pipeline, its agent spec, its schemas, and its five test
episodes were retired and moved to `legacy/` (see `legacy/README.md`). Nothing in the
active pipeline below reads or depends on anything under `legacy/`.

## Pipeline

```
master_script.md                      -- written upstream, supplied externally
    |  deterministic ingestion (scripts/ingest_script.py, no LLM)
    v
script_manifest.json                  -- locked narration, source_refs as hints
    |  TTS (not yet built)
    v
tts_manifest.json                     -- MEASURED per-block audio duration
    |  Claude -- B-DISCOVER
    v
asset_inventory.json                  -- real, verified visual material
    |  Claude -- B-EDIT
    v
edit_plan.json                        -- complete, deterministic visual timeline
    |  FFmpeg renderer (not yet built)
    v
final.mp4
```

One Claude production agent, two modes (not two agents) — see
`agents/agent_b_archive_visual_editor.md`.

## Pipeline invariants

1. **The locked script is the editorial source of truth.** Research determines the
   upstream script; the script determines what is spoken; Claude determines only
   what is shown and how it's assembled. `script_manifest.json`'s `narration_text`
   is never rewritten, reordered, translated, or fact-checked by Claude.
2. **Ingestion is deterministic and LLM-free.** `scripts/ingest_script.py` performs
   only mechanical structure extraction (H1 title, an unambiguous single-line
   italic deck, blank-line-separated paragraph blocks, trailing-citation-link
   stripping into `source_refs`). It never invents story beats, sections, or
   structure the script doesn't already have, and never touches narration prose
   beyond that.
3. **`master_script.md` is preserved verbatim.** Ingestion copies it byte-for-byte
   into the episode directory and records its SHA-256 in
   `script_manifest.json.script_sha256`, so any downstream artifact can be proven
   to trace back to that exact locked script.
4. **TTS timing is measured, not estimated.** `tts_manifest.json`'s `duration_sec`
   per block must come from probing the actually-rendered audio file (e.g.
   `scripts/media_probe.py`'s `probe()`), never a guess. `status: "generated"`
   means *every* `script_manifest.json` block has exactly one measured entry — a
   partial set must not claim that status.
5. **Real, block-level visual coverage before B-EDIT.** `edit_plan.json` must not
   be written until `asset_inventory.json`'s `status` is `gathered` or `approved`
   **and** `tts_manifest.json` is fully `generated` **and** every block in
   `script_manifest.json` has exactly one `block_coverage` entry with no
   `critical_gap` among them **and** episode-level `overall_effective_coverage`
   (`sum(min(planned_visual_sec, target_visual_sec)) / sum(target_visual_sec)`
   across blocks) is `>= 0.90` — a collection of barely-partial blocks must not
   open B-EDIT. Coverage is planned per block against that block's **measured**
   runtime (`block_coverage[].target_visual_sec` = the block's
   `tts_manifest.json` `duration_sec`), never a per-request checklist — see
   `agents/agent_b_archive_visual_editor.md`.
6. **Discovery is not verification.** In `asset_inventory.json`,
   `exact_subject_match: true` requires `verification_method: visually_inspected`,
   and a video's `usable_segments` may only be recorded for footage actually
   inspected. Titles, captions and search snippets establish what an asset
   *claims* to show, never what it shows.
7. **A usable segment is a permitted range, not an indivisible clip.** B-EDIT may
   select any subrange of a `usable_segments` entry (or several different
   subranges of the same segment across different clips), as long as each
   `[source_start_sec, source_end_sec]` stays inside that segment's own bounds.
8. **No playback-rate creativity in V0.** For a video clip in `edit_plan.json`,
   `timeline_end_sec - timeline_start_sec` must equal `source_end_sec -
   source_start_sec` within a small tolerance. No speed changes, no implicit
   looping, no freeze-frame extension.
9. **The edit plan must continuously cover the actual narration timeline.** Once
   `tts_manifest.json` is fully `generated`, `edit_plan.json`'s ordered clips must
   cover `[0, total measured narration duration]` with no gaps and no overlaps,
   beyond a small rounding tolerance. A silent visual gap is a defect.
10. **Rendering is deterministic and comes much later.** Don't build FFmpeg code
    speculatively beyond what `edit_plan.json` already fully specifies.
11. **One Claude production agent, two modes.** B-DISCOVER and B-EDIT are modes of
    the same role, not separate agents. Do not add a third agent, a translation
    agent, a fact-checking agent, or a scene-detection/CV service.
12. **`asset_type` has exactly one video type.** Contextuality is expressed via an
    allocation's `relevance: contextual`, never via a separate `contextual_video`
    media type.
13. **Source references are hints, never a fact-check gate.** `script_manifest.json`
    `source_refs` may help Claude locate archival material or understand context.
    Claude must not stop production to re-verify the upstream writer's claims —
    that responsibility is upstream's. Visual honesty is still Claude's: never
    present an asset as showing something it does not show.
14. **No infrastructure creep.** No database, no vector store, no embeddings, no
    scene-detection AI, no dashboard, no server, no Docker, no cloud orchestration,
    no motion-graphics/transition engine, no subtitle engine — this project is
    intentionally minimal. `asset_library/` is a flat-file convention, not a
    database.

These invariants are topic-independent by design — none of them may be relaxed or
overridden for a specific episode's subject matter. `agents/agent_b_archive_visual_editor.md`
has the full production detail; this list is the index.

## Layout

- `episodes/<episode_id>/` — one folder per episode: `master_script.md` (verbatim
  copy), `script_manifest.json`, `tts_manifest.json`, `asset_inventory.json`,
  `edit_plan.json`. `episode_id` is `<channel_id>_<slugified-topic>`. Empty until
  the first `ingest` run creates one.
- `agents/agent_b_archive_visual_editor.md` — the one active Claude production
  role spec (B-DISCOVER / B-EDIT modes).
- `config/channels/<channel_id>.json` — minimal per-channel identity
  (`channel_id`, `output_language`). Editorial defaults (research/working
  language, narration register, target audience, runtime policy, act structure)
  belonged to the retired pipeline and are not part of this repository's
  responsibility anymore — see `legacy/`.
- `schemas/` — JSON Schema (draft-07) for every active episode state file
  (`script_manifest.json`, `tts_manifest.json`, `asset_inventory.json`,
  `edit_plan.json`). Validate against these before handing off between stages.
- `run_episode.py` — CLI. One command: `ingest`.
- `scripts/ingest_script.py` — deterministic, LLM-free `master_script.md` →
  `script_manifest.json` converter.
- `scripts/media_probe.py` — deterministic ffprobe/ffmpeg helper: `probe()` for
  duration/dimensions/fps/codec (video or audio), `coarse_contact_sheet()` /
  `fine_contact_sheet()` for adaptive-interval frame sampling so Claude can
  honestly inspect a long video without watching every frame.
- `scripts/validate_episode.py` — deterministic validator for one episode: schema
  shape (if `jsonschema` is installed; skipped with a note otherwise) plus
  cross-file/reference checks no schema can express (block-reference integrity,
  the block-coverage gate and its `overall_effective_coverage` arithmetic,
  segment-bounds checks, and `edit_plan.json`'s continuous-coverage/
  duration-match checks). Topic-independent; no episode-specific logic.
- `asset_library/` — minimal flat-file convention (`index.json` + `media/`) for
  reusing visual assets cheaply across episodes. No database, no vector store.
- `legacy/` — the retired pre-script-first architecture (Agent A spec, its
  schemas, and the five test episodes produced under it), preserved for
  historical reference only. Not part of the active pipeline.

## CLI

```bash
python run_episode.py ingest --channel <channel_id> --topic "<topic>" --script <path/to/master_script.md>
```

Looks up `config/channels/<channel_id>.json`, creates
`episodes/<channel_id>_<topic-slug>/`, copies `master_script.md` in verbatim,
deterministically parses it into `script_manifest.json`, and writes empty
(`status: pending`) stubs for `tts_manifest.json`, `asset_inventory.json`, and
`edit_plan.json`. No quirk, no fact pack, no producer outline, no Agent A state —
those belonged to the retired architecture.
