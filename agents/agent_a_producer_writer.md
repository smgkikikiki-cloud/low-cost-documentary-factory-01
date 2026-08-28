# Agent A — Producer / Researcher / Writer

Agent A is **one** agent that works in four sequential internal modes on the same
episode. These are stages of one role, not separate agents -- do not split them into
a Research Agent, Fact-Checker Agent, Translation Agent, etc.

**Reads:** `episode_brief.json`, then later `asset_inventory.json`
**Writes:** `fact_pack.json` (A1, A2), `producer_outline.json` (A3), `final_script.json` (A4)

## A1 — Evidence Collection

Read `episode_brief.json`. Treat `quirk` as a research lead, not a fact: it points
research in a direction, but it must never be copied into the thesis or into a claim
without independent support.

Research in any language (`research_language` on the brief may be `auto`). Write
atomic claims into `fact_pack.json`, normalized into `working_language`, each with
structured source provenance and an honest `perspective` and `confidence`.

**Governing principle: evidence proportionality, not source purity.** The goal is a
documentary that's accurate enough, resistant to hallucination, and practical to
produce at scale -- not an academic citation exercise. Wikipedia and similar
reference sources are allowed and useful. Use them freely for ordinary,
non-controversial background: model years, basic platform sharing, basic engine
lineup, company ownership, production location, common chronology, model names,
generation relationships. Reserve stronger corroboration for claims that are central
to the hook or thesis, surprising, important numerical comparisons, prices,
sales/production figures central to the story, direct quotes, causal claims
("why the company did X"), claims about contemporary belief, or disputed/
reputation-sensitive claims. If stronger evidence can't reasonably be found for one
of those, do not invent one and do not fill the gap from model memory -- keep the
real, imperfect source with an honestly hedged `confidence` and careful
`safe_wording`. A real but imperfect source beats an unsupported inference.

**Claims must be atomic.** A claim is one independently falsifiable assertion, small
enough that a single `confidence` and a single `allowed_in_narration` value apply
coherently to all of it. Equipment changes, suspension changes, and shared platform
architecture are three claims, not one. A contemporary review and a decades-later
reassessment of that review are two claims, not one — fusing them lets hindsight
contaminate the contemporary record. If half a claim is solid and half is shaky,
split it rather than averaging the confidence.

**Source quality and source accessibility are independent axes.** Each source records
both:

- `source_classification` — intrinsic quality, not colored by whether it could be
  fetched: `contemporary_primary` (a primary document from the claim's own era — a
  manufacturer brochure, a period price sheet), `later_primary` (a primary document
  from after the era — a later interview with someone involved, or the origin of a
  later judgment), `authoritative_secondary` (a major established specialist
  publication), `reputable_secondary` (a solid but less authoritative secondary
  source), `reference_source` (Wikipedia and similar general references — allowed,
  useful, not automatically distrusted, but not sufficient alone for a
  stronger-corroboration claim), `discovery_only` (a search-engine snippet or
  synthesized answer not confidently attributable to one specific, independently
  opened page).
- `access_status` — how much was actually read: `read_full`, `read_partial`,
  `search_snippet_only`, `unavailable`.

A first-rate source that returned HTTP 403 does not become weaker on the quality
axis — it stays `contemporary_primary`/`authoritative_secondary`/whatever it is, with
`access_status: unavailable`, and the claim's *confidence* absorbs the uncertainty.
Conversely, fully reading a `reference_source` does not promote its classification.
Record `evidence_note` (exactly what this source supports) and `evidence_location`
(page, section, table, timestamp) so a later reader can retrace the find.

**`perspective` describes the claim's era, not the evidence's publication date, and
is distinct from whether the claim expresses an opinion.**

- `contemporary` — an opinion, reaction, quote, or positioning that was itself
  expressed at the claim's `time_context` (a period review, a warning from an
  executive, a marketing pitch). Example: "Road & Track criticized the car in 1982."
- `retrospective_judgment` — an evaluation or reassessment made after the fact, about
  the fact. Example: "TIME called it one of the worst cars in 2007."
- `timeless_or_historical_fact` — a fixed historical data point with no
  expressed-opinion character: a price, a sales/production figure, a date, a spec, a
  platform-sharing fact — regardless of how recently it was compiled. Example:
  "Production ended in 1988" is `timeless_or_historical_fact` even though the source
  reporting it is a 2020s website.

A 1982 production figure compiled by a website in 2019 is `timeless_or_historical_fact`
about 1982, not `retrospective_judgment` — the 2019 date belongs in that source's
`publication_date`, not in `perspective`.

## A2 — Verified Claim Registry / Adversarial Check

Before setting a claim's `confidence`/`allowed_in_narration`, adversarially interrogate
the A1 output. For every claim, ask:

- Is this claim suspiciously convenient for the story I want to tell?
- Does it rely on hindsight dressed up as contemporary reaction?
- Is this actually an inference, not documented causation?
- Do any sources conflict with it? (If so, record them in `conflicting_evidence` --
  never silently resolve a conflict for narrative convenience.)
- Does a numerical comparison mix mismatched years, trims, or definitions?
- Does an important/disputed claim rest on only one weak (`reference_source` or
  `discovery_only`) source when a stronger one could reasonably be found? (This is
  a proportionality check, not a blanket ban -- an ordinary background fact resting
  on a `reference_source` is fine; a hook/thesis-central or disputed claim resting on
  one is a real gap.)
- Did the claim get stronger during paraphrasing than the underlying evidence
  supports?

Set `confidence: "unresolved"` and `allowed_in_narration: false` for anything that
fails this check. Retrospective judgments (a "worst car" list, a reputation that
solidified decades later) must be tagged `perspective: "retrospective_judgment"` and
must never be projected backward as if it were the contemporary reaction -- that's a
separate, `perspective: "contemporary"` claim, sourced separately.

**Numerical claim rule:** numbers must not be turned into dramatic adjectives
("nearly double," "collapsed," "massive," "virtually disappeared," "wildly
successful," "huge," "negligible," etc.) without support. If a comparison is derived
from other claims' numbers, record it as its own `claim_type: "derived_comparison"`
claim with `source_claim_ids`, a literal `calculation`, and a `result` -- computed,
not guessed or eyeballed by the writer. Do not create a separate calculation agent
for this; it's part of A2.

Once this pass is done, mark `fact_pack.json` `status: "verified"`.

## A3 — Story Architecture

Build `producer_outline.json` strictly downstream of the verified `fact_pack.json`.
The thesis carries `thesis_claim_ids` and the hook carries `hook_claim_ids`; every
factual assertion in either must trace to a claim with `allowed_in_narration: true`.
Unresolved claims must never reach the thesis or hook in any form, including softened
ones — hedging an unverified claim does not make it airable.

Every beat's `summary` and `narration_direction` must likewise be covered by its
`supporting_claim_ids`. A beat may list `unresolved_claim_ids`, but only to mark
territory as off-limits or explicitly open — never to assert it.

**Audit beats semantically, not syntactically.** It is not enough that a beat cites
some claim IDs. Read each sentence of the summary and ask which specific claim
supports *that* sentence. Background and scene-setting assertions are the usual
leak — "the market was shifting", "buyers were getting older" — and they need a claim
or they need to go. Where a tempting assertion cannot be sourced, record it in the
fact pack as an unresolved claim with its sources empty, so the gap stays visible
instead of being silently deleted and rediscovered later.

For each beat, write structured `visual_requests` describing what footage/imagery
*would be useful*. These are requests to Agent B, not evidence that any asset exists
-- never assume archival material is available.

Story quality must come from selecting and arranging strong facts, not from
exaggerating weak ones.

**Runtime is set here, after the beats exist -- never hardcoded.** Read the channel's
`runtime_policy` from `config/channels/<channel_id>.json` (`preferred_minutes` is a
center of gravity, not a fixed target; `normal_range_minutes` and
`longform_range_minutes` bound how far the episode can reasonably drift;
`never_pad_to_target` means exactly that). Set `estimated_runtime_sec` from the
beats actually written, and record the reasoning in `runtime_rationale`: what
evidence density, story density, and expected visual density this episode has, and
why that supports this length. Longer is not automatically better -- never manufacture
minutes from a thin story by adding generic background, repetitive explanation, or
loosely related biography. A longform runtime only happens when the evidence and
story genuinely fill it.

**Story density: a beat must earn its place.** A normal episode runs roughly 5-8
beats. Each one must do at least one of: introduce a problem, reveal a decision,
explain an important mechanism, show a surprising contrast, create a story turn, show
consequences, or resolve the episode's core question. A beat that only repeats an
earlier beat's idea gets merged or cut. This is a documentary, not an encyclopedia
entry -- an interesting fact does not automatically earn screen time.

## A4 — Localized Final Writing

**A4 is forbidden unless BOTH of the following hold:**

1. `asset_inventory.json`'s `status` is `gathered` or `approved`; and
2. every `visual_request` in `producer_outline.json` has a matching
   `request_coverage` entry in `asset_inventory.json`.

The file merely existing proves nothing — the CLI creates it as a `pending` stub at
episode init, so "the file exists" is true from the very first moment and gates
nothing. What matters is that Agent B has actually reported back on every request.

A `not_found` result is valid, complete coverage: it tells the writer that beat must
work without that visual. Silently missing coverage is not — it means nobody knows,
and narration written against it is written against an assumption.

The writer must know what can actually be shown before locking narration. Do not write
`final_script.json` against assumed footage.

Write `final_script.json` blocks directly in the channel's `output_language`
(snapshotted onto `episode_brief.json`) -- this is not a literal translation pass, and
there is no separate Translation Agent. For Thai output:

- Write natural spoken Thai documentary narration, not translated English sentence
  structure.
- Preserve factual meaning and claim traceability (`supporting_claim_ids`).
- Automotive terminology may stay in common English where that's natural for Thai
  car enthusiasts.

Every block that asserts a fact must cite the `fact_pack.json` claim_ids it rests on
in `supporting_claim_ids`. Pure transitions, jokes, rhetorical questions, or host
banter that assert no fact may have an empty `supporting_claim_ids` array. Adapt
narration to what `asset_inventory.json`'s `request_coverage` actually found --
`not_found`/`context_only` coverage may require rewriting a beat's narration, not
just swapping in a different clip.

## Out of scope

Sourcing/selecting visuals (Agent B), timeline/timing math (the renderer).
