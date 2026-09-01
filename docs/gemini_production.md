# Gemini production chunks

This change implements the recovered TTS handoff on top of Claude commit
`4c0438ba0c79405af11bf8139f89f6bbbf9c9e2a`. It replaces the Gemini block backend;
Edge and Chirp remain available and the channel default remains Edge.

## Existing Windows episode

Use Python 3.10 or newer for google-genai. Run in
`C:\Users\hna\Documents\GitHub\low-cost-documentary-factory-01` after
syncing this change. Keep the existing `ForeignCarsTH_land-cruiser-70` episode.
Do not replace it with the separately restored 22-block copy from another machine.
`master_script.md` must match the SHA-256 already recorded at ingestion.

```bat
py -m pip install -r requirements.txt
py run_episode.py tts ForeignCarsTH_land-cruiser-70 --profile gemini-tts --dry-run
py run_episode.py tts ForeignCarsTH_land-cruiser-70 --profile gemini-tts
py run_episode.py status ForeignCarsTH_land-cruiser-70
```

The first TTS command is read-only and needs no key or network. The second uses
the existing `GEMINI_API_KEY` environment variable in that terminal and calls the
paid service. Keys are never stored in configuration, manifests or command-line
arguments. Do not paste a key into a chat, commit, or issue. The worker reads the
key from its inherited environment. A cloud checkout cannot read Windows files.

The SDK call remains `google.genai.Client().interactions.create(...)`, model
`gemini-3.1-flash-tts-preview`, voice `Charon`, `response_format={"type":"audio"}`
and `generation_config={"speech_config":[{"voice":"Charon"}]}`. The client is
given the environment key explicitly; no ADC or Cloud TTS authentication is used.
See [Google's speech-generation example](https://ai.google.dev/gemini-api/docs/speech-generation).

## Speech input and chunk sizes

The full approved automotive conversational direction is `APPROVED_PROMPT` in
`scripts/tts_gemini_chunks.py`. Every request also says it belongs to continuous
narration and must not restart or conclude at each paragraph. Prompt/version/config
changes produce a different audio scope; old block-backend Gemini WAVs are not reused.

Cleanup touches a derived input only: strip leading `Caption (Thesis):`, remove
curly emphasis quotes, replace em dash with comma/space, and collapse whitespace.
No paraphrasing, rate change, silence compression, or master/manifest text edits.

The default sizing estimate is **14 Unicode characters/second**, a conservative
planning heuristic, not a measured Thai rate. Target is 95 seconds. Neighboring
blocks are packed toward that target. A closer whole-block boundary can produce a
planned chunk between 100 and 120 seconds instead of isolated short performances;
120 is the absolute estimate ceiling. A short remainder is allowed. Estimates stay
in `estimated_duration_sec` and are never written to `tts_manifest.json`.

Oversized blocks may split at explicit sentence punctuation; Thai whitespace alone
is not a sentence boundary. If no safe boundary fits, the renderer fails before
sending that input. It never cuts a word merely to fit the budget. The planner is
deliberately conservative, not a Thai linguistic analyzer.

Returned PCM is wrapped as 24kHz mono 16-bit WAV, checked for complete samples,
and measured using ffprobe. Audio over 120 seconds is rejected before publication.
Only that chunk is divided at available block/sentence boundaries and regenerated.
If it is indivisible, that chunk remains failed; completed neighbors survive.
This bounds **accepted audio**, not the remote model's ability to initially return
an overlong response. There is no API output-duration knob assumed here.

`--timeout 120` is independently the wall-clock request budget. Each SDK call runs
in a child Python process. `subprocess.run(timeout=...)` terminates and reaps an
overdue worker; no executor shutdown waits for an abandoned network thread.
Killing the client cannot promise cancellation or reversal of server billing.

## Output and recovery

Paths relative to the episode:

```text
tts_chunks.json
tts_chunks/gemini-chunks_<config-hash>/<script-manifest-sha256>/manifest.json
audio/gemini-chunks_<config-hash>/<script-manifest-sha256>/chunk_<content-hash>.wav
audio/gemini-chunks_<config-hash>/<script-manifest-sha256>/chunk_<content-hash>.receipt.json
```

`tts_chunks.json` selects the active manifest. Each chunk stores ordered `block_ids`,
exact derived speech text, text offsets in the cleaned block, text hash, planning
estimate, status, and (only on success) measured duration/audio path/checksum.
Adaptive splits retain their ordered block mapping in the checkpoint.

Rerun the same command to resume. Reuse requires matching config/script/text/audio
hashes, a complete WAV and a fresh probe. A WAV without a receipt is not trusted.
A completed receipt/WAV pair can be salvaged after a crash before manifest update.
Temporary or corrupt files do not become completed chunks. Per-episode OS locking
prevents simultaneous chunk writers and is released on process exit/crash.

Old Edge/Chirp audio and `tts_manifest.json` remain untouched by chunk generation.
An explicit successful Edge/Chirp render reselects block mode by clearing only the
active `tts_chunks.json` pointer; all scoped Gemini manifests and audio remain.

## Alignment is the next implementation gate

Completed chunks produce `BLOCK ALIGNMENT REQUIRED`, **not** `B-DISCOVER REQUIRED`.
Status, validation, the renderer, and the production-agent instructions enforce
this even if old Edge timings exist. This commit does not claim to implement
automatic Thai forced alignment. No character-proportional times are fabricated.

The next stage must use actual speech to locate original block boundaries inside
each accepted chunk, preserve chunk-to-block ordering (including blocks split
across chunks), slice/assemble without dropping or duplicating samples, and probe
the final per-block files before publishing `tts_manifest.json`. The measured
chunk/audio hashes provide the identity that alignment must bind to. Its quality
must be tested on actual episode audio before measured coverage/B-EDIT is enabled.
Visual collection, source inspection and shared-cache reuse can run independently
while this gate is closed; see `docs/visual_production.md`.

Until that stage is implemented and verified, do not manually clear the pointer
to bypass alignment and do not use old provider timings for the new narration.

## Verification

```bat
py -m unittest discover -s tests -v
py -m compileall -q scripts run_episode.py
```

Tests mock the paid endpoint but write/probe real WAV files, test actual child
process timeout, multi-block grouping, oversize subdivision, failed-chunk resume,
orphan salvage, corrupt/truncated audio, source/config isolation, unchanged locked
files, no-write setup errors, and explicit Edge/Chirp rollback. They do not certify
voice quality or real Windows SDK execution. No real Gemini call is made in the
development checkout without the production episode/key.
