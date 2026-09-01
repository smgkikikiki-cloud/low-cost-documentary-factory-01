# Legacy area

Everything under this directory belonged to the pre-script-first V0 architecture,
retired in the "SCRIPT-FIRST V0 MIGRATION" (see `CLAUDE.md` at the repository root for
the current active pipeline). It is preserved for historical reference only and is
**not** part of the active production path -- nothing in the active
`scripts/validate_episode.py`, `run_episode.py`, or `agents/` reads or writes
anything under here.

Contents:

- `agents/agent_a_producer_writer.md` -- the retired Agent A (Producer/Researcher/
  Writer) role spec. There is no active Agent A in this repository anymore; an
  upstream OpenAI writer now produces the locked Thai master script externally.
- `schemas/episode_brief.json`, `fact_pack.json`, `producer_outline.json`,
  `final_script.json` -- the retired data contracts those stages used.
- `episodes/` -- the five test episodes produced under the old
  research → fact_pack → producer_outline → final_script pipeline (Cadillac
  Cimarron, Jeep Grand Cherokee 1990, Lancia Thema 8.32, Renault Avantime,
  Volvo 480), including their `script_preview*.md` A-FINAL evaluation drafts. Kept
  for reference; none of it is valid input to the new script-first pipeline.
- `PROJECT_INSPECTION.md` -- a point-in-time repository dump generated for an
  earlier external review, from before this migration. Superseded by `CLAUDE.md`.

`agents/agent_b_archive_visual_editor.md` (B-DISCOVER/B-EDIT) was **not** retired --
it was retooled in place at the repository root to read the new
`script_manifest.json`/`tts_manifest.json` contracts instead of
`producer_outline.json`. See it there, not here.
