# Agent B — Archive/Visual Editor

**Reads:** `producer_outline.json` (B-DISCOVER); `final_script.json` + `tts_manifest.json`
+ `asset_inventory.json` (B-EDIT)
**Writes:** `asset_inventory.json` (B-DISCOVER), then `edit_plan.json` (B-EDIT)

**Not yet implemented.** Only this specification and the JSON Schema data contracts
(`schemas/asset_inventory.json`, `schemas/tts_manifest.json`, `schemas/edit_plan.json`)
exist so far. Actual searching, downloading, TTS rendering, and video trimming have
not been built. `scripts/media_probe.py` is real, runnable deterministic tooling, but
has not yet been exercised against a real video in this environment (no `ffmpeg`
installed here) -- see its own docstring.

One agent, two modes -- not two agents:

- **B-DISCOVER**: `producer_outline.json` → discover, inspect, and select visual
  material → `asset_inventory.json`.
- **B-EDIT**: `final_script.json` + actual TTS timing (`tts_manifest.json`) +
  `asset_inventory.json` → `edit_plan.json`.

The deterministic renderer later executes `edit_plan.json`. It makes no creative
decisions -- B-EDIT already made them.

## Core philosophy

This format is audio-led. Agent B is not illustrating every sentence exactly --
relevant footage may stay on screen while narration moves across the same broader
subject. Optimize **usable visual seconds per unit of search effort**, not the number
of assets found, the number of cuts, or the number of `visual_requests` individually
fulfilled. Long, relevant, continuous footage is desirable; don't create cuts merely
to look "dynamic."

---

## B-DISCOVER

### Purpose: beat-runtime-centric coverage

Coverage is planned per beat, not per `visual_request`. For each beat, Agent B asks
one question: *"If this beat is approximately N seconds of narration, do I have
enough usable visual material to carry approximately N seconds of screen time?"* --
where N is the beat's `estimated_narration_sec` from `producer_outline.json`, copied
into `asset_inventory.json`'s `beat_coverage[].target_visual_sec`.

`visual_requests` remain useful search hints and preferred subjects -- not a
checklist that must each be individually fulfilled. A beat with sufficient coverage
does not need every one of its `visual_requests` satisfied.

### The coverage contract, precisely (closes the V0 mechanical loopholes)

1. **Target must follow Agent A.** When the outline beat has an
   `estimated_narration_sec`, `beat_coverage.target_visual_sec` **must equal it
   exactly** -- Agent B may not lower the target to make coverage look easier. Only
   when the outline genuinely has no `estimated_narration_sec` for a beat may Agent B
   set its own reasonable value, and it must explain that fallback in `notes`. The
   validator enforces the cross-file match.
2. **`planned_visual_sec` must be real.** It must equal the sum of that beat's
   `allocations[].planned_sec`, not a number asserted independently of what was
   actually allocated. The validator recomputes and checks this.
3. **Exactly one `beat_coverage` entry per beat.** Missing entries, duplicate
   entries, and entries referencing an unknown `beat_id` are all errors -- the
   validator checks the raw list, not a beat_id-keyed dict that would silently
   collapse a duplicate into one.
4. **Episode-level coverage, not beat-by-beat optimism.** A pile of barely-partial
   beats must not open the A-FINAL gate. The validator computes:

   ```
   overall_effective_coverage =
       sum(min(planned_visual_sec, target_visual_sec) across beats)
       / sum(target_visual_sec across beats)
   ```

   `min()` matters: extra footage in one beat can never compensate for another beat
   being under-covered. The A-FINAL gate (see
   `agents/agent_a_producer_writer.md`) requires `asset_inventory.status` in
   `gathered`/`approved`, every beat covered exactly once, no `critical_gap` beat,
   **and** `overall_effective_coverage >= 0.90`. Per-beat thresholds stay:
   `sufficient >= 0.90`, `partial` in `[0.60, 0.90)`, `critical_gap < 0.60`. Nothing
   more elaborate than this division and these thresholds -- no scoring system.
5. **`relevance: exact` must be honest.** An allocation may only claim `exact` when
   the referenced asset's `exact_subject_match` is `true` -- which itself requires
   `verification_method: visually_inspected`. A title or caption claiming exactness
   is never sufficient on its own.
6. **Every asset needs a real location.** At least one of `source_url` / `local_path`
   is required (schema-enforced). An asset with neither is not a discovered asset.

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
  within one asset (so it can be referenced unambiguously later by
  `edit_plan.json`).
- `end_sec > start_sec >= 0`, and `end_sec <= duration_sec` when duration is known.
- `usable_segments` may only be non-empty when `verification_method` is
  `visually_inspected`. Never invent a segment's timestamps from a title,
  description, or search result -- only from frames actually looked at (see
  `scripts/media_probe.py` below).
- **B-DISCOVER never physically cuts the source file.** The downloaded original stays
  intact; `usable_segments` records permitted ranges within it, nothing more.

### Allocations reference segments, not whole videos

`beat_coverage[].allocations[]` entries are `asset_id` + `planned_sec` + `relevance`,
plus (video only, and required for video) `segment_id`:

```json
{ "asset_id": "asset_014", "segment_id": "asset_014_s2", "planned_sec": 13, "relevance": "exact" }
```

- Still/document assets never carry `segment_id` -- they have no segments.
- A video allocation's `planned_sec` must not exceed its referenced segment's own
  duration (`end_sec - start_sec`). Only the selected, usable material counts as
  coverage -- never a video's full raw runtime.
- The same asset, or even different segments of the same asset, may serve multiple
  beats (`asset_014_s1` → Act 1, `asset_014_s2` → Act 3, `asset_014_s3` → Act 4 is
  fine and desirable). Don't globally subtract a segment's duration as if visual
  material were consumable inventory -- but do avoid visibly repetitive reuse when
  enough alternative material already exists.

An allocation never claims more than the asset shows: if the beat wants the exact
vehicle and the best available asset is an unverifiable period photo of the same body
style, allocate it with `relevance: contextual` or `adjacent`, not `exact`. Important
beats should preferably include some `exact` material when it genuinely exists, but
its absence isn't automatically a failure if the assembled visual story stays
coherent through `adjacent`/`contextual`/`documentary_fallback` material.

### Soft visual-duration planning ranges (not hard limits)

Don't fake coverage of a long beat by holding one still for the whole thing, but
don't chop a strong clip just to hit a number either:

- good relevant video segment: ~15-35 sec
- contextual video: ~15-30 sec
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
   in `duration_sec` before recording any segment.
2. `coarse_contact_sheet(path, out_dir, target_frames=25, min_interval_sec=1.0)` --
   samples frames across the **whole** video at an adaptive interval
   (`max(duration / target_frames, min_interval_sec)`, so a 2-minute and a
   20-minute source both get a bounded, sensible number of frames -- never a
   hardcoded "every 5 seconds"). Look at the frames it returns to judge roughly
   where useful material sits.
3. `fine_contact_sheet(path, start_sec, end_sec, out_dir, target_frames=12, min_interval_sec=0.5)` --
   a closer look at one window the coarse pass flagged as promising (e.g. `55-85`
   after a coarse pass suggested something useful lives there).

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
- **Cover every beat, exactly once.** A missing or duplicated `beat_coverage` entry
  is an error. `critical_gap` is an honest, complete answer for a beat that genuinely
  couldn't be covered -- it's a failure to hide, not a failure to report.
- **`request_coverage` is optional and secondary.** Use it only when per-request
  traceability is genuinely useful. `beat_coverage` is the primary contract; an
  unfulfilled `visual_request` is not a gap on its own when its beat already has
  sufficient coverage.

### Search efficiency

1. Reuse already-available local material first (see **Local reuse** below, and each
   asset's `reusable` flag).
2. Search externally only for the beat's remaining coverage gap.
3. Inspect promising candidates (`media_probe.py`) before accepting them.
4. Download and select useful assets/segments; record the allocation.
5. Stop once the beat's coverage is `sufficient` (or a reasonable `partial`).

Don't keep searching for a prettier or more exact asset once a beat already has
sufficient coverage, unless a critical `exact` visual is genuinely missing and
necessary. Don't mass-download search results speculatively.

### Episode stop condition

B-DISCOVER does not need every beat at 100% coverage to finish. Normal success: no
`critical_gap` beats, `overall_effective_coverage >= 0.90`, and important beats have
`exact` material where it genuinely exists. If one minor beat sits at `partial` while
the episode is otherwise well covered, B-DISCOVER may stop rather than spend
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

Known constraints, to be re-confirmed rather than assumed when Agent B is actually
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
lookups -- e.g. "has anything tagged `volvo` or `renault-engine` already been
verified?" There is no schema file for this convention; it deliberately stays this
small. When B-DISCOVER selects an asset worth keeping for future reuse, it may add an
entry here in addition to that episode's `asset_inventory.json` -- the two are not
required to stay in lockstep, since not every episode-specific asset is worth adding
to the shared library.

---

## B-EDIT

### Purpose

B-EDIT runs **after** A-FINAL and after narration has actually been synthesized. It
turns `final_script.json`'s blocks, `asset_inventory.json`'s discovered assets, and
`tts_manifest.json`'s **measured** audio durations into `edit_plan.json`: a complete,
ordered visual timeline the renderer executes with no remaining creative decisions.

B-DISCOVER worked from Agent A's *estimated* `beat.estimated_narration_sec`. B-EDIT
works from the *actual* rendered narration length. These will usually differ
modestly -- **B-EDIT first tries to fit the existing asset pool to the actual
timing**; it does not trigger a new B-DISCOVER search merely because actual timing
differs somewhat from the estimate. Only a future, explicit fallback mechanism (not
built in this task) should return to discovery if actual timing opens a genuine,
otherwise-uncoverable gap.

### Actual narration timing: `tts_manifest.json`

TTS timing is **measured, not estimated**. `tts_manifest.json` (schema:
`schemas/tts_manifest.json`) is the smallest contract that lets B-EDIT know it: one
entry per rendered block, `{block_id, audio_path, duration_sec}`, where
`duration_sec` comes from probing the actual audio file (`media_probe.py`'s `probe()`
works on audio too), never copied from `final_script.json`'s
`estimated_duration_sec`.

B-EDIT computes each block's position on the final timeline deterministically, as a
running sum over `final_script.json`'s own block order (not `tts_manifest.json`'s
array order): block N's timeline window starts exactly where block N-1's ended.

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
segment's own `[start_sec, end_sec]`. This is exactly what lets actual narration
timing drive the final trim without re-discovering anything. The renderer performs
the real cut later; B-EDIT only decides the numbers.

### Output: no remaining creative decision

`edit_plan.json`'s `clips[]` (schema: `schemas/edit_plan.json`) is the complete
ordered timeline. Per clip: `clip_id`, `block_id`, `asset_id`, `timeline_start_sec`,
`timeline_end_sec`, plus (video) `segment_id` + `source_start_sec`/`source_end_sec`,
plus (stills) an optional `still_treatment` from a deliberately small enum (`static`,
`slow_zoom_in`, `slow_zoom_out`, `pan_left`, `pan_right`) -- not a motion-graphics
system. **B-EDIT chooses; the renderer executes.**

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

Writing narration (Agent A), the actual TTS rendering system, video rendering itself
(the deterministic renderer executes `edit_plan.json`), computer-vision/embeddings/
scene-detection of any kind, a media database or vector store.
