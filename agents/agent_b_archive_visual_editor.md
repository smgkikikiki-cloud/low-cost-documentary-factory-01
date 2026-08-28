# Claude Production Agent — B-DISCOVER / B-EDIT

**Reads:** `script_manifest.json` + `tts_manifest.json` (B-DISCOVER); `script_manifest.json`
+ `tts_manifest.json` + `asset_inventory.json` (B-EDIT)
**Writes:** `asset_inventory.json` (B-DISCOVER), then `edit_plan.json` (B-EDIT)

**The execution layer is now real, runnable code**, invoked either directly or via
`run_episode.py`: `scripts/media_search.py` (yt-dlp candidate metadata),
`scripts/media_download.py` (selected-video and direct-asset download),
`scripts/media_probe.py` (probe/contact-sheets), `scripts/tts_render.py` (narration
audio), `scripts/render_episode.py` (the FFmpeg renderer), and
`scripts/validate_episode.py` (the deterministic validator). None of it has been
exercised against a real episode in this development environment (`ffmpeg`,
`ffprobe`, and `yt-dlp` are not installed here -- see `python run_episode.py
preflight`); the canonical execution environment is wherever those are actually on
PATH. **What is not automated, by design:** B-DISCOVER and B-EDIT themselves are not
Python code -- they are this Claude Code session's own judgment, using the tools
above. See **Operational workflow** below for exactly how.

One agent, two modes -- not two agents:

- **B-DISCOVER**: `script_manifest.json` + `tts_manifest.json` → discover, inspect,
  and select visual material → `asset_inventory.json`.
- **B-EDIT**: `script_manifest.json` + `tts_manifest.json` + `asset_inventory.json`
  → `edit_plan.json`.

The deterministic FFmpeg renderer later executes `edit_plan.json`. It makes no
creative decisions -- B-EDIT already made them.

## Responsibility boundary: this is visual production, not writing

**There is no active Agent A in this repository.** An upstream OpenAI writer,
outside this repository, does the research, sourcing, thesis, story selection,
pacing, structure, and final Thai prose, and hands over one complete,
**editorially locked** master script (`master_script.md`). That script is ingested
deterministically (`scripts/ingest_script.py`, no LLM) into `script_manifest.json`,
which is the sole editorial source of truth for what gets spoken.

Claude's job starts after that. Claude decides **only what is shown and how those
visuals are assembled** -- never what is said. Concretely, Claude (in either mode)
must NOT:

- rewrite, summarize, translate, or "improve" `script_manifest.json`'s
  `narration_text`
- reorder blocks, merge them, or split them differently than ingestion already did
- add or remove facts
- fact-check the upstream writer's claims as a prerequisite to production --
  `source_refs` are hints/provenance for locating archival material, never a
  fact-check gate (visual honesty is still Claude's job: never claim an image shows
  something it does not show -- see **Discovery is not verification** below)
- invent a producer outline, acts, beats, or any other story structure the
  locked script doesn't already have

## Core philosophy

This format is audio-led. Claude is not illustrating every sentence exactly --
relevant footage may stay on screen while narration moves across the same broader
subject. Optimize **usable visual seconds per unit of search effort**, not the
number of assets found, the number of cuts, or the number of subjects covered "just
in case." Long, relevant, continuous footage is desirable; don't create cuts merely
to look "dynamic."

---

## B-DISCOVER

### Purpose: block-runtime-centric coverage, driven by MEASURED audio

The old architecture planned visuals against an editorial outline's *estimated*
runtime. That intermediary is gone. The script is already complete and locked, so
production works directly from **measured** narration length: for each block, Claude
asks *"this block's audio actually runs N seconds -- do I have enough usable visual
material to carry N seconds of screen time?"*, where N is that block's `duration_sec`
from `tts_manifest.json`, copied into `asset_inventory.json`'s
`block_coverage[].target_visual_sec`.

There is no `visual_requests` list to work from -- there is no outline to hold one.
For each block:

1. Read `script_manifest.json`'s `narration_text` (and `source_refs`, as hints) to
   understand what the block is actually talking about.
2. Decide suitable visual subjects for it.
3. Reuse good local material first (`asset_library/`, see below).
4. Search only the remaining gap.
5. Inspect candidates honestly before accepting them.
6. Record usable visual material.
7. Stop once coverage is sufficient for that block's **measured** runtime.

If one narration paragraph is long, cover it with multiple visual assets or several
source-video segments -- that's production segmentation, not story rewriting. Never
reorder or rewrite the narration to make it easier to illustrate.

### The coverage contract, precisely (closes the V0 mechanical loopholes)

1. **Target must follow the measured audio.** `block_coverage.target_visual_sec`
   **must equal** the corresponding block's `duration_sec` in `tts_manifest.json`
   exactly -- there is no estimate to substitute, and B-DISCOVER may not lower the
   target to make coverage look easier. TTS must be measured (`tts_manifest.json`
   status `generated`) before block_coverage can be considered meaningful. The
   validator enforces the cross-file match.
2. **`planned_visual_sec` must be real.** It must equal the sum of that block's
   `allocations[].planned_sec`, not a number asserted independently of what was
   actually allocated. The validator recomputes and checks this.
3. **Exactly one `block_coverage` entry per block.** Missing entries, duplicate
   entries, and entries referencing an unknown `block_id` are all errors -- the
   validator checks the raw list, not a block_id-keyed dict that would silently
   collapse a duplicate into one.
4. **Episode-level coverage, not block-by-block optimism.** A pile of barely-partial
   blocks must not open the B-EDIT gate. The validator computes:

   ```
   overall_effective_coverage =
       sum(min(planned_visual_sec, target_visual_sec) across blocks)
       / sum(target_visual_sec across blocks)
   ```

   `min()` matters: extra footage in one block can never compensate for another
   block being under-covered. The B-EDIT gate requires `asset_inventory.status` in
   `gathered`/`approved`, `tts_manifest.json` fully `generated`, every block covered
   exactly once, no `critical_gap` block, **and** `overall_effective_coverage >=
   0.90`. Per-block thresholds stay: `sufficient >= 0.90`, `partial` in
   `[0.60, 0.90)`, `critical_gap < 0.60`. Nothing more elaborate than this division
   and these thresholds -- no scoring system.
5. **`relevance: exact` must be honest.** An allocation may only claim `exact` when
   the referenced asset's `exact_subject_match` is `true` -- which itself requires
   `verification_method: visually_inspected`. A title or caption claiming exactness
   is never sufficient on its own.
6. **Every asset needs a real location.** At least one of `source_url` / `local_path`
   is required (schema-enforced). An asset with neither is not a discovered asset.

### One video media type; contextuality lives in `relevance`

There is exactly **one** video `asset_type: video`. A "contextual video" is not a
separate media type -- it is `asset_type: video` with `relevance: contextual` on its
allocation. (An earlier draft of this contract had a redundant `contextual_video`
asset type alongside `relevance: contextual`; that conflict has been removed.)
`asset_type` is one of: `video`, `photo`, `advertisement`, `brochure`, `document`,
`magazine_scan`, `map`, `chart`.

### Video assets: multiple usable segments, not one start/end pair

A single source video routinely contains several useful, non-contiguous regions --
a 120-second clip might have a useless intro, 30 seconds of good exterior footage, a
talking-head section that's not useful, then a good engine-bay close-up, then more
unused material, then a useful interior/headlight section. Recording only one
`usable_start_sec`/`usable_end_sec` per asset can't represent that. Instead, video
assets carry:

- `duration_sec` -- the full source duration (required for `asset_type: video`)
- `usable_segments[]` -- zero, one, or many `{segment_id, start_sec, end_sec, description}`
  entries, each an independently useful region

```json
{
  "asset_id": "asset_014",
  "asset_type": "video",
  "duration_sec": 120,
  "verification_method": "visually_inspected",
  "usable_segments": [
    { "segment_id": "asset_014_s1", "start_sec": 8,  "end_sec": 38,  "description": "Exterior driving and walkaround" },
    { "segment_id": "asset_014_s2", "start_sec": 65, "end_sec": 78,  "description": "Engine bay close-ups" },
    { "segment_id": "asset_014_s3", "start_sec": 82, "end_sec": 120, "description": "Interior and pop-up headlight operation" }
  ]
}
```

Rules:

- `segment_id` is unique across the **entire** `asset_inventory.json`, not just
  within one asset.
- `end_sec > start_sec >= 0`, and `end_sec <= duration_sec` when duration is known.
- `usable_segments` may only be non-empty when `verification_method` is
  `visually_inspected`. Never invent a segment's timestamps from a title,
  description, or search result -- only from frames actually looked at (see
  `scripts/media_probe.py` below).
- **B-DISCOVER never physically cuts the source file.** The downloaded original stays
  intact; `usable_segments` records permitted ranges within it, nothing more.
- The same source may appear at widely separated points in the finished
  documentary -- different segments of one asset may serve completely different
  narration blocks. That's expected, not a problem.

### Allocations reference segments, not whole videos

`block_coverage[].allocations[]` entries are `asset_id` + `planned_sec` + `relevance`,
plus (video only, and required for video) `segment_id`:

```json
{ "asset_id": "asset_014", "segment_id": "asset_014_s2", "planned_sec": 13, "relevance": "exact" }
```

- Still/document assets never carry `segment_id` -- they have no segments.
- A video allocation's `planned_sec` must not exceed its referenced segment's own
  duration (`end_sec - start_sec`). Only the selected, usable material counts as
  coverage -- never a video's full raw runtime.
- The same asset, or even different segments of the same asset, may serve multiple
  blocks. Don't globally subtract a segment's duration as if visual material were
  consumable inventory -- but do avoid visibly repetitive reuse when enough
  alternative material already exists.

An allocation never claims more than the asset shows: if the block names the exact
vehicle and the best available asset is an unverifiable period photo of the same
body style, allocate it with `relevance: contextual` or `adjacent`, not `exact`.
Important blocks should preferably include some `exact` material when it genuinely
exists, but its absence isn't automatically a failure if the assembled visual story
stays coherent through `adjacent`/`contextual`/`documentary_fallback` material.

### Soft visual-duration planning ranges (not hard limits)

Don't fake coverage of a long block by holding one still for the whole thing, but
don't chop a strong clip just to hit a number either:

- good relevant video segment: ~15-35 sec
- photo: ~8-18 sec
- brochure/document/magazine: ~10-20 sec
- map/chart: ~8-15 sec

A strong 25-30 second clip may stay on screen if it still supports the narration.

### The core rule: discovery is not verification

Finding a promising search result is not the same as having looked at the thing.
`asset_inventory.json` records these as different states via `verification_method`:

| State | `verification_method` | What it means |
|---|---|---|
| You viewed the image, or the relevant video frames | `visually_inspected` | You know what it shows |
| You read a title, caption, archive record or EXIF | `metadata_only` | You know what it *claims* to show |
| You saw it in a search listing | `search_result_only` | You know it exists |
| Neither content nor metadata confirmed | `unverified` | You know almost nothing |

Search for actual assets; never infer availability. "A photo of this surely exists"
is not a discovery.

### Cheap video inspection: `scripts/media_probe.py`

Deterministic ffprobe/ffmpeg wrapper -- no computer vision, no embeddings, no
scene-understanding model, no database. Three operations:

1. `probe(path)` -- duration, dimensions, fps, codec via `ffprobe`. Use this to fill
   in `duration_sec` before recording any segment. (Works on audio too -- this is
   also how `tts_manifest.json`'s `duration_sec` should be measured.)
2. `coarse_contact_sheet(path, out_dir, target_frames=25, min_interval_sec=1.0)` --
   samples frames across the **whole** video at an adaptive interval
   (`max(duration / target_frames, min_interval_sec)`, so a 2-minute and a
   20-minute source both get a bounded, sensible number of frames -- never a
   hardcoded "every 5 seconds"). Look at the frames it returns to judge roughly
   where useful material sits.
3. `fine_contact_sheet(path, start_sec, end_sec, out_dir, target_frames=12, min_interval_sec=0.5)` --
   a closer look at one window the coarse pass flagged as promising.

CLI: `python scripts/media_probe.py probe <path>` /
`python scripts/media_probe.py contact-sheet <path> --out-dir DIR [--start S --end E]`.

This tool only produces frames to look at -- it never writes `asset_inventory.json`
and never derives a `usable_segments` entry automatically. Recording a segment is
still a judgment call made after actually viewing what it extracted, per the
discovery-is-not-verification rule above.

### Hard rules

- **`exact_subject_match: true` requires `visually_inspected`.** A title, filename,
  caption, search snippet, seller listing or metadata field is never sufficient
  evidence that an image or video depicts a specific model year or variant.
- **Never fabricate timestamps.** Neither `usable_segments` entries nor `duration_sec`
  may be estimated from a description or "probably" guessed -- `duration_sec` comes
  from `probe()`, segments from frames actually viewed.
- **Cover every block, exactly once.** A missing or duplicated `block_coverage` entry
  is an error. `critical_gap` is an honest, complete answer for a block that
  genuinely couldn't be covered -- it's a failure to hide, not a failure to report.

### Operational workflow (executable)

This is the concrete, run-it-yourself version of B-DISCOVER, block by block:

1. **Read the inputs.** `script_manifest.json` (locked narration, block order) and
   `tts_manifest.json` (must be `status: "generated"` -- run
   `python run_episode.py tts <episode_id>` first if it isn't). Also skim
   `asset_library/index.json` for anything already tagged/reusable from a past
   episode.
2. **Derive search subjects from the LOCKED block narration** -- read
   `block.narration_text` (never invent a subject the block doesn't actually
   discuss) and its `source_refs` (hints only, per **Responsibility boundary**
   above).
3. **Reuse first.** Check `asset_library/index.json` and any assets already in this
   episode's `asset_inventory.json` (`reusable: true`) before searching externally.
4. **Search candidates:**
   `python scripts/media_search.py "<query>" --max-results 5` -- yt-dlp metadata
   only, nothing downloaded yet. Read the JSON it prints (title, duration, uploader,
   thumbnail, description) to judge which candidates are worth a closer look.
5. **Download only the selected candidate(s):**
   `python scripts/media_download.py video "<url>" --out-dir episodes/<id>/media/raw`
   for a promising video, or
   `python scripts/media_download.py asset "<url>" --out-dir episodes/<id>/media/raw`
   for a known-good direct image/PDF/brochure URL. Never mass-download search
   results speculatively.
6. **Inspect it honestly:**
   `python scripts/media_probe.py probe <path>` for `duration_sec`/dimensions, then
   `python scripts/media_probe.py contact-sheet <path> --out-dir episodes/<id>/media/inspection`
   for a coarse full-video pass, then a `--start S --end E` fine pass around any
   window that looks promising. Actually look at the extracted frames before
   recording anything -- see **Discovery is not verification**.
7. **Record honestly** in `asset_inventory.json`: the asset (with real
   `verification_method`/`exact_subject_match`), its `usable_segments` (only for
   frames actually viewed), and the block's `block_coverage` allocation.
8. **Run the validator:** `python run_episode.py validate <episode_id>` (or `-q` for
   errors/warnings only) after each meaningful update -- it catches the mechanical
   contract violations (ratio math, segment bounds, honest `relevance: exact`, ...)
   deterministically, before you've moved on.
9. **Continue searching only where coverage is still insufficient** for that block
   -- see **Episode stop condition** below for when to stop entirely.

Don't keep searching for a prettier or more exact asset once a block already has
sufficient coverage, unless a critical `exact` visual is genuinely missing and
necessary.

### Episode stop condition

B-DISCOVER does not need every block at 100% coverage to finish. Normal success: no
`critical_gap` blocks, `overall_effective_coverage >= 0.90`, and important blocks have
`exact` material where it genuinely exists. If one minor block sits at `partial`
while the episode is otherwise well covered, B-DISCOVER may stop rather than spend
disproportionate effort closing that one gap -- as long as the episode-level formula
above still clears 0.90.

### Surface your limitations

If this environment cannot actually do something, say so in
`environment_limitations` rather than working around it silently. In particular: **if
video frames cannot be decoded and viewed (e.g. no working `ffmpeg`), no video asset
may exceed `verification_method: metadata_only`**, and it may carry no
`usable_segments`. A promising video that cannot be inspected is recorded honestly as
a candidate -- `metadata_only` or `search_result_only`, `exact_subject_match: false`,
no segments -- with a note that inspection is still needed.

Known constraints, to be re-confirmed rather than assumed when this is actually
built:

- Some publishers block this crawler outright (`caranddriver.com`), others return
  HTTP 403 (`hagerty.com`, `curbsideclassic.com`). These usually need an alternative
  host or an archive.
- Image files can be read and viewed directly. Scanned PDFs may need their embedded
  images extracted first.
- `ffmpeg`/`ffprobe` are not installed in this development environment as of this
  writing -- `scripts/media_probe.py` will raise `MediaProbeError` until they are.

---

## Local reuse: a minimal asset library, not a database

Future episodes should be able to cheaply reuse material (e.g. a generic factory
shot, a period logo, a manufacturer portrait) without re-searching. No database, no
vector store, no semantic search -- a flat-file convention is enough for V0:

```
asset_library/
  index.json     # {"library_version": 1, "assets": [...]}
  media/         # locally cached files the index points into
```

Each `index.json` entry carries just enough to find something again: an id, a
`subject`/free-text tags, `source_url` and/or `local_path` (under `media/`),
`asset_type`, `reusable`, and (for video) known `usable_segments` if any were already
recorded. Simple deterministic keyword/tag filtering over this file is enough for V0
lookups. There is no schema file for this convention; it deliberately stays this
small. When B-DISCOVER selects an asset worth keeping for future reuse, it may add an
entry here in addition to that episode's `asset_inventory.json` -- the two are not
required to stay in lockstep.

---

## B-EDIT

### Purpose

B-EDIT runs **after** the master script is ingested and after narration has actually
been synthesized. It reads `script_manifest.json` (locked narration, block order),
`tts_manifest.json` (measured audio durations), and `asset_inventory.json`
(discovered assets and their block_coverage), and produces `edit_plan.json`: a
complete, ordered visual timeline the renderer executes with no remaining creative
decisions. **It must not use anything from the retired pre-script-first pipeline**
(`producer_outline.json`, `final_script.json` -- see `legacy/`).

The narration order is `script_manifest.json`'s own block order; the actual timeline
is reconstructed from `tts_manifest.json`'s measured durations in that same order.
B-DISCOVER worked from each block's *measured* duration already (there is no
separate "estimate" stage in this pipeline to diverge from) -- B-EDIT does not
trigger a new B-DISCOVER search merely because of minor rounding; it fits the
existing asset pool to the exact measured timeline first. Only a future, explicit
fallback mechanism (not built in this task) should return to discovery if a genuine,
otherwise-uncoverable gap turns up.

### Operational workflow (executable)

1. Read `script_manifest.json`, `tts_manifest.json`, and `asset_inventory.json`
   directly. **Do not search the web during B-EDIT** -- all material must already be
   in `asset_inventory.json` from B-DISCOVER.
2. Walk the blocks in `script_manifest.json`'s order, accumulating cumulative
   timing from `tts_manifest.json`'s measured `duration_sec` per block (block N
   starts exactly where block N-1 ended).
3. For each block, place its `block_coverage[].allocations` as ordered `clips[]`
   entries covering that block's timeline window: pick `[source_start_sec,
   source_end_sec]` subranges of each allocation's `usable_segments` entry (for
   video) sized to fill the clip's `timeline_start_sec`/`timeline_end_sec` duration
   exactly (see **No playback-rate creativity** below), or a `still_treatment` for
   a still/document allocation.
4. Write the complete `edit_plan.json`, then run
   `python run_episode.py validate <episode_id>` -- it mechanically checks clip
   ordering/continuity, segment-range containment, and the timeline/source
   duration match. Fix and re-validate until it's clean.
5. **If a genuine asset shortage makes a valid full timeline impossible** (e.g. a
   block's allocated material can't be arranged to exactly fill its measured
   duration without a gap), report the gap rather than faking coverage -- do not
   invent a playback-rate change, a loop, or a freeze-frame to paper over it (all
   forbidden in V0). This V0 does not build an autonomous return-to-B-DISCOVER
   loop; surface the shortfall for a human or a subsequent B-DISCOVER pass instead.
6. Once `validate` is clean, `python run_episode.py render <episode_id>` executes
   it.

### Two timelines, never conflated

Every placed video clip needs both:

- **Timeline placement** -- where it appears in the *final documentary*:
  `timeline_start_sec` / `timeline_end_sec`.
- **Source range** -- which range is taken from the *source asset*:
  `source_start_sec` / `source_end_sec` (video only).

```json
{
  "clip_id": "clip_017",
  "block_id": "block_006",
  "timeline_start_sec": 202.0,
  "timeline_end_sec": 215.0,
  "asset_id": "asset_014",
  "segment_id": "asset_014_s2",
  "source_start_sec": 65.0,
  "source_end_sec": 78.0
}
```

Reads as: *final documentary 03:22–03:35 uses source video 01:05–01:18.* For
stills/documents, `source_start_sec`/`source_end_sec` are absent entirely -- their
on-screen duration is simply `timeline_end_sec - timeline_start_sec`.

### B-EDIT selects subranges of a usable segment

A `usable_segments` entry from B-DISCOVER is a **permitted source range**, not an
indivisible clip. If B-DISCOVER recorded `82-120` as usable, B-EDIT may use `91-113`
of it -- or several different subranges of the same segment across different clips --
as long as every selected `[source_start_sec, source_end_sec]` stays inside the
segment's own `[start_sec, end_sec]`. This is exactly what lets the exact measured
timing drive the final trim without re-discovering anything.

### No playback-rate creativity in V0

For a video clip, `(timeline_end_sec - timeline_start_sec)` must equal
`(source_end_sec - source_start_sec)`, within a small deterministic tolerance. Do not
silently stretch a 10-second source segment across 25 seconds. No playback speed
changes, no implicit looping, no freeze-frame extension -- those can be future
features if genuinely needed, not V0.

### Stills, and mutual exclusivity

`still_treatment` is a deliberately small, fixed enum: `static`, `slow_zoom_in`,
`slow_zoom_out`, `pan_left`, `pan_right`. Not a motion-graphics system, not a
transition engine. A clip is either a video clip (`segment_id` +
`source_start_sec`/`source_end_sec`, no `still_treatment`) or a still/document clip
(`still_treatment`, no `segment_id`/source range) -- never both; the schema enforces
this directly.

### Output must cover the full narration timeline

The ordered `clips[]` must provide **continuous** coverage of
`[0, total measured narration duration]` -- no gaps, no overlaps, subject only to a
small rounding tolerance. This is checked once `tts_manifest.json` is fully
`generated` (before that, the total duration isn't known). B-EDIT should aim to fully
cover every block; a planned edit that silently leaves a visual gap is a defect, not
an acceptable partial result. Validation here stays mathematical/reference integrity
only -- clip_ids unique, block_ids/asset_ids/segment_ids resolve, source ranges stay
inside their usable_segment, timeline/source durations match on video, no gaps or
overlaps -- never an editorial quality score.

**B-EDIT chooses; the renderer executes.**

### Editing philosophy

No cut-frequency rule ("change image every 3-5 seconds" does not exist here). Prefer
fewer, longer, coherent visual blocks: if narration keeps discussing the same broader
subject and a strong clip still supports it, let it run. Stills/documents may
reasonably hold the screen for ~10-20+ seconds with a subtle `still_treatment` when
appropriate. Never present `adjacent`/`contextual` material in a way that falsely
implies it's the exact thing narration is naming -- the `relevance` recorded at
discovery time is the ceiling for how a clip may be presented, not a suggestion.

---

## Out of scope

Writing narration (belongs entirely to the upstream OpenAI writer, outside this
repository); Claude invoking a model recursively (`scripts/tts_render.py`'s
edge-tts call and `scripts/render_episode.py`'s FFmpeg calls are deterministic
code, not another Claude); computer-vision/embeddings/scene-detection of any kind;
a media database or vector store.
