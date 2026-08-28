# PROJECT_INSPECTION.md

Generated for external review. This is a point-in-time dump of the repository's
contents and structure — it makes no changes to any project file.

---

## 1. Complete project tree

```
.
├── CLAUDE.md
├── README.md
├── run_episode.py
├── agents/
│   ├── agent_a_producer_writer.md
│   └── agent_b_archive_visual_editor.md
├── config/
│   └── channels/
│       └── ForeignCarsTH.json
├── schemas/
│   ├── episode_brief.json
│   ├── fact_pack.json
│   ├── producer_outline.json
│   ├── asset_inventory.json
│   ├── final_script.json
│   └── edit_plan.json
└── episodes/
    └── ForeignCarsTH_cadillac-cimarron/
        ├── episode_brief.json
        ├── fact_pack.json
        ├── producer_outline.json
        ├── asset_inventory.json
        ├── final_script.json
        └── edit_plan.json
```

---

## 2. Project documentation and agent specs

### CLAUDE.md

```markdown
# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repository.

## What this is

A minimal, low-cost automated documentary content factory. Two LLM agents research,
plan, and script an episode and locate its visuals; a deterministic renderer (added
later) turns those into video. No servers, no database, no dashboard — episode state
lives entirely in flat JSON files on disk.

## Pipeline

```
episode_brief.json
    |  Agent A (A1 evidence collection + A2 adversarial verification)
    v
fact_pack.json
    |  Agent A (A3 story architecture)
    v
producer_outline.json
    |  Agent B (real asset discovery)
    v
asset_inventory.json
    |  Agent A (A4 localized final writing)
    v
final_script.json                    -- TTS later
    |  Agent B (edit planning)
    v
edit_plan.json                       -- deterministic renderer later
```

- **Agent A (Producer/Researcher/Writer)** — `agents/agent_a_producer_writer.md`. One
  agent, four internal modes (A1-A4). Writes `fact_pack.json` and
  `producer_outline.json`, then later `final_script.json`.
- **Agent B (Archive/Visual Editor)** — `agents/agent_b_archive_visual_editor.md`.
  Writes `asset_inventory.json` and `edit_plan.json`.
- **Renderer** — FFmpeg/Remotion, not implemented yet. Will consume `edit_plan.json`
  only; it makes no creative decisions.

Every stage file has a `status` field; a stage is only safe to run once its inputs'
status says so.

## Pipeline invariants

1. **Evidence before narrative.** Nothing gets written into `producer_outline.json`
   or `final_script.json` that isn't traceable to a `fact_pack.json` claim_id.
2. **The quirk is a lead, not a conclusion.** `episode_brief.json`'s `quirk` seeds
   research; it must never be auto-promoted into the thesis or into a claim without
   independent verification (see `fact_pack.json`'s `quirk_lead`).
3. **Fact pack before outline.** `fact_pack.json` must reach `status: "verified"`
   (A2's adversarial pass done) before `producer_outline.json` is built from it.
4. **Real asset inventory before final script.** `final_script.json` (A4) must not be
   written until Agent B has produced `asset_inventory.json` for the episode. The
   outline may *request* visuals (`visual_requests`); it must never assume they exist.
5. **Final narration language comes from channel config.** `final_script.json`'s
   `output_language` must match the channel's `output_language`, snapshotted onto
   `episode_brief.json` at init time. Localization happens inside A4 as natural
   spoken narration, not a literal translation pass.
6. **No separate Translation Agent.** Localization is a mode of Agent A, not a
   third agent.
7. **Every factual script claim traces back to the fact pack.** Each
   `final_script.json` block's `supporting_claim_ids` must resolve to
   `fact_pack.json` claims with `allowed_in_narration: true`. Only pure transitions/
   banter that assert no fact may have an empty list.
8. **Rendering is deterministic and comes much later.** Don't build FFmpeg/Remotion
   code speculatively.
9. **Two AI agents, not more.** Keep the architecture at Agent A + Agent B unless a
   demonstrated bottleneck later proves a third agent is necessary — research,
   fact-checking, translation, and QA are internal stages of Agent A, not separate
   agents.

## Layout

- `episodes/<episode_id>/` — one folder per episode, holding the six JSON state
  files above. `episode_id` is `<channel_id>_<slugified-topic>`.
- `agents/` — role specs for Agent A and Agent B (prompts, not code, for now).
- `config/channels/<channel_id>.json` — per-channel defaults (`research_language`,
  `working_language`, `output_language`, `narration_register`, `target_audience`)
  used when initializing an episode.
- `schemas/` — JSON Schema (draft-07) for every episode state file. Validate against
  these before an agent hands off to the next stage.
- `run_episode.py` — CLI. Currently one command: `init`.

## Language architecture

Research and audience language are separate concepts, both snapshotted onto
`episode_brief.json` at init time so an episode stays reproducible even if the
channel config later changes:

- `research_language` — what language(s) Agent A may research in (`"auto"` means any).
- `working_language` — the internal language `fact_pack.json` normalized claims are
  written in, for consistency across an episode researched in multiple languages.
- `output_language` — the language `final_script.json` narration MUST be written in.
- `narration_register` — style guidance for A4 (e.g. `"natural_spoken_thai"`).

## Conventions

- Keep episode state as plain JSON matching `schemas/*.json` — no new state stores.
- Don't add infrastructure (DB, Docker, cloud, dashboard, scraping) or new agents
  beyond A and B unless explicitly asked; this project is intentionally minimal.
- The renderer is deterministic and out of scope until it's explicitly requested —
  don't start implementing FFmpeg/Remotion code speculatively.

## CLI

```bash
python run_episode.py init --channel <channel_id> --topic "<topic>" --quirk "<quirk>"
```

Looks up `config/channels/<channel_id>.json`, creates
`episodes/<channel_id>_<topic-slug>/`, and writes `episode_brief.json` (with the
channel's language settings snapshotted in) plus empty (`status: pending`) stubs for
`fact_pack.json`, `producer_outline.json`, `asset_inventory.json`,
`final_script.json`, and `edit_plan.json`.
```

### agents/agent_a_producer_writer.md

```markdown
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
atomic claims into `fact_pack.json`, normalized into `working_language`, each with its
raw source(s) and an honest `source_classification`, `perspective`, and `confidence`.

## A2 — Verified Claim Registry / Adversarial Check

Before setting a claim's `confidence`/`allowed_in_narration`, adversarially interrogate
the A1 output. For every claim, ask:

- Is this claim suspiciously convenient for the story I want to tell?
- Does it rely on hindsight dressed up as contemporary reaction?
- Is this actually an inference, not documented causation?
- Do any sources conflict with it? (If so, record them in `conflicting_evidence` --
  never silently resolve a conflict for narrative convenience.)
- Does a numerical comparison mix mismatched years, trims, or definitions?
- Does an important/disputed claim rest on only one weak (`reference_only`) source
  when a stronger one could reasonably be found?
- Did the claim get stronger during paraphrasing than the underlying evidence
  supports?

Set `confidence: "unresolved"` and `allowed_in_narration: false` for anything that
fails this check. Retrospective judgments (a "worst car" list, a reputation that
solidified decades later) must be tagged `perspective: "retrospective"` and must
never be projected backward as if it were the contemporary reaction -- that's a
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

Build `producer_outline.json` strictly downstream of the verified `fact_pack.json`:
thesis, hook, and every beat's `summary`/`narration_direction` must be traceable to
`supporting_claim_ids` (claims with `allowed_in_narration: true`). A beat may
reference `unresolved_claim_ids` too, but only to flag them as open questions -- never
to assert them as settled.

For each beat, write structured `visual_requests` describing what footage/imagery
*would be useful*. These are requests to Agent B, not evidence that any asset exists
-- never assume archival material is available.

Story quality must come from selecting and arranging strong facts, not from
exaggerating weak ones.

## A4 — Localized Final Writing

**A4 is forbidden until Agent B has produced `asset_inventory.json` for this episode.**
The writer must know what can actually be shown before locking narration -- do not
write `final_script.json` against assumed footage.

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
```

### agents/agent_b_archive_visual_editor.md

```markdown
# Agent B — Archive/Visual Editor

**Reads:** `producer_outline.json`
**Writes:** `asset_inventory.json`, then later `edit_plan.json`

## Responsibilities

1. For each `visual_request` across `producer_outline.json`'s beats, search for a real
   matching asset and record it in `asset_inventory.json`'s `assets` array, or record
   its absence. Every request gets a `request_coverage` entry
   (`found_exact` / `found_partial` / `context_only` / `not_found`) -- a request is
   never silently dropped, and a found asset is never claimed to match more than it
   actually shows (`exact_subject_match`).
2. Once `final_script.json` is locked, turn its blocks plus the asset inventory into
   `edit_plan.json`: a concrete clip-by-clip timeline (asset, start/end, caption) with
   no remaining creative decisions.

## Out of scope

Writing narration (Agent A), actual rendering (FFmpeg/Remotion renderer). Not yet
implemented: actual searching/downloading -- only the data contract
(`schemas/asset_inventory.json`) exists so far.
```

### config/channels/ForeignCarsTH.json

```json
{
  "channel_id": "ForeignCarsTH",
  "research_language": "auto",
  "working_language": "en",
  "output_language": "th",
  "narration_register": "natural_spoken_thai",
  "target_audience": "Thai car enthusiasts interested in obscure foreign automotive history"
}
```

---

## 3. Schemas (schemas/*.json)

### schemas/episode_brief.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "episode_brief.schema.json",
  "title": "EpisodeBrief",
  "description": "The seed spec for one episode. Created by the CLI at episode init time, which snapshots the channel's language settings here so the episode stays reproducible even if the channel config changes later. Consumed by Agent A.",
  "type": "object",
  "required": [
    "channel_id",
    "research_language",
    "working_language",
    "output_language",
    "narration_register",
    "topic",
    "quirk",
    "target_audience"
  ],
  "additionalProperties": false,
  "properties": {
    "episode_id": {
      "type": "string",
      "description": "Unique slug for the episode folder, e.g. ForeignCarsTH_cadillac-cimarron"
    },
    "channel_id": {
      "type": "string",
      "description": "Identifier of the channel this episode belongs to, e.g. ForeignCarsTH"
    },
    "research_language": {
      "type": "string",
      "description": "Snapshot of the channel's research_language. 'auto' means research may draw on sources in any language."
    },
    "working_language": {
      "type": "string",
      "description": "Snapshot of the channel's working_language -- the internal language fact_pack.json normalized claims are written in"
    },
    "output_language": {
      "type": "string",
      "description": "Snapshot of the channel's output_language -- final_script.json narration MUST be written directly in this language"
    },
    "narration_register": {
      "type": "string",
      "description": "Snapshot of the channel's narration_register, e.g. 'natural_spoken_thai' -- guides A4 localized writing style"
    },
    "topic": {
      "type": "string",
      "description": "The subject of the episode, e.g. Cadillac Cimarron"
    },
    "quirk": {
      "type": "string",
      "description": "The specific angle/hook that makes this episode interesting. A research lead, NOT a pre-verified fact or a guaranteed thesis -- see fact_pack.json's quirk_lead."
    },
    "target_audience": {
      "type": "string",
      "description": "Who this episode is made for, e.g. car enthusiasts, general audience"
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "status": {
      "type": "string",
      "enum": ["draft", "ready_for_producer"],
      "default": "draft"
    }
  }
}
```

### schemas/fact_pack.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "fact_pack.schema.json",
  "title": "FactPack",
  "description": "Agent A's (A1 Evidence Collection / A2 Verified Claim Registry) evidence boundary between research and storytelling. producer_outline.json may only cite claim_ids that exist here; final_script.json narration may only assert claims marked allowed_in_narration.",
  "type": "object",
  "required": ["episode_id", "status", "claims"],
  "additionalProperties": false,
  "properties": {
    "episode_id": { "type": "string" },
    "status": {
      "type": "string",
      "enum": ["pending", "collected", "verified"],
      "default": "pending",
      "description": "pending: not started. collected: A1 evidence collection done. verified: A2 adversarial pass done, allowed_in_narration values are trustworthy."
    },
    "research_language": {
      "type": "string",
      "description": "Snapshot of the channel's research_language at collection time (research itself may draw on sources in any language)"
    },
    "working_language": {
      "type": "string",
      "description": "Snapshot of the channel's working_language -- normalized_claim text is written in this language for internal consistency"
    },
    "quirk_lead": {
      "type": "object",
      "description": "The episode_brief's quirk, carried forward as a research lead only. It is NOT a claim and must never be treated as pre-verified or auto-promoted to the thesis.",
      "additionalProperties": false,
      "properties": {
        "text": { "type": "string" },
        "note": {
          "type": "string",
          "default": "Research lead only -- not a verified fact. Must not be assumed as the thesis until supported by claims in this fact pack."
        }
      }
    },
    "claims": {
      "type": "array",
      "description": "Atomic, independently traceable claims. Includes both sourced claims and derived_comparison claims (numbers computed from other claims -- see the numerical claim rule in agents/agent_a_producer_writer.md).",
      "items": {
        "type": "object",
        "required": [
          "claim_id",
          "normalized_claim",
          "claim_type",
          "time_context",
          "source_language",
          "sources",
          "source_classification",
          "perspective",
          "confidence",
          "allowed_in_narration",
          "safe_wording",
          "forbidden_or_unsupported_inference",
          "conflicting_evidence",
          "notes"
        ],
        "additionalProperties": false,
        "properties": {
          "claim_id": { "type": "string" },
          "normalized_claim": {
            "type": "string",
            "description": "The claim stated plainly in working_language, independent of any beat's phrasing"
          },
          "claim_type": {
            "type": "string",
            "enum": ["fact", "quote", "statistic", "derived_comparison", "reputation_assessment", "context"]
          },
          "time_context": {
            "type": "string",
            "description": "The time period the claim is ABOUT, e.g. '1982', '1985-1987', '2007'"
          },
          "source_language": {
            "type": "string",
            "description": "Primary language of the source(s) used, e.g. 'en'"
          },
          "sources": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Source URLs (or citations) for this claim. May be empty for a derived_comparison claim, which cites source_claim_ids instead."
          },
          "source_classification": {
            "type": "string",
            "enum": ["contemporary_primary", "later_primary", "high_quality_secondary", "reference_only"]
          },
          "perspective": {
            "type": "string",
            "enum": ["contemporary", "retrospective", "timeless"],
            "description": "contemporary: asserted/observed at time_context. retrospective: a later judgment projected onto time_context -- must not be presented as what people thought at the time. timeless: not time-bound (e.g. platform-sharing fact)."
          },
          "confidence": {
            "type": "string",
            "enum": ["high", "medium", "unresolved"],
            "description": "unresolved claims cannot be stated as fact in narration -- allowed_in_narration must be false"
          },
          "allowed_in_narration": {
            "type": "boolean",
            "description": "Whether this claim, as currently evidenced, may be asserted as fact in final_script.json. Must be false whenever confidence is 'unresolved'."
          },
          "safe_wording": {
            "type": "string",
            "description": "Pre-approved phrasing that does not overclaim beyond the evidence -- the wording a writer may use, or the hedge to use if allowed_in_narration is false"
          },
          "forbidden_or_unsupported_inference": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Specific conclusions a writer might be tempted to draw from this claim that the evidence does NOT support"
          },
          "conflicting_evidence": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Other data points/sources that disagree with this claim. Must be preserved here rather than silently resolved for narrative convenience; empty array if none."
          },
          "notes": { "type": "string" },
          "source_claim_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Required (by convention, not schema) when claim_type is derived_comparison: the claim_ids the calculation is derived from"
          },
          "calculation": {
            "type": "string",
            "description": "For derived_comparison claims: the literal arithmetic performed, e.g. '(12131 - 9712) / 9712 * 100'"
          },
          "result": {
            "type": "string",
            "description": "For derived_comparison claims: the calculated result, stated with its comparator explicit"
          }
        }
      }
    }
  }
}
```

### schemas/producer_outline.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "producer_outline.schema.json",
  "title": "ProducerOutline",
  "description": "Agent A's (A3 Story Architecture) structural plan for the episode. Downstream of fact_pack.json: every supporting_claim_ids/unresolved_claim_ids entry must reference a claim_id that exists there, and this file must not introduce factual claims fact_pack.json doesn't contain. visual_requests are requests to Agent B, not evidence that any asset exists.",
  "type": "object",
  "required": ["episode_id", "status", "thesis", "beats"],
  "additionalProperties": false,
  "properties": {
    "episode_id": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": ["pending", "drafted", "approved"],
      "default": "pending"
    },
    "thesis": {
      "type": "string",
      "description": "The one-sentence argument/story the episode is built around. Must be supported by fact_pack.json claims, not auto-derived from episode_brief.quirk."
    },
    "hook": {
      "type": "string",
      "description": "The cold-open line(s) meant to grab attention before the thesis unfolds"
    },
    "estimated_runtime_sec": {
      "type": "integer",
      "minimum": 0
    },
    "open_questions": {
      "type": "array",
      "description": "Outline-level open questions that aren't tied to one fact_pack claim (e.g. structural/strategic questions). Per-claim uncertainty belongs in fact_pack.json instead.",
      "items": { "type": "string" }
    },
    "beats": {
      "type": "array",
      "description": "Ordered narrative beats making up the episode",
      "items": {
        "type": "object",
        "required": [
          "beat_id",
          "purpose",
          "summary",
          "supporting_claim_ids",
          "unresolved_claim_ids",
          "narration_direction",
          "visual_requests"
        ],
        "additionalProperties": false,
        "properties": {
          "beat_id": { "type": "string" },
          "purpose": {
            "type": "string",
            "description": "Why this beat exists -- its narrative function in the episode"
          },
          "summary": { "type": "string" },
          "supporting_claim_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "fact_pack.json claim_ids (allowed_in_narration: true) this beat is built on"
          },
          "unresolved_claim_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "fact_pack.json claim_ids this beat references but that are NOT allowed_in_narration -- must be framed as open/unconfirmed if mentioned at all, never stated as fact"
          },
          "narration_direction": {
            "type": "string",
            "description": "Guidance for the A4 localized-writing stage -- talking points and tone, NOT final narration text"
          },
          "visual_requests": {
            "type": "array",
            "description": "Structured requests to Agent B. A request, not evidence the asset exists.",
            "items": {
              "type": "object",
              "required": [
                "request_id",
                "beat_id",
                "subject",
                "desired_asset_type",
                "description",
                "priority",
                "exact_subject_required"
              ],
              "additionalProperties": false,
              "properties": {
                "request_id": { "type": "string" },
                "beat_id": { "type": "string" },
                "subject": { "type": "string" },
                "desired_asset_type": {
                  "type": "array",
                  "items": {
                    "type": "string",
                    "enum": ["video", "photo", "advertisement", "brochure", "document", "magazine_scan", "map", "chart", "contextual_video"]
                  }
                },
                "description": { "type": "string" },
                "priority": {
                  "type": "string",
                  "enum": ["low", "medium", "high"]
                },
                "exact_subject_required": {
                  "type": "boolean",
                  "description": "If true, only footage/imagery of the exact subject satisfies this request -- generic/contextual substitutes are not acceptable. If false, contextual/period-appropriate substitutes are acceptable."
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### schemas/asset_inventory.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "asset_inventory.schema.json",
  "title": "AssetInventory",
  "description": "Agent B's (Archive/Visual Editor) record of REAL discovered assets for the episode, plus coverage reporting against producer_outline.json's visual_requests. This schema defines the data contract only -- searching/downloading is not implemented yet.",
  "type": "object",
  "required": ["episode_id", "status", "assets", "request_coverage"],
  "additionalProperties": false,
  "properties": {
    "episode_id": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": ["pending", "gathered", "approved"],
      "default": "pending"
    },
    "assets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["asset_id", "matched_request_ids", "asset_type", "subject", "exact_subject_match"],
        "additionalProperties": false,
        "properties": {
          "asset_id": { "type": "string" },
          "matched_request_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "producer_outline.json visual_request request_id values this asset satisfies"
          },
          "source_url": { "type": "string" },
          "local_path": { "type": "string" },
          "asset_type": {
            "type": "string",
            "enum": ["video", "photo", "advertisement", "brochure", "document", "magazine_scan", "map", "chart", "contextual_video"]
          },
          "subject": { "type": "string" },
          "description": { "type": "string" },
          "date_or_period": { "type": "string" },
          "exact_subject_match": {
            "type": "boolean",
            "description": "Whether this asset actually shows the exact subject requested, vs. being a contextual/period substitute"
          },
          "usable_start_sec": { "type": "number", "minimum": 0 },
          "usable_end_sec": { "type": "number", "minimum": 0 },
          "visual_quality": {
            "type": "string",
            "enum": ["low", "medium", "high"]
          },
          "notes": { "type": "string" }
        }
      }
    },
    "request_coverage": {
      "type": "array",
      "description": "One entry per producer_outline.json visual_request, reporting what was actually found -- lets Agent A adapt final narration to what exists.",
      "items": {
        "type": "object",
        "required": ["request_id", "beat_id", "coverage_status", "asset_ids"],
        "additionalProperties": false,
        "properties": {
          "request_id": {
            "type": "string",
            "description": "References a visual_request request_id from producer_outline.json"
          },
          "beat_id": { "type": "string" },
          "coverage_status": {
            "type": "string",
            "enum": ["found_exact", "found_partial", "context_only", "not_found"]
          },
          "asset_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "asset_id values in this file that address the request, if any"
          },
          "notes": { "type": "string" }
        }
      }
    }
  }
}
```

### schemas/final_script.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "final_script.schema.json",
  "title": "FinalScript",
  "description": "The locked, localized narration script. Written by Agent A's A4 stage, which is forbidden until asset_inventory.json exists for this episode (final narration must know what can actually be shown). Any block that asserts a factual claim must cite it via supporting_claim_ids; the script must not introduce facts absent from fact_pack.json.",
  "type": "object",
  "required": ["episode_id", "output_language", "status", "blocks"],
  "additionalProperties": false,
  "properties": {
    "episode_id": {
      "type": "string"
    },
    "output_language": {
      "type": "string",
      "description": "Must match the channel's output_language (snapshotted on episode_brief.json) -- narration is written directly in this language, not translated word-for-word from working_language"
    },
    "status": {
      "type": "string",
      "enum": ["pending", "drafted", "locked"],
      "default": "pending"
    },
    "blocks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["block_id", "beat_id", "narration", "supporting_claim_ids", "estimated_duration_sec"],
        "additionalProperties": false,
        "properties": {
          "block_id": { "type": "string" },
          "beat_id": {
            "type": "string",
            "description": "References a beat_id from producer_outline.json"
          },
          "narration": {
            "type": "string",
            "description": "Final narration text, in output_language"
          },
          "supporting_claim_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "fact_pack.json claim_ids this block's factual assertions trace back to. May be empty ONLY for pure transitions, jokes, rhetorical questions, or host banter that assert no fact."
          },
          "asset_ids": {
            "type": "array",
            "items": { "type": "string" },
            "description": "asset_inventory.json asset_id values this block is written around"
          },
          "estimated_duration_sec": { "type": "number", "minimum": 0 }
        }
      }
    }
  }
}
```

### schemas/edit_plan.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "edit_plan.schema.json",
  "title": "EditPlan",
  "description": "The deterministic, machine-executable timeline handed to the renderer (FFmpeg/Remotion). Generated from final_script.json + asset_inventory.json, no further creative decisions left to make.",
  "type": "object",
  "required": ["episode_id", "status", "clips"],
  "additionalProperties": false,
  "properties": {
    "episode_id": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": ["pending", "planned", "rendered"],
      "default": "pending"
    },
    "clips": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["clip_id", "block_id", "asset_id", "start_sec", "end_sec"],
        "additionalProperties": false,
        "properties": {
          "clip_id": { "type": "string" },
          "block_id": {
            "type": "string",
            "description": "References a block_id from final_script.json"
          },
          "asset_id": {
            "type": "string",
            "description": "References an asset_id from asset_inventory.json"
          },
          "start_sec": { "type": "number", "minimum": 0 },
          "end_sec": { "type": "number", "minimum": 0 },
          "narration_audio_path": { "type": "string" },
          "caption_text": { "type": "string" }
        }
      }
    }
  }
}
```

---

## 4. CLI

### run_episode.py

```python
#!/usr/bin/env python3
"""CLI for the documentary content factory.

Usage:
    python run_episode.py init --channel ForeignCarsTH \\
        --topic "Cadillac Cimarron" \\
        --quirk "Cadillac's infamous attempt to turn the GM J-car into a luxury compact"
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES_DIR = ROOT / "episodes"
CHANNELS_DIR = ROOT / "config" / "channels"


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def load_channel(channel_id: str) -> dict:
    channel_path = CHANNELS_DIR / f"{channel_id}.json"
    if not channel_path.exists():
        raise SystemExit(
            f"Unknown channel '{channel_id}': no config at {channel_path.relative_to(ROOT)}"
        )
    return json.loads(channel_path.read_text())


def init_episode(channel_id: str, topic: str, quirk: str) -> Path:
    channel = load_channel(channel_id)
    episode_id = f"{channel_id}_{slugify(topic)}"
    episode_dir = EPISODES_DIR / episode_id

    if episode_dir.exists():
        raise SystemExit(f"Episode folder already exists: {episode_dir.relative_to(ROOT)}")

    episode_dir.mkdir(parents=True)

    episode_brief = {
        "episode_id": episode_id,
        "channel_id": channel_id,
        "research_language": channel["research_language"],
        "working_language": channel["working_language"],
        "output_language": channel["output_language"],
        "narration_register": channel["narration_register"],
        "topic": topic,
        "quirk": quirk,
        "target_audience": channel["target_audience"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
    }
    _write(episode_dir / "episode_brief.json", episode_brief)

    _write(episode_dir / "fact_pack.json", {
        "episode_id": episode_id,
        "status": "pending",
        "research_language": channel["research_language"],
        "working_language": channel["working_language"],
        "quirk_lead": {
            "text": quirk,
            "note": "Research lead only -- not a verified fact. Must not be assumed as the thesis until supported by claims in this fact pack.",
        },
        "claims": [],
    })
    _write(episode_dir / "producer_outline.json", {
        "episode_id": episode_id,
        "status": "pending",
        "thesis": "",
        "beats": [],
    })
    _write(episode_dir / "asset_inventory.json", {
        "episode_id": episode_id,
        "status": "pending",
        "assets": [],
        "request_coverage": [],
    })
    _write(episode_dir / "final_script.json", {
        "episode_id": episode_id,
        "output_language": channel["output_language"],
        "status": "pending",
        "blocks": [],
    })
    _write(episode_dir / "edit_plan.json", {
        "episode_id": episode_id,
        "status": "pending",
        "clips": [],
    })

    return episode_dir


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Documentary content factory CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new episode folder")
    init_parser.add_argument("--channel", required=True, help="Channel ID, e.g. ForeignCarsTH")
    init_parser.add_argument("--topic", required=True, help="Episode topic")
    init_parser.add_argument("--quirk", required=True, help="Episode quirk/angle")

    args = parser.parse_args()

    if args.command == "init":
        episode_dir = init_episode(args.channel, args.topic, args.quirk)
        print(f"Initialized episode at {episode_dir.relative_to(ROOT)}")
        for f in sorted(episode_dir.iterdir()):
            print(f"  {f.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
```

---

## 5. Example episode: episodes/ForeignCarsTH_cadillac-cimarron/

### episode_brief.json

```json
{
  "episode_id": "ForeignCarsTH_cadillac-cimarron",
  "channel_id": "ForeignCarsTH",
  "research_language": "auto",
  "working_language": "en",
  "output_language": "th",
  "narration_register": "natural_spoken_thai",
  "topic": "Cadillac Cimarron",
  "quirk": "Cadillac's infamous attempt to turn the GM J-car into a luxury compact",
  "target_audience": "Thai car enthusiasts interested in obscure foreign automotive history",
  "created_at": "2026-08-28T06:08:05.666252+00:00",
  "status": "draft"
}
```

### fact_pack.json

```json
{
  "episode_id": "ForeignCarsTH_cadillac-cimarron",
  "status": "verified",
  "research_language": "auto",
  "working_language": "en",
  "quirk_lead": {
    "text": "Cadillac's infamous attempt to turn the GM J-car into a luxury compact",
    "note": "Research lead only -- not a verified fact. The claims below support a narrower, more defensible thesis (joined the J-car program too late to differentiate it enough) rather than the quirk's blunter 'infamous attempt' framing."
  },
  "claims": [
    {
      "claim_id": "c1",
      "normalized_claim": "The 1982 Cadillac Cimarron's base price at launch was in the $12,131-$12,181 range.",
      "claim_type": "statistic",
      "time_context": "1982",
      "source_language": "en",
      "sources": [
        "https://en.wikipedia.org/wiki/Cadillac_Cimarron",
        "https://www.hagerty.com/media/opinion/final-parking-space/final-parking-space-1982-cadillac-cimarron/",
        "https://macsmotorcitygarage.com/cadillacs-small-mistake-the-1982-1988-cimarron/"
      ],
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "The 1982 Cimarron launched with a base price of roughly $12,100-12,200.",
      "forbidden_or_unsupported_inference": [
        "Picking one exact figure ($12,131 or $12,181) and presenting it as the single undisputed price without the range"
      ],
      "conflicting_evidence": [
        "Wikipedia and Hagerty give $12,181; Mac's Motor City Garage gives $12,131. Likely rounding or a mid-year adjustment; both figures are retained rather than silently resolved to one."
      ],
      "notes": ""
    },
    {
      "claim_id": "c13",
      "normalized_claim": "A 1982 Chevrolet Cavalier's base price ranged from roughly $6,600 (base coupe) to $7,000-$8,000 (sedan), well below the Cimarron.",
      "claim_type": "statistic",
      "time_context": "1982",
      "source_language": "en",
      "sources": [
        "https://www.hagerty.com/media/opinion/final-parking-space/final-parking-space-1982-cadillac-cimarron/"
      ],
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "A base Chevrolet Cavalier coupe started around $6,600 that same year; a sedan ran $7,000-8,000.",
      "forbidden_or_unsupported_inference": [
        "Using this base-Cavalier figure as if it were a comparably equipped comparator to the Cimarron (see c14 and d1 for the equipped comparison, and d2 for what this figure alone actually supports)"
      ],
      "conflicting_evidence": [],
      "notes": "This is the cheapest, least-equipped Cavalier configuration -- useful for the base-to-base comparison (d2), not for a like-for-like trim comparison."
    },
    {
      "claim_id": "c14",
      "normalized_claim": "A 1982 Chevrolet Cavalier CL (top Cavalier trim) started around $8,137, and cost roughly $9,712 when optioned to Cimarron-equivalent spec.",
      "claim_type": "statistic",
      "time_context": "1982",
      "source_language": "en",
      "sources": [
        "https://www.curbsideclassic.com/vintage-reviews/vintage-reviews-cadillac-cimarron/"
      ],
      "source_classification": "reference_only",
      "perspective": "contemporary",
      "confidence": "unresolved",
      "allowed_in_narration": false,
      "safe_wording": "Do not state these exact figures in narration. If confirmed, the safe wording would be: 'a comparably equipped Cavalier CL ran close to $9,700.'",
      "forbidden_or_unsupported_inference": [
        "Stating '$8,137' or '$9,712' as settled facts",
        "Using this to compute a public-facing percentage premium (see d1) before this claim is resolved"
      ],
      "conflicting_evidence": [],
      "notes": "This is the most important claim in the episode's central price comparison and it is currently the weakest-sourced: the only source found returned HTTP 403 on direct fetch, so these numbers come from a search-engine summary, not a directly read page. Per the adversarial-check rule, an important/disputed claim should not rest on a reference_only source when a stronger one can reasonably be found -- treat resolving this as the top research priority before final_script.json is written. A period Cavalier CL brochure or window sticker would upgrade this to contemporary_primary."
    },
    {
      "claim_id": "d1",
      "normalized_claim": "Premium of the Cimarron's base price over a comparably-equipped Cavalier CL.",
      "claim_type": "derived_comparison",
      "time_context": "1982",
      "source_language": "en",
      "sources": [],
      "source_claim_ids": ["c1", "c14"],
      "calculation": "(12131 - 9712) / 9712 * 100",
      "result": "approx. 24.9% premium (about $2,419) over a comparably equipped Cavalier CL -- roughly a quarter more, not double",
      "source_classification": "reference_only",
      "perspective": "contemporary",
      "confidence": "unresolved",
      "allowed_in_narration": false,
      "safe_wording": "Do not state a specific percentage yet. Once c14 is confirmed, the safe wording is: 'against a similarly equipped Cavalier, the premium was closer to a quarter more than double.'",
      "forbidden_or_unsupported_inference": [
        "Stating '~25% more expensive' as settled fact before c14 is confirmed",
        "Rounding this up to a punchier 'nearly double' framing -- that conflates it with the base-Cavalier comparison in d2"
      ],
      "conflicting_evidence": [],
      "notes": "Blocked on resolving c14's source. This is the claim that should replace any instinct to write 'nearly double the price' in the final script."
    },
    {
      "claim_id": "d2",
      "normalized_claim": "Premium of the Cimarron's base price over the cheapest base Chevrolet Cavalier coupe.",
      "claim_type": "derived_comparison",
      "time_context": "1982",
      "source_language": "en",
      "sources": [],
      "source_claim_ids": ["c1", "c13"],
      "calculation": "(12131 - 6600) / 6600 * 100",
      "result": "approx. 83.8% premium (about $5,531) over the cheapest base Cavalier coupe -- close to double, but only against the least-equipped Cavalier body style",
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "medium",
      "allowed_in_narration": true,
      "safe_wording": "Against the cheapest, most stripped-down Cavalier coupe, the Cimarron's price was close to double -- but that's comparing against the least-equipped Cavalier available, not a like-for-like trim.",
      "forbidden_or_unsupported_inference": [
        "Presenting this as 'the' Cimarron-vs-Cavalier premium without specifying the comparator is the cheapest base coupe",
        "Dropping the qualifier and just saying 'the Cimarron cost nearly double a Cavalier'"
      ],
      "conflicting_evidence": [],
      "notes": "Confidence is medium rather than high only because c1's own base price carries a minor $12,131/$12,181 discrepancy (see c1); the arithmetic itself and both input claims are solid."
    },
    {
      "claim_id": "c2",
      "normalized_claim": "GM president Pete Estes warned Cadillac general manager Edward Kennard that there wasn't enough time to turn the J-car into a real Cadillac ('Ed, you don't have time to turn the J-car into a Cadillac').",
      "claim_type": "quote",
      "time_context": "circa 1980-1981, pre-launch",
      "source_language": "en",
      "sources": ["https://en.wikipedia.org/wiki/Cadillac_Cimarron"],
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "medium",
      "allowed_in_narration": true,
      "safe_wording": "GM president Pete Estes reportedly warned Cadillac general manager Edward Kennard that there wasn't enough time to turn the J-car into a real Cadillac.",
      "forbidden_or_unsupported_inference": [
        "Presenting this as a verbatim primary-source transcript rather than a widely repeated secondary account",
        "Using it to imply GM leadership as a whole opposed the Cimarron"
      ],
      "conflicting_evidence": [],
      "notes": "Attribution (who 'Ed' is) was resolved in a prior research pass via Wikipedia, which names Edward Kennard as Cadillac's general manager at the time."
    },
    {
      "claim_id": "c3",
      "normalized_claim": "The Cimarron shared its J-body platform with the Chevrolet Cavalier, Pontiac J2000, Buick Skyhawk, and Oldsmobile Firenza.",
      "claim_type": "fact",
      "time_context": "1982",
      "source_language": "en",
      "sources": ["https://en.wikipedia.org/wiki/Cadillac_Cimarron"],
      "source_classification": "high_quality_secondary",
      "perspective": "timeless",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "The Cimarron shared its J-body platform with the Chevrolet Cavalier, Pontiac J2000, Buick Skyhawk, and Oldsmobile Firenza.",
      "forbidden_or_unsupported_inference": [],
      "conflicting_evidence": [],
      "notes": ""
    },
    {
      "claim_id": "c8",
      "normalized_claim": "Cadillac standardized real differentiating equipment on the Cimarron versus the Cavalier -- air conditioning, extra sound insulation, deep-pile carpeting, alloy wheels, leather-wrapped steering wheel, full instrumentation, leather upholstery -- plus Cadillac-specific ('F41') suspension tuning, while the platform, body structure, and initial engine remained shared.",
      "claim_type": "fact",
      "time_context": "1982",
      "source_language": "en",
      "sources": ["https://en.wikipedia.org/wiki/Cadillac_Cimarron"],
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "Cadillac did add real equipment and its own suspension tuning -- air conditioning, extra sound insulation, alloy wheels, leather, full instrumentation -- even though the platform, body, and (at first) the engine stayed shared with the Cavalier.",
      "forbidden_or_unsupported_inference": [
        "Reducing this to 'just badges and leather'",
        "Implying the suspension used entirely different hardware rather than Cadillac-specific tuning of shared components"
      ],
      "conflicting_evidence": [],
      "notes": "Supersedes the prior draft's flatter 'badges, leather, and sound insulation' framing."
    },
    {
      "claim_id": "c4",
      "normalized_claim": "A 2.8L V6 became optional on the Cimarron in 1985 (roughly 125-130 hp) and standard equipment by 1987.",
      "claim_type": "fact",
      "time_context": "1985-1987",
      "source_language": "en",
      "sources": ["https://www.conceptcarz.com/vehicle/z1990/cadillac-cimarron.aspx"],
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "A 2.8-liter V6 became optional in 1985 and standard by 1987.",
      "forbidden_or_unsupported_inference": [],
      "conflicting_evidence": [],
      "notes": ""
    },
    {
      "claim_id": "c5",
      "normalized_claim": "Cimarron production ended in 1988; total production across the model run was about 132,499 units, with only 6,454 built in the final year.",
      "claim_type": "statistic",
      "time_context": "1982-1988",
      "source_language": "en",
      "sources": ["https://www.goodcarbadcar.net/cadillac-cimarron-sales-figures/"],
      "source_classification": "high_quality_secondary",
      "perspective": "retrospective",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "Production ended in 1988, after about 132,499 units total -- only 6,454 of them in that final year.",
      "forbidden_or_unsupported_inference": [],
      "conflicting_evidence": [],
      "notes": "perspective is 'retrospective' because this is a modern compiled tally, not a contemporary announcement -- the underlying production events were of course contemporary."
    },
    {
      "claim_id": "c6",
      "normalized_claim": "Annual Cimarron production fell in the car's final years: 25,534 in 1986, 14,561 in 1987, 6,454 in 1988.",
      "claim_type": "statistic",
      "time_context": "1986-1988",
      "source_language": "en",
      "sources": ["https://www.goodcarbadcar.net/cadillac-cimarron-sales-figures/"],
      "source_classification": "high_quality_secondary",
      "perspective": "retrospective",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "Year-over-year production kept falling: 25,534 in 1986, 14,561 in 1987, 6,454 in 1988.",
      "forbidden_or_unsupported_inference": [
        "Attributing the decline solely to reputation without noting the V6/equipment updates happened over this same window"
      ],
      "conflicting_evidence": [],
      "notes": ""
    },
    {
      "claim_id": "c7",
      "normalized_claim": "TIME magazine's 2007 retrospective list named the Cadillac Cimarron among the '50 Worst Cars of All Time.'",
      "claim_type": "reputation_assessment",
      "time_context": "2007",
      "source_language": "en",
      "sources": ["https://content.time.com/time/specials/2007/article/0,28804,1658545_1658533_1658526,00.html"],
      "source_classification": "high_quality_secondary",
      "perspective": "retrospective",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "In 2007, TIME named the Cimarron to its retrospective list of the '50 Worst Cars of All Time.'",
      "forbidden_or_unsupported_inference": [
        "Presenting this as how the car was perceived in 1982",
        "Treating inclusion on one magazine list as objective, universal consensus"
      ],
      "conflicting_evidence": [],
      "notes": "Must be paired with c9/c10 (contemporary reception) in narration so the two eras aren't collapsed into one."
    },
    {
      "claim_id": "c9",
      "normalized_claim": "Car and Driver's original review (Rich Ceppos, August 1981 issue) was notably positive, reportedly calling the Cimarron launch 'one of the boldest moves ever made by a car company'; the author later said he felt embarrassed for having 'effused' over the car once its reputation soured.",
      "claim_type": "quote",
      "time_context": "August 1981",
      "source_language": "en",
      "sources": ["https://www.curbsideclassic.com/vintage-reviews/vintage-reviews-cadillac-cimarron/"],
      "source_classification": "reference_only",
      "perspective": "contemporary",
      "confidence": "unresolved",
      "allowed_in_narration": false,
      "safe_wording": "Do not quote 'one of the boldest moves ever made by a car company' directly until confirmed. Safe interim wording: 'contemporary coverage, including Car and Driver, was reportedly more positive than the car's later reputation would suggest.'",
      "forbidden_or_unsupported_inference": [
        "Quoting the exact phrase as verified when it hasn't been read from a primary or directly-fetched source",
        "Using this to claim ALL contemporary press was positive -- c10 shows contemporary criticism existed too"
      ],
      "conflicting_evidence": [],
      "notes": "Source page returned HTTP 403 on direct fetch; only a search-engine summary was available. Needs primary confirmation (original C&D issue or an independently fetchable reprint) before use as a direct quote in final_script.json."
    },
    {
      "claim_id": "c10",
      "normalized_claim": "A contemporary Road & Track test recorded 0-60 mph in 15.9 seconds for the 1.8L Cimarron and described the performance as 'painfully slow.'",
      "claim_type": "quote",
      "time_context": "1982",
      "source_language": "en",
      "sources": ["https://macsmotorcitygarage.com/cadillacs-small-mistake-the-1982-1988-cimarron/"],
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "Road & Track clocked the original 1.8-liter car at 0-60 in 15.9 seconds and called it 'painfully slow.'",
      "forbidden_or_unsupported_inference": [
        "Applying this performance criticism to the later V6 cars (1985+), which were meaningfully quicker"
      ],
      "conflicting_evidence": [],
      "notes": "Directly confirmed via fetch this session (not just a search summary)."
    },
    {
      "claim_id": "c11",
      "normalized_claim": "Cadillac's own 1982 marketing materials positioned the Cimarron against the Volvo GL, Saab 900S, and BMW 320i.",
      "claim_type": "fact",
      "time_context": "1982",
      "source_language": "en",
      "sources": ["https://www.thedrive.com/news/37839/the-infamous-cadillac-cimarron-was-a-bad-caddy-but-not-as-awful-a-car-as-you-think"],
      "source_classification": "high_quality_secondary",
      "perspective": "contemporary",
      "confidence": "high",
      "allowed_in_narration": true,
      "safe_wording": "Cadillac's own launch brochure named the Volvo GL, Saab 900S, and BMW 320i as the competition.",
      "forbidden_or_unsupported_inference": [],
      "conflicting_evidence": [],
      "notes": "Directly confirmed via fetch this session (quoted from the brochure by the source)."
    },
    {
      "claim_id": "c15",
      "normalized_claim": "Contemporary and retrospective sources also compare the Cimarron's price and positioning against the Audi 4000 and Honda Accord.",
      "claim_type": "fact",
      "time_context": "1982",
      "source_language": "en",
      "sources": ["https://amazingclassiccars.com/cadillac-cimarron-1982/"],
      "source_classification": "reference_only",
      "perspective": "contemporary",
      "confidence": "unresolved",
      "allowed_in_narration": false,
      "safe_wording": "Do not name Audi 4000/Honda Accord as confirmed period competitors until this is independently confirmed; c11's Volvo/Saab/BMW brochure quote is the confirmed version of this claim.",
      "forbidden_or_unsupported_inference": [
        "Stating the ~$2,000 price gap vs. Audi/Accord as a confirmed figure"
      ],
      "conflicting_evidence": [],
      "notes": "Came from a web-search summary, not an independently fetched page. Confirm against amazingclassiccars.com directly, or drop it."
    },
    {
      "claim_id": "c12",
      "normalized_claim": "Former Cadillac product director John Howell reportedly kept a photo of a Cimarron in his office as a cautionary reminder.",
      "claim_type": "context",
      "time_context": "unspecified, retrospective anecdote",
      "source_language": "en",
      "sources": ["https://www.thedrive.com/news/37839/the-infamous-cadillac-cimarron-was-a-bad-caddy-but-not-as-awful-a-car-as-you-think"],
      "source_classification": "high_quality_secondary",
      "perspective": "retrospective",
      "confidence": "medium",
      "allowed_in_narration": true,
      "safe_wording": "Former Cadillac product director John Howell reportedly kept a photo of a Cimarron in his office as a warning to himself.",
      "forbidden_or_unsupported_inference": [
        "Stating this as verified fact rather than a reported anecdote",
        "Implying this was official Cadillac policy or a company-wide sentiment rather than one person's habit"
      ],
      "conflicting_evidence": [],
      "notes": "Source itself hedges with 'reportedly' -- single-source anecdote, kept at medium confidence rather than high."
    }
  ]
}
```

### producer_outline.json

```json
{
  "episode_id": "ForeignCarsTH_cadillac-cimarron",
  "status": "drafted",
  "thesis": "In 1982, Cadillac tried to answer BMW, Volvo, Saab, and Audi's small sport sedans by building its own version of GM's new J-car, and made real (if late and limited) changes to trim, equipment, and suspension tuning. It cost meaningfully more than a base Cavalier, but because Cadillac joined the program too late to differentiate the car enough, it never fully shed its economy-car roots -- and it became a textbook case study in badge engineering.",
  "hook": "In 1982, Cadillac took GM's new compact economy car, gave it leather seats and a script badge, and asked buyers to pay a real premium for it. It didn't work, and people inside GM remembered it for decades afterward.",
  "estimated_runtime_sec": 480,
  "beats": [
    {
      "beat_id": "b1_cold_open",
      "purpose": "Hook the viewer with the badge-on-an-economy-car premise before revealing the model name, and pose the question the episode answers.",
      "summary": "Cold open: an established luxury brand puts its badge on a compact economy car and charges a real premium for it -- a decision people inside the company still cite as a cautionary tale.",
      "supporting_claim_ids": ["c1"],
      "unresolved_claim_ids": [],
      "narration_direction": "Lead with the badge-on-an-economy-car setup and withhold the model name 'Cimarron' for a beat. Gesture at 'a real premium' (c1 supports this) but do not put a percentage or 'nearly double' on it here -- that number is earned later, in b4, via d1/d2. End on a question: how does an established luxury brand end up here?",
      "visual_requests": [
        {
          "request_id": "V001",
          "beat_id": "b1_cold_open",
          "subject": "1982 Cadillac Cimarron next to a same-year Chevrolet Cavalier",
          "desired_asset_type": ["photo", "advertisement"],
          "description": "Side-by-side still of a Cimarron and same-year Cavalier badge/grille close-up, plus a period Cimarron print ad for the opening graphic.",
          "priority": "high",
          "exact_subject_required": true
        }
      ]
    },
    {
      "beat_id": "b2_cadillacs_problem",
      "purpose": "Establish the legitimate business problem Cadillac was trying to solve, so the badge-engineering decision reads as a response to real pressure rather than pure carelessness.",
      "summary": "By the early 1980s Cadillac's buyer base was aging, fuel-economy/downsizing pressure was real, and a wave of European compact sport sedans threatened to pull in younger buyers Cadillac wanted. Cadillac's own launch marketing named the Volvo GL, Saab 900S, and BMW 320i as the competition.",
      "supporting_claim_ids": ["c11"],
      "unresolved_claim_ids": ["c15"],
      "narration_direction": "Use the confirmed competitive set from c11 (Volvo GL, Saab 900S, BMW 320i) as the concrete anchor. Audi 4000/Honda Accord (c15) may be mentioned only as a softer 'often compared to' aside, not asserted as confirmed brochure copy, until c15 is resolved.",
      "visual_requests": [
        {
          "request_id": "V002",
          "beat_id": "b2_cadillacs_problem",
          "subject": "Contemporary BMW 320i, Volvo GL, and Saab 900S",
          "desired_asset_type": ["photo", "advertisement"],
          "description": "Period photos or ads of the BMW 320i, Volvo GL, and Saab 900S to establish the competitive set Cadillac was aiming at.",
          "priority": "medium",
          "exact_subject_required": false
        }
      ]
    },
    {
      "beat_id": "b3_rushed_j_car",
      "purpose": "Explain the mechanism behind the badge-engineering decision -- a rushed, top-down timing problem, not simply a lack of effort.",
      "summary": "GM's 1982 J-car platform was shared across five divisions (Chevrolet Cavalier, Pontiac J2000, Buick Skyhawk, Oldsmobile Firenza, Cadillac Cimarron). Cadillac joined the program late, and GM president Pete Estes reportedly warned Cadillac general manager Edward Kennard that there wasn't enough time to turn it into a real Cadillac.",
      "supporting_claim_ids": ["c2", "c3"],
      "unresolved_claim_ids": [],
      "narration_direction": "Use the Estes-to-Kennard warning (c2) as the pivot line, but flag it on screen as a widely repeated secondary account, not a primary transcript -- per c2's safe_wording, use 'reportedly.'",
      "visual_requests": [
        {
          "request_id": "V003",
          "beat_id": "b3_rushed_j_car",
          "subject": "1982 GM J-car siblings",
          "desired_asset_type": ["photo", "advertisement", "video"],
          "description": "Visual comparison showing the Cimarron alongside the other GM J-cars (Cavalier, J2000, Skyhawk, Firenza) to show how similar they were underneath.",
          "priority": "high",
          "exact_subject_required": true
        },
        {
          "request_id": "V004",
          "beat_id": "b3_rushed_j_car",
          "subject": "Early-1980s GM assembly line",
          "desired_asset_type": ["video", "contextual_video", "photo"],
          "description": "General GM/Detroit assembly-line footage or photos from the era to visualize the rushed production timeline; does not need to show the J-car specifically.",
          "priority": "medium",
          "exact_subject_required": false
        }
      ]
    },
    {
      "beat_id": "b4_what_you_got",
      "purpose": "Deliver the episode's factual core: what actually changed vs. what stayed the same, and what the real price gap was -- replacing any 'just badges and leather' or 'nearly double' shortcuts with defensible specifics.",
      "summary": "Cadillac did make genuine changes to the Cimarron -- standard air conditioning, extra sound insulation, alloy wheels, leather, full instrumentation, and Cadillac-specific suspension tuning -- but the platform, body, and initial engine stayed shared with the Cavalier. Against the cheapest base Cavalier coupe the price gap was close to double; against a comparably equipped Cavalier CL it was reportedly closer to a quarter more, though that second figure is not yet independently confirmed.",
      "supporting_claim_ids": ["c1", "c8", "c13", "d2"],
      "unresolved_claim_ids": ["c14", "d1"],
      "narration_direction": "This is the beat that has to get the numbers right. Use d2's safe_wording for the 'close to double' framing and explicitly name the comparator (cheapest base coupe). Only mention the smaller ~25%-over-a-comparable-CL figure (d1) as a reported-but-unconfirmed data point, per d1's safe_wording -- do not state it as settled. Reframe from 'it was just badges and leather' to 'Cadillac tried, but ran out of time to differentiate it enough' using c8.",
      "visual_requests": [
        {
          "request_id": "V005",
          "beat_id": "b4_what_you_got",
          "subject": "Cimarron and Cavalier CL interiors",
          "desired_asset_type": ["photo"],
          "description": "Matched interior/dashboard shots of a Cimarron and a Cavalier CL for a direct visual comparison.",
          "priority": "high",
          "exact_subject_required": true
        },
        {
          "request_id": "V006",
          "beat_id": "b4_what_you_got",
          "subject": "'Cimarron by Cadillac' badge",
          "desired_asset_type": ["photo"],
          "description": "Close-up of the 'Cimarron by Cadillac' script badge.",
          "priority": "medium",
          "exact_subject_required": true
        },
        {
          "request_id": "V007",
          "beat_id": "b4_what_you_got",
          "subject": "1982 Cimarron window sticker or price sheet",
          "desired_asset_type": ["document", "brochure"],
          "description": "A surviving window sticker, price sheet, or standard-equipment comparison chart, if one exists in the archive.",
          "priority": "low",
          "exact_subject_required": true
        }
      ]
    },
    {
      "beat_id": "b5_market_reaction",
      "purpose": "Correct the assumption that the Cimarron was mocked from day one -- show contemporary reception was mixed, distinct from its much harsher retrospective reputation.",
      "summary": "Contemporary reception in 1981-82 was genuinely mixed: Road & Track criticized the initial 1.8L engine's performance as 'painfully slow,' while Car and Driver's original review is reported to have been notably positive about Cadillac's strategic boldness (not yet independently confirmed verbatim). The much harsher, near-universal 'worst car' reputation is a retrospective judgment (see b7), not the immediate press consensus at launch.",
      "supporting_claim_ids": ["c10"],
      "unresolved_claim_ids": ["c9"],
      "narration_direction": "Explicitly separate two timelines: (a) contemporary 1981-82 reception -- real criticism of performance (c10, confirmed), reportedly some real praise for the concept (c9, unconfirmed) -- and (b) the retrospective reputation in b7. Do not quote c9's exact phrase; use its safe_wording hedge instead unless it gets confirmed before scripting.",
      "visual_requests": [
        {
          "request_id": "V008",
          "beat_id": "b5_market_reaction",
          "subject": "August 1981 Car and Driver issue",
          "desired_asset_type": ["magazine_scan", "photo"],
          "description": "Cover or article scan of the August 1981 Car and Driver issue containing the original Cimarron review.",
          "priority": "medium",
          "exact_subject_required": true
        },
        {
          "request_id": "V009",
          "beat_id": "b5_market_reaction",
          "subject": "Contemporary Road & Track Cimarron road test",
          "desired_asset_type": ["magazine_scan", "photo"],
          "description": "Scan or photo of the period Road & Track road test that recorded the 15.9-second 0-60 time.",
          "priority": "low",
          "exact_subject_required": true
        }
      ]
    },
    {
      "beat_id": "b6_slow_fix",
      "purpose": "Show real, ongoing engineering effort across the model run without a turnaround ending -- a slow chase for credibility, not redemption.",
      "summary": "Between 1983 and 1988 Cadillac kept revising the car: styling updates, a 2.0L engine in 1983, a 2.8L V6 added as an option in 1985 (standard by 1987), and suspension upgrades -- but annual production kept falling through the car's final years.",
      "supporting_claim_ids": ["c4", "c6"],
      "unresolved_claim_ids": [],
      "narration_direction": "Present the V6/equipment updates (c4) and the production decline (c6) together so the effort-without-payoff shape is clear. Do not editorialize the decline as 'collapsed' -- state the actual year-over-year numbers from c6.",
      "visual_requests": [
        {
          "request_id": "V010",
          "beat_id": "b6_slow_fix",
          "subject": "Cimarron styling across 1982, 1985, 1988",
          "desired_asset_type": ["photo"],
          "description": "Year-by-year exterior styling comparison shots.",
          "priority": "medium",
          "exact_subject_required": true
        },
        {
          "request_id": "V011",
          "beat_id": "b6_slow_fix",
          "subject": "Cimarron V6 engine bay",
          "desired_asset_type": ["photo"],
          "description": "Engine bay shot showing the 2.8L V6 added in 1985.",
          "priority": "low",
          "exact_subject_required": true
        }
      ]
    },
    {
      "beat_id": "b7_cancellation_legacy",
      "purpose": "Land the thesis: the car's real significance is retrospective -- a case study people inside and outside GM still reference -- distinct from how it was actually received when new (b5).",
      "summary": "Production ended in 1988 after roughly 132,499 total units (only 6,454 in the final year). In the decades since, the Cimarron has been named to lists like TIME's '50 Worst Cars of All Time' and is used as a standard example of badge engineering; former Cadillac product director John Howell reportedly kept a photo of a Cimarron in his office as a cautionary reminder.",
      "supporting_claim_ids": ["c5", "c7", "c12"],
      "unresolved_claim_ids": [],
      "narration_direction": "Explicitly mark c7 and the general 'worst car' reputation as retrospective (2007 onward), contrasting with b5's contemporary account. Use c12's 'reportedly' hedge rather than stating the Howell anecdote as flat fact.",
      "visual_requests": [
        {
          "request_id": "V012",
          "beat_id": "b7_cancellation_legacy",
          "subject": "'Worst cars' list reference",
          "desired_asset_type": ["photo", "document"],
          "description": "A shot or graphic referencing a 'worst cars' list cover/headline (e.g. the 2007 TIME piece).",
          "priority": "low",
          "exact_subject_required": false
        },
        {
          "request_id": "V013",
          "beat_id": "b7_cancellation_legacy",
          "subject": "Late-production (1988) Cadillac Cimarron",
          "desired_asset_type": ["photo"],
          "description": "A 1988 Cimarron for visual closure on the model run.",
          "priority": "low",
          "exact_subject_required": true
        }
      ]
    }
  ]
}
```

### asset_inventory.json

```json
{
  "episode_id": "ForeignCarsTH_cadillac-cimarron",
  "status": "pending",
  "assets": [],
  "request_coverage": []
}
```

### final_script.json

```json
{
  "episode_id": "ForeignCarsTH_cadillac-cimarron",
  "output_language": "th",
  "status": "pending",
  "blocks": []
}
```

### edit_plan.json

```json
{
  "episode_id": "ForeignCarsTH_cadillac-cimarron",
  "status": "pending",
  "clips": []
}
```

---

## 6. Inventory summary

### List of all files

```
CLAUDE.md
README.md
run_episode.py
agents/agent_a_producer_writer.md
agents/agent_b_archive_visual_editor.md
config/channels/ForeignCarsTH.json
schemas/episode_brief.json
schemas/fact_pack.json
schemas/producer_outline.json
schemas/asset_inventory.json
schemas/final_script.json
schemas/edit_plan.json
episodes/ForeignCarsTH_cadillac-cimarron/episode_brief.json
episodes/ForeignCarsTH_cadillac-cimarron/fact_pack.json
episodes/ForeignCarsTH_cadillac-cimarron/producer_outline.json
episodes/ForeignCarsTH_cadillac-cimarron/asset_inventory.json
episodes/ForeignCarsTH_cadillac-cimarron/final_script.json
episodes/ForeignCarsTH_cadillac-cimarron/edit_plan.json
```

18 tracked files total (not counting this report or `.git/`).

### Empty / stub files

No file in the repository is literally zero bytes. "Stub" here means: present,
schema-valid, but holding only placeholder/pending state with no substantive
episode content yet.

| File | State |
|---|---|
| `episodes/ForeignCarsTH_cadillac-cimarron/asset_inventory.json` | Stub — `status: "pending"`, `assets: []`, `request_coverage: []`. Agent B has not run. |
| `episodes/ForeignCarsTH_cadillac-cimarron/final_script.json` | Stub — `status: "pending"`, `blocks: []`. Agent A's A4 stage has not run (correctly blocked: the pipeline invariant forbids A4 until a real `asset_inventory.json` exists, and it doesn't yet). |
| `episodes/ForeignCarsTH_cadillac-cimarron/edit_plan.json` | Stub — `status: "pending"`, `clips: []`. Agent B's edit-planning stage has not run. |

These three being stubs is expected given the pipeline has only been run through
`fact_pack.json` and `producer_outline.json` for this example episode — it is not a
defect.

### Files with real content

| File | State |
|---|---|
| `CLAUDE.md`, `README.md` | Full project documentation. |
| `agents/agent_a_producer_writer.md`, `agents/agent_b_archive_visual_editor.md` | Full role specs. |
| `config/channels/ForeignCarsTH.json` | Fully populated channel config. |
| `run_episode.py` | Fully implemented `init` CLI command. |
| `schemas/episode_brief.json`, `schemas/fact_pack.json`, `schemas/producer_outline.json`, `schemas/asset_inventory.json`, `schemas/final_script.json`, `schemas/edit_plan.json` | Complete JSON Schema definitions. |
| `episodes/ForeignCarsTH_cadillac-cimarron/episode_brief.json` | Fully populated. |
| `episodes/ForeignCarsTH_cadillac-cimarron/fact_pack.json` | Fully populated — 17 claims (`status: "verified"`). |
| `episodes/ForeignCarsTH_cadillac-cimarron/producer_outline.json` | Fully populated — thesis, hook, 7 beats, 13 visual requests (`status: "drafted"`). |

### Schema validation errors

**None.** All six example-episode files were validated against their corresponding
schema with `jsonschema.validate()` at the time this report was generated:

```
VALID   episodes/ForeignCarsTH_cadillac-cimarron/episode_brief.json
VALID   episodes/ForeignCarsTH_cadillac-cimarron/fact_pack.json
VALID   episodes/ForeignCarsTH_cadillac-cimarron/producer_outline.json
VALID   episodes/ForeignCarsTH_cadillac-cimarron/asset_inventory.json
VALID   episodes/ForeignCarsTH_cadillac-cimarron/final_script.json
VALID   episodes/ForeignCarsTH_cadillac-cimarron/edit_plan.json
```

All six `schemas/*.json` files also pass `jsonschema.Draft7Validator.check_schema()`
(i.e. each is itself a structurally valid JSON Schema draft-07 document).

Additional cross-file reference checks (not expressible in JSON Schema alone, so run
separately) also passed:
- No duplicate `claim_id` values in `fact_pack.json`.
- Every `supporting_claim_ids` entry in `producer_outline.json` resolves to a
  `fact_pack.json` claim with `allowed_in_narration: true`.
- Every `unresolved_claim_ids` entry resolves to a claim that exists and has
  `allowed_in_narration: false`.
- All 13 `visual_requests[].request_id` values across the outline are unique.
- Both `derived_comparison` claims' `calculation` strings evaluate to the numbers
  stated in their `result` fields (`d1` ≈ 24.9%, `d2` ≈ 83.8%).

### TODOs / inconsistencies noticed

1. **`b6_slow_fix` summary asserts two details with no supporting `fact_pack.json`
   claim.** Its `summary` and `narration_direction` mention "a 2.0L engine in 1983"
   and "suspension upgrades" (the pre-refactor draft of this outline referenced an
   optional Bilstein/touring suspension package), but `fact_pack.json` contains no
   claim for either — `supporting_claim_ids` for this beat is only `["c4", "c6"]`
   (the V6 update and the production decline). This is a real gap against the
   project's own stated invariant ("producer_outline.json... must not introduce
   factual claims that do not exist in the fact pack"). Fix: either add fact_pack
   claims for the 1983 2.0L engine and the suspension-package upgrades (with
   sources), or trim those two details out of the beat's summary/narration_direction.

2. **`b2_cadillacs_problem` summary asserts unsourced context.** "Cadillac's buyer
   base was aging" and "fuel-economy/downsizing pressure was real" are stated as
   background fact but have no corresponding `fact_pack.json` claim_id in
   `supporting_claim_ids` (only `c11`, the competitive-set claim, is cited). This is
   milder than #1 — it reads as scene-setting rather than a specific factual
   assertion — but under a strict reading of the evidence-before-narrative invariant
   it should either be cited or softened to a framing device rather than a claim.

3. **Two claims are the episode's known weak points and are explicitly gated off
   from narration**, by design: `c14` (comparably-equipped Cavalier CL pricing) and
   `c9` (the Car and Driver "boldest moves" quote) are both `source_classification:
   "reference_only"`, `confidence: "unresolved"`, `allowed_in_narration: false` —
   because their only source returned HTTP 403 on direct fetch during research and
   was only available via a search-engine summary. The derived claim `d1` (the
   ~24.9% Cavalier CL price premium) is consequently also gated off, since it
   depends on `c14`. `c15` (Audi 4000 / Honda Accord competitive framing) is
   similarly unresolved for the same reason (search-summary only, page not
   independently fetched). None of these are inconsistencies in the data — they are
   correctly flagged as unresolved — but they are the concrete blockers standing
   between the current fact pack and a fully-sourced final script, and are called
   out here since they're the most consequential open TODOs in the project.

4. **`producer_outline.json`'s optional `open_questions` array (defined in
   `schemas/producer_outline.json`) is omitted from the current episode file.** The
   outline-level uncertainty that would belong there (e.g. "should the ~25% vs.
   ~84% price-premium framing in b4 be resolved before scripting?") currently lives
   only inside individual `fact_pack.json` claim `notes` fields. Not a schema
   violation (the field is optional), but a minor structural inconsistency worth
   noting: nothing at the outline level currently surfaces "c14 is the top research
   priority" as an actionable item the way a populated `open_questions` array would.

5. **No episode has been taken past `producer_outline.json`.** `asset_inventory.json`,
   `final_script.json`, and `edit_plan.json` are all empty stubs for the only
   example episode in the repo, so the `request_coverage` mechanism, the
   `supporting_claim_ids`-on-script-blocks mechanism, and the renamed
   `edit_plan.json` `block_id` field (renamed from the pre-refactor `scene_id`) have
   not yet been exercised against real data — only validated structurally via the
   CLI's stub output and schema checks. This is expected given the project's
   explicit instruction to stop after the architecture refactor, not a defect, but
   it means the new `asset_inventory.json` / `final_script.json` / `edit_plan.json`
   contracts are currently untested against a real Agent B / A4 / edit-planning run.

6. **`README.md` was not part of this inspection's required "full contents" list**
   (the request named `CLAUDE.md`, the two agent specs, and the channel config only)
   but does exist in the repo and is listed in the file inventory above for
   completeness; its content is not reproduced in Section 2.
