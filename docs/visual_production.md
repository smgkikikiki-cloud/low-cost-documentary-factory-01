# Reusable visual production (all topics/channels)

Claude remains the sole visual editor. These commands execute Claude's choices;
they do not invoke another model, rewrite narration, or decide what an image shows.
No Gemini key, billing change, or TTS generation is needed for collection.

## Two parts of the same B-DISCOVER mode

1. **Collection, available immediately after ingestion:** search, select a source,
   import/download, probe, extract evidence, actually view it, review, and reuse.
   `asset_inventory.json` stays `pending`; `block_coverage` stays empty.
2. **Measured coverage, after narration/alignment:** Claude supplies allocations;
   code obtains targets from the measured block audio, re-probes it, calculates
   coverage, and reports gaps. Only sufficient coverage opens B-EDIT.

An active Gemini chunk pointer still blocks coverage and B-EDIT until actual block
alignment exists. Old Edge/Chirp block timings cannot stand in for Gemini timing.
Collection does not need or change those files. `status` reports the sequential
production gate; `visual status` reports the independent collection track.

## Commands

Run from the repository root. Replace `EPISODE` with any ingested episode ID or
folder path. On Windows use `py`; on Linux/macOS use `python`/`python3`.

```bat
py run_episode.py visual status EPISODE
py run_episode.py visual search EPISODE --query "Claude's subject keywords" --local-only
py run_episode.py visual search EPISODE --query "Claude's search query" --max-results 5
py run_episode.py visual add EPISODE --type video --url "https://selected-public-source"
py run_episode.py visual add EPISODE --type photo --file "C:\path\to\selected-image.png"
py run_episode.py visual inspect EPISODE --asset ASSET_ID
py run_episode.py visual inspect EPISODE --asset ASSET_ID --start 12 --end 24
py run_episode.py visual review EPISODE --asset ASSET_ID --review review.json
py run_episode.py visual publish EPISODE --asset ASSET_ID
py run_episode.py visual reuse ANOTHER_EPISODE --asset ASSET_ID
py run_episode.py visual coverage EPISODE --plan allocations.json
```

`add` accepts video, photo, advertisement, brochure, document, magazine_scan, map,
or chart. Non-video material must be a decodable raster image/page (PNG/JPG/etc.);
PDF rasterization is not implemented. A PDF URL is not a ready-to-render image.
Use an existing scan/page image, or report that the source needs rasterization.

Search checks the flat shared index and returns metadata candidates; it does not
download any candidate or infer exactness. Use `--local-only` first. Searches are
cached under `media/search/`; `--refresh` explicitly repeats an external search.
One query returns at most 20 results. Keep early collection bounded: begin with
one small candidate set for a script subject, then inspect selected sources.
Before audio is ready, report material found and unfilled subjects, never a
coverage percentage or a claim that the whole documentary is visually covered.

`add --url` chooses ONE source. Repeating it resumes from the inventory/download
receipt; a source published in the shared library is copied without downloading
again. `add --file` imports a user-provided source without moving/modifying it.

## Review input is written by Claude, AFTER viewing the evidence

`inspect` prints episode-relative paths of actual frames (or the still itself).
Open those images with the agent's image viewer. Extracting files alone does not
establish `visually_inspected`. Use fine windows where source cuts/identity are
unclear; sampled frames are evidence for judgment, not automated scene detection.

Example shape only: substitute the actual ID, observed range and returned paths.
Do not copy these invented example timestamps into production data.

```json
{
  "subject": "What the viewed source actually shows",
  "description": "Claude's description of the observed content",
  "exact_subject_match": false,
  "visual_quality": "high",
  "license": "unknown",
  "reusable": true,
  "tags": ["descriptive", "keywords"],
  "viewed_evidence": ["media/inspection/RETURNED_SOURCE/coarse_000_t0000.00.jpg"],
  "usable_segments": [
    {"segment_id": "ASSET_ID_s1", "start_sec": 0, "end_sec": 2, "description": "Observed useful range"}
  ]
}
```

For stills omit `usable_segments` and use the returned still path as evidence.
`subject`, `description`, and a nonempty `viewed_evidence` are required. Optional
fields also include `notes`, `date_or_period`, and `source_title`. Never invent a
license from public accessibility. Source URLs and rights notes travel with reuse.

The tool checks the current source hash, evidence files/hashes, segment bounds,
and that each claimed segment has viewed evidence within it. These are mechanical
checks, not proof that Claude actually looked or that a particular vehicle/year
is correct; that responsibility still belongs to Claude.

## Cross-episode reuse

`publish` means **cache locally**, not publish to YouTube or an external service.
It requires a reviewed source explicitly marked `reusable: true`. The existing
`asset_library/index.json` convention is retained; managed entries add source
checksums and evidence. No database, embeddings, third agent or service is added.

`reuse` copies the source and inspected evidence to the destination episode, with
relative paths. Inspection/usable ranges transfer, but `exact_subject_match`
resets to false: exact relevance to the NEW narration must be judged again.
Files are independent copies, so moving the old episode cannot break the new one.
Shared media is gitignored; sharing the JSON index alone does not distribute the
actual media cache. `cache_usable: false` means a cache needs repair/re-import,
not that its unseen content is poor. Legacy index entries remain searchable but
need managed local import/inspection before automatic reuse.

## Coverage input, only after measured narration

Claude writes ONE allocation entry for every script block, including empty gaps:

```json
[
  {
    "block_id": "block_001",
    "allocations": [
      {"asset_id": "ASSET_ID", "segment_id": "ASSET_ID_s1", "planned_sec": 2, "relevance": "contextual"}
    ]
  },
  {"block_id": "block_002", "allocations": []}
]
```

No `target_visual_sec` is accepted in this input. The tool derives targets from
`tts_manifest.json` and checks them against the actual audio files. It validates
asset/segment references, never fills missing allocations, never pads a video
beyond its inspected segment, and uses the existing 90% aggregate/no-critical-gap
B-EDIT gate. Stills omit `segment_id`. B-EDIT still writes the final continuous
timeline; the renderer still does only what that timeline specifies.

If gaps remain, keep the reported allocations. To return to collection explicitly:

```bat
py run_episode.py visual reopen EPISODE
```

This snapshots the prior inventory/coverage under `media/coverage_history/`, clears
only coverage/timing selection, and preserves all assets/evidence. It refuses if
an edit plan has already been written. Fill the gaps, then resubmit allocations.
No existing coverage/edit plan is silently invalidated by collection commands.

## Integrity and failure behavior

- Source, evidence or locked-script changes cause a clear refusal, not stale reuse.
- After coverage, changing `tts_manifest.json` invalidates its timing fingerprint;
  validate/status/render refuse to pass that old coverage.
- JSON writes and copies are atomic. A single-writer OS lock prevents concurrent
  visual commands from losing inventory updates; a crashed process releases it.
- Download receipts survive a subsequent probe failure and prevent a repeat fetch.
- No TTS config, API keys, narration files or final timeline are changed by collection.
- Broken/blocked searches are reported; no bypass of publisher access restrictions.

## Verification

```bat
py -m pip install -r requirements.txt
py -m unittest discover -s tests -v
py run_episode.py preflight
```

The visual suite uses multiple topic/channel fixtures, real generated video/still
files, real ffprobe/frame extraction, measured WAVs, and a short 1080p FFmpeg render.
External search/download are mocked in tests; successful tests do not establish
that YouTube or a publisher is accessible from a particular machine. Test one
Claude-selected public source on the production machine after installation.

Humans handle installing dependencies and any unavailable network/file access.
Claude handles queries, source selection, viewing frames, review JSON, allocations
and edit planning. Do not hand the human an unfiltered candidate-review workload.
