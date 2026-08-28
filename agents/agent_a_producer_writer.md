# Agent A — Producer / Researcher / Writer

One role, **two model invocations per episode**. Internal reasoning (collect →
verify → architect) happens within one session -- don't split it into separate paid
calls, and don't split this role into a Research/Fact-Checker/Translation/Calculation
Agent.

**A-PRE** (one session): research the topic, verify claims, build `fact_pack.json`,
derive the thesis *from* the evidence, build `producer_outline.json` with
`visual_requests` for Agent B. This is the conceptual A1 (evidence collection) + A2
(verification) + A3 (story architecture) work other project docs (`CLAUDE.md`,
`schemas/*.json`) refer to by those stage names -- same work, one invocation.

**A-FINAL** (one session, after Agent B returns asset coverage; this is the
conceptual A4 stage): read the airable claims + outline + asset coverage, write
`final_script.json` in the channel's `output_language`. Don't re-research unless a genuine new factual problem surfaces.
Feed it a compact packet per airable claim (`claim_id`, the fact, `safe_wording`) plus
thesis/hook/beats/coverage -- not the full source trail; provenance stays in
`fact_pack.json` for audit and doesn't need to round-trip into the writer's context.

**Reads:** `episode_brief.json`, then `asset_inventory.json` (A-FINAL only)
**Writes:** `fact_pack.json` + `producer_outline.json` (A-PRE), `final_script.json` (A-FINAL)

Target is practical documentary accuracy, not an academic literature review: a
knowledgeable viewer shouldn't catch a wrong year, an invented number, a fake quote,
the wrong person, unsupported causation, or a misleading comparison. Nothing more.

## Principles

1. **The quirk is a question, not a fact.** Never copy it into the thesis or a claim
   without independent support. The thesis is an *output* of research, not an input
   you search to confirm.
2. **Use real sources.** Never fill a gap from model memory -- an honestly
   unresolved claim beats an invented one.
3. **Reference sources are fine for ordinary, uncontested background** (dates, basic
   lineage, ownership, chronology). Don't over-research facts nobody disputes.
4. **Scrutinize harder where it matters:** thesis/hook claims, important numbers,
   quotes, causal claims ("X happened because Y"), disputed/reputation-sensitive
   claims. For these, try the canonical source, an alternate URL, an archive/reprint,
   or independent corroboration before marking it unresolved.
5. **Wording must never exceed the evidence.** "Reportedly"/"approximately"/"one
   source says" must not quietly become "definitely"/"exactly"/"caused" in
   `safe_wording`, the outline, or eventual narration -- check the hedge words match.
6. **Preserve conflicts, don't paper over them.** When credible sources disagree,
   record it in `conflicting_evidence` rather than picking one, averaging, or
   blending two series. A safe rounded/attributed statement ("roughly six thousand")
   is fine when it genuinely represents the agreement, not as a dodge.
7. **Derived numbers are calculated, not eyeballed.** A `derived_comparison` claim
   needs `source_claim_ids` + a literal `calculation` + a `result` that names its
   comparator explicitly (vs. what, which period, which market/tier) -- and it can
   never be more confident or more airable than its weakest input.
8. **Distinguish who's speaking.** A manufacturer's claim, a journalist's
   independent comparison, what people actually did, a later historian's judgment,
   and your own inference are different claim types -- don't collapse them just
   because they point the same narrative direction.
9. **Atomicity is practical, not microscopic.** Split a claim only when its parts
   could independently be wrong or need different confidence/eligibility. Don't
   shred an ordinary fact into fragments nobody will separately cite.
10. **Stop once the story is reliably supported.** Soft targets for a normal
    episode: 5-10 sources, 8-15 searches, 15-25 claims -- not hard limits, just a
    signal to spend effort proportionally rather than chasing every tempting detail.

## Source provenance (lean)

Per source: `url`, `title`, `publisher`, `source_language`, `source_classification`
(`contemporary_primary` / `later_primary` / `authoritative_secondary` /
`reputable_secondary` / `reference_source` / `discovery_only`), `access_status`
(`read_full` / `read_partial` / `search_snippet_only` / `unavailable`),
`evidence_note`. Add `author` / `publication_date` / `evidence_location` only when
they materially matter.

Quality and accessibility are different axes: a source blocked by a 403 keeps its
`source_classification` -- it's just `access_status: unavailable`, and the claim's
`confidence` absorbs the uncertainty.

`perspective`: `contemporary` (an opinion/reaction/pitch expressed at the time) /
`retrospective_judgment` (a later evaluation) / `timeless_or_historical_fact` (a
fixed data point, regardless of when it was compiled -- most prices, dates, specs,
and production figures belong here, not wherever the compiling source's own
publish date would suggest).

## Runtime and story shape

Read the channel's `runtime_policy` and set `estimated_runtime_sec` +
`runtime_rationale` after the beats exist -- from evidence/story/visual density, not
automatically at `preferred_minutes`. 5-8 beats, each earning its place (introduces a
problem, reveals a decision, explains a mechanism, shows a contrast/turn/consequence,
or resolves the core question).

## A-FINAL gate

Forbidden until `asset_inventory.status` is `gathered`/`approved` **and** every
`visual_request` has a `request_coverage` entry -- the file existing at `pending`
from CLI init doesn't count. `not_found` is valid coverage; a missing entry isn't.
Write directly in the channel's `output_language`/`narration_register`, not a
translation pass. Every factual block cites `supporting_claim_ids` from airable
claims; empty only for pure transitions/banter.

## A-FINAL writing

A-FINAL is an editor, not a fact-pack serializer.

- **Airable means eligible, not mandatory.** `allowed_in_narration: true` means a
  claim *may* be used -- not that it must appear, that every supporting claim needs
  a sentence, or that every beat earns equal runtime. Select the smallest set of
  facts that tells the strongest, clearest story: omit low-value or redundant
  material, compress or effectively skip a beat whose evidence adds nothing, combine
  neighboring material naturally. Never invent a fact to fill the gap. The result
  should read as a documentary built from research, not research notes read aloud.
- **Keep research uncertainty backstage unless the disagreement itself is part of
  the story.** Don't narrate the research process -- what couldn't be accessed, that
  only one source had something, what a confidence rating means, why a claim is
  unresolved. If a weak or unresolved claim isn't needed, cut it rather than
  explaining why it's shaky; omission usually beats narrating the verification
  process. Narrate uncertainty only when it's itself historically interesting (e.g.
  "accounts differ over who proposed it") -- and even then, use the minimum hedge
  ("reportedly" / "around" / "one account says"), never a paragraph about method.

## Validation

Run `python scripts/validate_episode.py <episode_id>` after A-PRE. It mechanically
checks schema shape, claim-reference integrity, the derived-claim-capped-by-inputs
rule, arithmetic, the A-FINAL gate, and runtime-vs-policy, so this document doesn't
need to re-explain them. It can't judge paraphrase creep, causal-claim strength, or
whether scene-setting is actually sourced -- that stays editorial judgment.

## Out of scope

Sourcing/selecting visuals (Agent B), timeline/timing math (the renderer).
