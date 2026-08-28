# CEOPRO AI — Engineering Plan (AI/ML Track)

**Owner:** AI/ML Engineering
**Status of this document:** closes the "will provide later" gap `PENDING_ACTIONS.md` #11 flagged —
`AI_ENGINEERING_PLAN.md` was referenced by `AI_PLAN_AND_CONTRACT_UPDATES.md` and `AI_CONTRACT_CHANGES_AND_CLARIFICATIONS.md`
but never existed in this repo until 2026-08-26. **Revalidated and rewritten 2026-08-28** against the
schema and code actually on `main` today, superseding the original 2026-08-26 draft rather than just
annotating it — the draft was written against a schema (`init_schema.sql`, called "Version A" below at
the time) that has since been formally retired; every section below reflects `Final_schema.sql` (26
tables) and the modules as reworked against it, cross-checked line-by-line against live-DB test runs,
not re-derived from the spec alone. Historical note, kept for the record: the original draft framed
the 21-table/26-table schema fork as a still-open decision — that decision was made 2026-08-27
(`Final_schema.sql` adopted as canonical, `PENDING_ACTIONS.md` #27) after this document was first
written, which is why a rewrite was needed rather than a patch.
**Grounded in:** `MASTER_SPEC_v4.md` (the real spec), `AI_PLAN_AND_CONTRACT_UPDATES.md`'s precedence
rule, the actual current state of `src/ai/` (`AI_PROGRESS.md`'s Module status table and its five
2026-08-27 entries), `Final_schema.sql` itself, and open items in `PENDING_ACTIONS.md`/`RED_FLAGS.md`.
Nothing in this document is invented outputs, KPIs, or architecture that don't trace to one of those
sources or to code that actually exists and has been run against a real database.

**Explicit exclusions (per instruction):** this document does not cover Demand Forecasting
(`src/ai/forecasting/`, spec §18) or "AI Advisor." The latter term doesn't appear anywhere in
`MASTER_SPEC_v4.md`, `AI_PLAN_AND_CONTRACT_UPDATES.md`, `AI_PROGRESS.md`, or `PENDING_ACTIONS.md` —
it isn't a defined module in this repo. Since spec §21's RAG Chatbot *is* separately and explicitly
in scope below (item 11 of the originating task list asks for RAG architecture), "AI Advisor" is
treated here as a distinct, not-yet-specified feature and nothing is built or written under that name.
If it refers to something specific, flag it and this document gets a follow-up entry.

**Schema basis:** `Final_schema.sql` (26 tables), adopted as canonical 2026-08-27
(`PENDING_ACTIONS.md` #27) and confirmed by the project owner directly. Every module in scope below
has been reworked against it and verified with a live-DB integration suite (49 tests passing against
a real disposable Postgres, `AI_PROGRESS.md`'s 2026-08-27/2026-08-28 entries) — this section is a
genuine re-validation, not a restatement of what the code was originally built against.

---

## 1. Functional Requirements & MVP AI Outputs

Per spec §3 (System Definition), the platform transforms raw data into structured business
information, market/competitor intelligence, sentiment analysis, pricing insights, business
recommendations, and explainable alerts — exposed through a dashboard, chatbot, alerts, and reports.
Every output is typed as one of five categories the system must never blur (spec §3, §22):
**FACT** (directly retrieved), **PREDICTION** (model output), **RECOMMENDATION** (rule/data-driven
suggestion), **ASSUMPTION** (explicitly labeled), or **UNKNOWN** (system doesn't currently know) —
*"the system must never present a prediction as a confirmed fact."*

MVP AI outputs actually implemented and tested today (excluding Demand Forecasting):

| Output | Module | Evidence category | Status |
|---|---|---|---|
| Price-change + margin recommendation | `pricing/` | RECOMMENDATION (or UNKNOWN if no competitor match) | 🟢 Built, tested |
| Per-subject sentiment summary (score + label breakdown) | `sentiment/` | FACT (or UNKNOWN) | 🟢 Built, tested |
| Market Perception Index (0–100, per subject) | `mpi/` | FACT (or UNKNOWN) | 🟢 Built, tested |
| Extracted structured entities (MONEY/DATE/PRODUCT/COMPETITOR/…) from raw text | `extraction/` | *(bulk annotation — see item 9)* | 🟢 Built, tested |
| Hybrid (lexical + semantic) document retrieval | `rag/` | *(retrieval only — no chatbot answer yet)* | 🟡 Retrieval built; LLM reasoning step not started |

Not an MVP output yet: a chatbot **answer** (spec §21's full pipeline ends in an LLM-reasoned,
validated final answer — `rag/` today stops at ranked chunks, see item 11) and Competitor Ranking
(spec §20, Phase 6 — ⚪ not started, blocked on the same missing scraper data as `pricing/`,
`PENDING_ACTIONS.md` #5).

## 2. Use Cases & Expected Business Value

Grounded in what's actually built and what spec §3 states the platform is for — a multi-country SMB
BI platform, not a generic analytics tool:

- **"Is my price competitive, and can I raise it without losing margin?"** — `pricing/` compares a
  tenant's price against matched same-currency competitors, bounds any suggested change against both
  a price-change guardrail and (once `products.cost_price` is set) a margin floor, and traces every
  suggestion back to the competitor rows that justified it. Business value: fewer manual price checks,
  a documented reason for every price change (spec §27 explainability).
- **"What do customers actually think of this product vs. the competitor's?"** — `sentiment/` +
  `mpi/` turn raw review text (Arabic, English, or mixed — spec §8) into a single comparable index per
  product/competitor/business, with a LOW SAMPLE SIZE flag instead of a false-confidence number when
  data is thin (spec §16, §23). Business value: a non-technical owner gets one number instead of
  reading fifty reviews.
- **"What's actually in this pile of news/social mentions about my market?"** — `extraction/` turns
  unstructured `news_record`/`social_mention` text into structured `MONEY`/`DISCOUNT`/`PRODUCT`/
  `COMPETITOR` entities a downstream dashboard or the future chatbot can query directly instead of
  re-reading raw text every time.
- **"Answer a question about my own business, in my own language, with sources."** — `rag/`'s
  retrieval half (spec §21) is the foundation; the reasoning/answer half is item 11 below.

## 3. Required Business, Operational, and Knowledge Data Sources

Per `src/infrastructure/DATA_OWNERSHIP_AND_CONTRACTS.md`'s ownership matrix and spec §12:

| Category | Tables | Owner | Real data status |
|---|---|---|---|
| Business (core) | `companies`, `products`, `inventory` | Backend/platform | ✅ Real, ingested via Phase 1 |
| Business (core) — **gap** | `transactions` | Backend/platform | 🔴 Table doesn't exist in `Final_schema.sql` at all — confirmed against all 26 `CREATE TABLE` statements. This isn't a data gap, it's a schema gap: `forecasting/data_access.py::load_daily_demand()` reads from it and cannot run against the current canonical schema. Tracked in `PENDING_ACTIONS.md` #31, needs an explicit decision (extend the schema to bring it back, or rework `forecasting/` onto `invoices`/`invoice_items` instead) — out of this document's scope (Demand Forecasting is explicitly excluded above), but too significant not to name here since section 3 would otherwise silently misstate it as ready. |
| Operational — pricing | `global_competitors`, `tenant_competitors`, `competitor_product_mappings`, `competitor_prices` | AI Market Scraper Service (named, not built) | 🔴 Empty (`PENDING_ACTIONS.md` #5). Table shape changed from the original draft: competitors are no longer a single flat table — a global catalog (`global_competitors`) a tenant opts into tracking (`tenant_competitors`), mapped to a specific product (`competitor_product_mappings`) before a `competitor_prices` row can reference it. |
| Operational — sentiment | `reviews` | Unassigned — no owner in the contract matrix at all | 🔴 Empty (`PENDING_ACTIONS.md` #18) |
| Operational — market intel | `news_record`, `social_mention` | Same gap as `reviews` — no named owner | 🔴 Empty |
| Knowledge | `rag_documents_metadata` + MinIO `ceopro-rag-knowledge` | Tenant-uploaded (backend) | 🟡 Seed data only |
| Reference | `currency_rates` | Infra/DB | ✅ Real, landed and wired |

Every module downstream of the 🔴 rows currently runs its cold-start/`UNKNOWN` path in production —
not a bug, the correct spec-mandated behavior (§23), but it means the MVP has never been validated
against non-trivial real data end-to-end. Item 12 addresses this for the AI/ML track's own seed data
(not a substitute for the real connectors these rows actually need).

## 4. AI Data Requirements, Quality Rules, and Minimum Data Thresholds

Spec §13's Collection Policy Engine classifies every external source `ALLOWED`/`RESTRICTED`/`BLOCKED`
— already implemented as `reviews.source_status`/`competitor_prices.source_status`, and every
`data_access.py` in `src/ai/` filters to `ALLOWED` only. Spec §13 also states the platform *"must
continue functioning if all social media data becomes unavailable"* and must not depend on it for
demand forecasting, ranking, sentiment, or market intelligence — reflected in every module's
`UNKNOWN`/cold-start fallback rather than a hard failure when a source is empty.

Minimum thresholds already implemented (spec §23's shared cold-start policy, one instance per
module rather than reinvented per module):

| Module | Threshold | Below it |
|---|---|---|
| `sentiment/cold_start.py` | `SENTIMENT_MIN_SAMPLE_SIZE` (default 10 analyzed reviews) | `LOW_SAMPLE_SIZE` status, score still computed but flagged |
| `mpi/cold_start.py` | Same 10-review floor, layered on `scoring.py`'s continuous volume dampening | `LOW_SAMPLE_SIZE` label + dampened-toward-50 score |
| `mpi/scoring.py` (`compare_mpi_results`) | `MPI_MIN_VOLUME_FOR_FULL_CONFIDENCE` (default 20) per side | Refuses to return *any* numeric comparison, not a low-confidence one |
| `pricing/` | At least one matched same-currency competitor | `UNKNOWN` evidence, no recommendation |
| `extraction/` | None (deterministic regex/rule matching, no sample-size concept) | N/A — always runs, may return zero entities |

Personal data (spec §14): not yet audited against every table this track reads — `reviews.review_text`
and `news_record`/`social_mention` text fields are free text that could contain names/contact info
captured incidentally; no redaction step exists in `extraction/` or `sentiment/` today. **Flagged as
a follow-up, not fixed in this document.**

## 5. AI Success Metrics, KPIs, and MVP Acceptance Criteria

Spec §25 defines the evaluation protocol per model family. Applied to what's in scope here:

| Module | Spec §25 metrics | Currently measured how |
|---|---|---|
| NER (`extraction/`) | Precision, Recall, Entity F1 | Not yet — no labeled entity gold-set exists; tests assert exact-match on synthetic cases only |
| Sentiment (`sentiment/`) | Accuracy, Macro F1, Confusion Matrix, Calibration | **Tooling ready, still no labeled data** (2026-08-28) — `sentiment/finetune.py::evaluate_only()` computes Accuracy/Macro F1/Confusion Matrix against any labeled CSV, verified end-to-end against the real production model; Calibration still needs a separate reliability-diagram/ECE computation, not yet built. `test_sentiment_model_real.py` still only checks known-clear-cases classify correctly — `evaluate_only()` is what actually closes this gap, the moment a real labeled set exists |
| Retrieval (`rag/`) | Recall@K, Precision@K, MRR, NDCG | Not yet — `test_rag_integration.py` checks the right chunk ranks first on a small synthetic corpus, not a formal IR benchmark |
| Chatbot | Groundedness, Citation correctness, Answer relevance, Hallucination rate | N/A — chatbot doesn't exist yet (item 11) |
| Pricing | Realized demand, Margin impact, Recommendation accuracy, Constraint violation rate | Partially — guardrail *constraint violation rate* is effectively 0 by construction (guardrails are hard bounds, not learned); the other three need real transaction data post-recommendation, which doesn't exist yet |

**Honest MVP acceptance criteria for this track today** (spec §25's formal metrics need real/labeled
data this repo doesn't have yet — see the gaps above): a module is "MVP-acceptable" when (a) it's
built and offline-tested, (b) verified against a real disposable Postgres, not just mocks, (c) every
output it writes is traceable through `evidence_records`' `source_record_ids` back to the rows that
produced it (spec §22), and (d) it degrades to `UNKNOWN`/`LOW_SAMPLE_SIZE` rather than a wrong or
overconfident answer when data is thin (spec §23). By that bar: `pricing/`, `sentiment/`, `mpi/`,
`extraction/` all pass; `rag/` passes for retrieval, not yet applicable for chat answers.

Closing the §25 formal-metrics gap needs a labeled evaluation set per model family (spec §7 also
requires one specifically for LLM/dialect selection before item 10 can be "finalized" in the full
sense) — this is real, separate work, not something this document fabricates numbers for.

## 6. AI Data Availability, Access Permissions, and Integration Readiness

Access: `src/ai/` reads via `psycopg2` connections. The RLS/role situation is more nuanced than a
single resolved/unresolved status, and worth stating precisely rather than glossing over:

- A non-superuser `ceopro_app` role exists (`migrations/20260827000200_add_app_role.sql`), with its
  password synced out-of-band from `APP_DB_PASSWORD`.
- Its RLS policies are now genuinely correct and verified end-to-end (`PENDING_ACTIONS.md` #32) —
  `get_current_tenant()` (every policy's tenant check) had an infinite-recursion bug that would have
  crashed on first real use under a non-superuser role; fixed and covered by 11 permanent regression
  tests connecting as `ceopro_app` for real.
- **But nothing actually connects as `ceopro_app` yet.** Every DB-touching codepath that exists
  today — `docker-compose.yml`'s only service definition that sets `DATABASE_URL`
  (`migrate`, correctly using the superuser for migrations) plus any `src/ai/` code reading that same
  env var — authenticates as `ceopro_admin`, a genuine Postgres superuser that unconditionally
  bypasses RLS regardless of policy correctness. No code anywhere calls `SET`/`set_config` for
  `app.current_tenant_id`/`app.current_user_id`. In practice, RLS provides **zero** isolation in the
  currently-deployed system, not because the policies are wrong (they're now fixed and tested) but
  because of which role actually connects (`PENDING_ACTIONS.md` #2, `RED_FLAGS.md`'s 🔴 Critical
  section). Closing this needs a real service that connects as `ceopro_app` and sets that session
  context per request — there is no `ai`/`backend` service in `docker-compose.yml` yet at all
  (`PENDING_ACTIONS.md` #8) — not a schema or policy change.

No `src/ai/` code currently constructs its own MinIO client for `rag/` — callers must inject one
(established convention, see `src/ai/README.md`).

Integration readiness by source, restating item 3 with an explicit readiness verdict:

- `products`/`inventory` — ✅ ready, real data flowing since Phase 1.
- `transactions` — 🔴 not ready, and not just a data gap: the table doesn't exist in `Final_schema.sql`
  at all (see item 3). Blocks Demand Forecasting entirely, though that module is out of this
  document's scope.
- `competitor_prices` — 🔴 not ready. Table and RLS policy exist; no producer. Blocks Phase 5's
  recommendation path and all of Phase 6 (Competitor Ranking).
- `reviews` — 🔴 not ready. Same situation, and per item 3, no owner is even assigned yet.
- `news_record`/`social_mention` — 🔴 not ready, same gap.
- `rag_documents_metadata` + MinIO — 🟡 ready mechanically (ingestion pipeline built and tested), but
  depends on tenants actually uploading documents; nothing seeds this in production either.

Net: of the five modules in scope for this document, **two (`pricing/`, and half of Phase 4) are
integration-ready in code but not in data.** This is the single largest gap between "built" and
"delivering real business value" for this track right now — not a code problem. Separately, the RLS
gap above means even the modules that *are* data-ready aren't yet running behind real tenant
isolation in production — a security posture gap, not a data or code-correctness one.

## 7. Database Schema Validation Against AI Inputs, Outputs, and Traceability

Validated against `Final_schema.sql` (26 tables), the now-canonical schema — not the original draft's
Version A, and not by re-reading the SQL alone: every claim below is confirmed by a live-DB
integration suite actually running against a real disposable Postgres with this exact schema and its
11 migrations applied (`AI_PROGRESS.md`'s 2026-08-27/2026-08-28 entries; 49 live-DB tests passing).

- **Reads:** `products` (note: `product_name` is JSONB, multilingual — every `data_access.py` was
  reworked for this), `global_competitors`/`tenant_competitors`/`competitor_product_mappings` (the
  competitor model was restructured from a single flat table into this three-table shape — a
  tenant-scoped mapping, not a rename), `competitor_prices`, `reviews` (restored `subject_type`/
  `source_status`/`competitor_id` columns the schema fork had dropped), `news_record`,
  `social_mention`, `currency_rates` (column names changed: `from_currency`/`to_currency`/
  `exchange_rate`/`last_fetched`, one row per currency pair rather than a history), `rag_documents_metadata`
  — all present, columns match what every `data_access.py` in `src/ai/` queries.
- **Writes (this track's owned tables per `DATA_OWNERSHIP_AND_CONTRACTS.md`):** `evidence_records`,
  `sentiment_results`, `extracted_entity`, `recommendation_outcomes` — present, correct FKs
  (`tenant_id → companies`, category-specific FKs like `sentiment_results.review_id → reviews`), all
  following `Final_schema.sql`'s own tenant-isolated composite-FK convention (a
  `UNIQUE(tenant_id, X)` perimeter constraint backing every cross-table FK, so a join can't silently
  cross tenants even before Row-Level Security is considered).
- **`evidence_records` needed a real schema fix, not just validation**: as originally defined in
  `Final_schema.sql` it was forecast-only (`forecast_id UUID NOT NULL`, no general-purpose columns) —
  structurally impossible for `pricing/`/`sentiment/`/`mpi/`/`extraction/` to write to, breaking
  spec §22's "one consistent evidence architecture" requirement outright. Fixed by extending the table
  (`forecast_id` made nullable, `category`/`source_module`/`explanation_text`/etc. added back, a
  `chk_evidence_shape` constraint requires one shape or the other, never a half-empty row) rather than
  forking a second evidence table. `PENDING_ACTIONS.md` #28.
- **Traceability (spec §22):** every `evidence_records` row this track writes carries
  `source_record_ids` (JSONB) pointing back to the specific rows that produced it — verified in
  integration tests, not just asserted in code.
- **Row-Level Security, part of the traceability/isolation guarantee, not a separate concern:** every
  tenant-scoped table has `FORCE ROW LEVEL SECURITY` plus a policy keyed on `get_current_tenant()`.
  That function itself had a real bug — infinite recursion under a non-superuser role, since fixed
  and verified (`PENDING_ACTIONS.md` #32) — but see item 6 above: the policies being correct doesn't
  mean isolation is active in production yet, since nothing currently connects as the restricted role.
- **Confirmed gaps, not hypothetical ones:** `model_versions` — the table Demand Forecasting's own
  artifact tracking needs — **does not exist in `Final_schema.sql`**, confirmed directly (not "a risk
  if adopted" — it *is* adopted, and the table genuinely isn't there). Same situation as `transactions`
  (item 3): both are real, structural gaps for the excluded Demand Forecasting module, not something
  this document's in-scope modules hit. `products.cost` from the original draft is `products.cost_price`
  in `Final_schema.sql` — present, and `pricing/guardrails.py`'s margin guardrail already uses it.

Every input/output/traceability need for the five modules actually in scope here is met by
`Final_schema.sql` as it stands today, after the `evidence_records` extension above — that extension
was the one schema change this validation required, and it's already landed and tested, not still
open.

## 8. MVP AI Architecture & Component Interfaces

Every built module (`forecasting/` excluded from detail, but it set the pattern every later module
copied) follows the same internal shape — a deliberate convention, not five independent designs:

```
data_access.py   → reads pre-existing tables this track doesn't own, ALLOWED-source-filtered
      ↓
(business logic: matching.py / scoring.py / model.py — pure functions, no DB access, fully unit-testable)
      ↓
evidence.py      → writes only to this track's own tables (evidence_records + one module-specific table)
      ↓
pipeline.py      → orchestrates: load → cold-start check → compute → guardrail/policy → persist
```

Component interface convention: every `pipeline.py` entry point takes `(conn, tenant_id, ...)` and
either returns a result dict (`{"status": ..., ...}`) or persists directly and returns an id/count —
never both a live DB write and an unrelated side effect in the same call. `conn` is always injected
by the caller (a consumer, a test, or a future API layer) — no module opens its own connection except
`forecasting/consumer.py` (excluded).

**Correction from the original draft:** an earlier version of this document described a
`src/ai/db.py::set_tenant_context()` helper as the established RLS-context call site,
called from `forecasting/consumer.py`. That file was never actually merged to `main` — it only ever
existed on the since-closed PR #15, and `forecasting/consumer.py` as it stands today calls no such
function (confirmed directly: zero references to `set_tenant_context`/`set_config`/
`app.current_tenant_id` anywhere in that file). This document should not have stated it as built —
see item 6 above for the accurate, current state: no code anywhere in `src/ai/` sets RLS session
context today. PR #15's version of that helper is recorded as a starting point in
`PENDING_ACTIONS.md` #2, not as something already in place.

Cross-cutting components, corrected against the actual current code (a claim worth verifying
precisely, not assuming, given the pattern of stale claims already found and fixed elsewhere in this
document):
- **Only `pricing/` actually reuses `forecasting/evidence.py::insert_evidence_record()` directly**
  (`from src.ai.forecasting.evidence import insert_evidence_record`, re-exported for its own callers).
  `sentiment/evidence.py` and `mpi/evidence.py` each define their **own** `insert_evidence_record()` —
  parallel implementations following the same shape (same columns, same `chk_evidence_shape`
  constraint satisfied the same way), not literal code reuse. `extraction/evidence.py` writes through
  `insert_extracted_entities()` instead — a genuinely different shape (one call writes many entity
  rows, not one evidence summary), not a variant of the same function at all.
- What *is* genuinely shared, per spec §22/§23's "one consistent" requirement, is the **shape**
  every evidence write follows (the same columns, the same `chk_evidence_shape`-satisfying pattern,
  the same `source_record_ids` traceability convention) — not one single reused function across all
  five modules. Worth finalizing as literal shared code, not just a shared shape, if that consistency
  is meant to be structurally enforced rather than convention-enforced.
- Cold-start policy — each module has its own `cold_start.py`, but all follow the same
  continuous-score-plus-discrete-flag shape established first in `sentiment/`.

## 9. AI Orchestration, Model Invocation, and Service Communication Flow

Per spec §12, ingestion is connector-based and event-driven; per `DATA_OWNERSHIP_AND_CONTRACTS.md`,
Redis Streams (`ceopro:stream:*`) is the established inter-service transport. Current state:

| Module | Trigger today | Spec-intended trigger |
|---|---|---|
| `forecasting/` *(excluded from this doc, noted for context only)* | `consumer.py`, real Redis Streams consumer (`demand_forecast_requested`) | Same — this is the only module with its contract actually implemented |
| `pricing/` | Called directly (no consumer) | No `ceopro:stream:*` topic provisioned yet for it in `src/infrastructure/init_broker.py` |
| `sentiment/` | Called directly | Same gap |
| `mpi/` | Called directly | Same gap |
| `extraction/` | Called directly | Same gap |
| `rag/` (ingestion) | Called directly (`ingest_pending_documents()`) | Same gap |

**This is the concrete orchestration gap to close** for a real MVP: four modules' worth of event
contracts (topic name, payload shape, consumer group) aren't defined anywhere yet. Proposed shape,
mirroring `forecasting/consumer.py`'s already-proven pattern (one persistent connection opened in
`listen()`, `xreadgroup`/`xack` ack-after-success) — **plus** the RLS session-context call that
pattern is still missing today (item 6: `forecasting/consumer.py` itself sets no
`app.current_tenant_id`/`app.current_user_id` currently, confirmed directly — any new consumer built
from this pattern should add that call, not copy its absence):

| Proposed topic | Payload | Triggers |
|---|---|---|
| `ceopro:stream:sentiment_analysis_requested` | `{tenant_id, subject_type, subject_id}` | `sentiment/pipeline.py::get_subject_sentiment_summary()` |
| `ceopro:stream:mpi_computation_requested` | `{tenant_id, subject_type, subject_id}` | `mpi/pipeline.py::get_subject_mpi()` |
| `ceopro:stream:price_recommendation_requested` | `{tenant_id, product_id}` | `pricing/pipeline.py::run_price_recommendation()` |
| `ceopro:stream:entity_extraction_requested` | `{tenant_id}` (batch, not per-record — extraction already processes all 'Pending' rows per call) | `extraction/pipeline.py::extract_and_store_*()` |

Not implemented in this document — `src/infrastructure/init_broker.py` provisioning these topics is
an infra-track change (this track's established boundary, per `src/ai/README.md`'s own scope
statement), and building four new consumer classes is real, separate implementation work, not a
planning-doc line item.

## 10. LLM and Core AI Model Approach for the MVP (excluding Demand Forecasting and AI Advisor)

Spec §5 (Zero-Mandatory-Paid-Cost) and §7 (Local LLM Strategy) jointly constrain every model choice
in this track: open-weight, locally runnable, no mandatory paid API. Every model actually in use
today already satisfies this — confirmed, not assumed:

| Component | Model | License/cost | Status |
|---|---|---|---|
| Sentiment classifier | `cardiffnlp/twitter-xlm-roberta-base-sentiment` | Open weight, free | 🟢 In production use, spec §16's own suggested model |
| RAG embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (`RAG_EMBEDDING_MODEL`-configurable) | Open weight, free | 🟢 In production use |
| RAG chat reasoning LLM | *(none selected yet)* | — | 🔴 Not started — this is the actual open item |

Spec §7's own required process before "finalizing" an LLM choice: build a small Arabic/English/
code-switching/dialect evaluation set, test candidate models (Llama, Mistral, Qwen, or Aya family)
against it for understanding, business reasoning, and hallucination behavior — *"the project team
must NOT train an LLM from scratch"* and this evaluation set is for *selection*, not training. This
evaluation set does not exist in this repo yet; it is a prerequisite for a real recommendation, not
something this document can responsibly invent. **Recommendation for the evaluation shortlist**,
given the constraints already established elsewhere in this codebase (CPU-only — confirmed
`PENDING_ACTIONS.md` #13, "confirmed CPU-only / no GPU 'for now'"): a quantized (GGUF, CPU-inferable)
small-to-medium Qwen2.5 or Llama-3.1 variant — both have strong published Arabic/English bilingual
benchmarks and widely-available CPU-quantized builds; final selection still needs the evaluation set
run, per spec §7's explicit process, before this line can move from "recommended" to "finalized."

Spec §7's fallback architecture is directly relevant to `rag/`'s current state: *"If a local LLM
produces unreliable factual explanations, the system must use... DATABASE FACTS + MODEL PREDICTIONS +
RULE-BASED EXPLANATION TEMPLATES + OPTIONAL LLM LANGUAGE POLISHING. The LLM must not be the source of
business facts."* Every module in this track already does exactly this *without* an LLM in the loop —
`explanation_text` in every `evidence_records` write is a rule-based template, not model-generated.
The LLM's role, once selected, is strictly the reasoning/polishing layer on top of retrieval — never
the source of the facts it reasons over. This is a real architectural constraint already satisfied by
existing code, not a new decision.

## 11. RAG Retrieval Architecture & Vector-Search Implementation Approach

Spec §21's full pipeline: query normalization → intent classification → language detection → country
context → entity extraction → date/filter extraction → (structured DB query + BM25 + FAISS in
parallel) → result fusion → optional reranking → context assembly → LLM reasoning → validation →
final answer.

**Built and tested today** (retrieval half only):
- `chunking.py` — word-boundary overlapping windows, language-agnostic (works for Arabic/English
  code-switching without a language-specific tokenizer, spec §8).
- `bm25_index.py` — in-memory lexical index, **BM25Plus** specifically (not the more common Okapi —
  Okapi's IDF formula zeroes out matches for terms appearing in exactly half a small corpus, a
  realistic cold-start case for a tenant with 2-3 documents; found via live-MinIO testing).
- `faiss_index.py` — exact flat search (corpus sizes here don't warrant approximate search),
  L2-normalized embeddings so inner product = cosine similarity.
- `hybrid_retrieval.py` — Reciprocal Rank Fusion combining BM25 + FAISS, unweighted. One documented,
  unfixed limitation: with very short chunks and only one genuine keyword match, BM25's length
  normalization can occasionally outrank a real match — inherent behavior, not a bug, documented in
  `test_rag_integration.py`.

**Vector-search implementation detail worth finalizing explicitly:** retrieval today rebuilds the
FAISS index from scratch on every call, fetching and re-chunking/re-embedding every document from
MinIO each time — correct, but doesn't scale past a small per-tenant document count (`src/ai/README.md`
already flags this as "a concrete argument for the pgvector ask," not a workaround). `rag_document_chunks`
(the persistence table) exists in `Final_schema.sql`, but its `embedding` column and the `vector`
Postgres extension didn't — a real gap found and fixed during the schema-fork rework (added via
`migrations/20260827000100_add_rag_embedding_column.sql`, sized at 384 dimensions, confirmed
empirically against the actual production embedding model rather than assumed). The column existing
now doesn't close this item, though — `rag/pipeline.py` still doesn't write to it; chunks/embeddings
are still computed in-memory only on every call. **Recommended approach to finalize:**
persist chunks + embeddings to `rag_document_chunks` on ingestion (`ingest_pending_documents()`),
switch `build_hybrid_index()`/`retrieve_hybrid()` to read from there instead of recomputing from
MinIO on every call, keep FAISS in-memory as the actual search structure (Postgres/pgvector as the
durable store, not necessarily the query-time engine) — avoids a full re-embed per query without
requiring pgvector's own ANN search to replace FAISS's already-tested exact search.

**Not built, and the actual gap to close for a working chatbot**: intent classification, language
detection as a distinct step (embeddings are multilingual, but no explicit language-tagging exists),
country-context detection, entity extraction integration into the retrieval query itself (extraction/
exists but isn't wired into rag/'s query path), the LLM reasoning step (blocked on item 10), and
answer validation. None of this is implementable without item 10's LLM decision landing first.

## 12. AI Development Dataset

**Correction from the original draft:** it described `seed_demo_data.py` as extended to seed
`competitors`/`competitor_prices`/`reviews`/`news_record`/`social_mention`. That extension was written
on PR #15, which was never merged (only this document was extracted from it, `PENDING_ACTIONS.md`
#12) — the actual `seed_demo_data.py` on `main` today is unchanged from before the schema-fork
rework: it seeds `companies`/`users`/`products`/`inventory`/`transactions`/`demand_forecasts`/
`currency_rates`/`rag_documents_metadata`/`rag_document_chunks` only. None of `pricing/`'s,
`sentiment/`'s, `mpi/`'s, or `extraction/`'s own tables (`competitor_prices`, `reviews`, `news_record`,
`social_mention`) get seeded at all, and — separately, confirmed directly — **this seeder would crash
against `Final_schema.sql` today**: it `INSERT`s into `transactions`, a table that doesn't exist in
the canonical schema at all (item 3/7's already-tracked gap). This isn't a new problem this document
introduces, but the original draft's claim that the extension existed and just needed validation was
inaccurate — the honest state is: the seeder is stale, untouched by the schema-fork rework (it's an
infra file, outside this track's boundary, `src/ai/README.md`), and doesn't cover this track's own
data needs even before considering whether it runs at all. Extending and fixing it is real, separate
work, correctly scoped to whoever owns `seed_demo_data.py` per `PENDING_ACTIONS.md`'s convention, not
something to claim as done in a planning document.

Each of this track's four in-scope modules (`pricing/`, `sentiment/`, `mpi/`, `extraction/`) *does*
have its own live-DB integration test suite that seeds exactly the rows it needs directly in the test
itself (49 tests passing against a real disposable Postgres, `AI_PROGRESS.md`'s 2026-08-27/2026-08-28
entries) — that's real validation of the code paths, just not a shared, reusable demo dataset a human
could explore interactively the way `seed_demo_data.py` is meant to provide.

---

## Summary: what's actually open after this document

**Resolved since the original 2026-08-26 draft** (kept here for the record, not as open items):
the Version A/B schema fork (item 7's basis) — `Final_schema.sql` adopted as canonical
(`PENDING_ACTIONS.md` #27); the `evidence_records` structural gap blocking 4 of 5 modules from
writing evidence at all (`PENDING_ACTIONS.md` #28); `get_current_tenant()`'s infinite-recursion bug,
which would have crashed every RLS-scoped query the instant a non-superuser role was actually used
(`PENDING_ACTIONS.md` #32); `products.cost`/margin guardrail (now `products.cost_price`, functional).

**Genuinely still open:**

1. A labeled evaluation set per model family (item 5) — needed for real §25 metrics, not fabricable.
2. Real data for `competitor_prices`/`reviews`/`news_record`/`social_mention` (item 3/6) — this
   track's own live-DB integration tests validate the code paths against seeded rows, but that isn't a
   substitute for production data, and item 12's seed-data extension never actually landed (see below).
3. Four missing event contracts + consumers (item 9) — infra provisioning + real consumer classes.
4. The Arabic/English LLM evaluation set + final model selection (item 10).
5. Everything past retrieval in the RAG pipeline (item 11) — blocked on #4.
6. **RLS is policy-correct but not operationally active** (item 6) — the non-superuser `ceopro_app`
   role and its policies now work correctly, but nothing in the deployed system connects as that role
   or sets tenant session context, so production isolation today is still zero, for an operational
   reason (which role connects) rather than a policy-correctness one. Needs a real service wired to
   connect as `ceopro_app` and set `app.current_tenant_id`/`app.current_user_id` per request —
   `PENDING_ACTIONS.md` #2.
7. Two schema gaps confirmed real, not hypothetical, both blocking the excluded Demand Forecasting
   module specifically: `transactions` and `model_versions` don't exist in `Final_schema.sql` at all
   (`PENDING_ACTIONS.md` #31). Not this document's modules' problem directly, but `seed_demo_data.py`
   (item 12) is broken by the same gap — it `INSERT`s into `transactions`.
8. `seed_demo_data.py`'s extension to cover this track's own tables (`competitors`/`reviews`/etc.)
   was written on the now-closed PR #15 but never merged — item 12's original claim that it existed
   and just needed a live-DB run was inaccurate. The seeder on `main` today is unextended and, per #7
   above, would crash against `Final_schema.sql` regardless. Real, separate follow-up work, correctly
   outside this track's boundary (`seed_demo_data.py` is an infra file).
9. The Universal Import Engine (`ingestion_pipeline.py`, all 5 `extraction/adapters/` files,
   `row_parsing.py`, `template_detection.py`, `locale_config.py`, `minio_persistence.py` — spec §12,
   not covered elsewhere in this document since it grew independently of this track's five modules) —
   largely unverified. A 2026-08-28 QA pass added real test coverage to 3 of ~10 files in this
   subsystem and found genuine bugs in 2 of them (silently degraded extraction quality, not crashes) —
   `RED_FLAGS.md`'s 🟠 High section, `PENDING_ACTIONS.md` #37. The rest of this subsystem should be
   treated as unverified, not assumed correct because nothing has crashed in normal use.
