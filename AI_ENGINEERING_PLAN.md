# CEOPRO AI — Engineering Plan (AI/ML Track)

> **Editorial note added 2026-08-27, merging this document to `main` for the first time:**
> this document was written 2026-08-26 against "Version A" (`init_schema.sql`, 21 tables) and
> describes the schema fork it references (`Version A` vs. the 26-table `Version B`) as a
> **still-open decision**. That decision has since been made: `Final_schema.sql` (what this
> document calls Version B) was adopted as canonical (`PENDING_ACTIONS.md` #27), and every
> AI/ML module below has been reworked against it — see `AI_PROGRESS.md`'s 2026-08-27 entries and
> [RED_FLAGS.md](RED_FLAGS.md) for what actually changed and what was found along the way. The
> **"Schema basis" line and every "Version A"/"Version B" reference below are now historical**,
> not current guidance — kept as-written rather than rewritten, since the reasoning in the rest of
> this document (functional requirements, use cases, data quality rules, success metrics,
> architecture, orchestration, LLM/RAG approach) is substantially still valid and this note lets a
> reader tell old context from current fact without guessing.

**Owner:** AI/ML Engineering
**Status of this document:** closes the "will provide later" gap `PENDING_ACTIONS.md` #11 flagged —
`AI_ENGINEERING_PLAN.md` was referenced by `AI_PLAN_AND_CONTRACT_UPDATES.md` and `AI_CONTRACT_CHANGES_AND_CLARIFICATIONS.md`
but never existed in this repo until now.
**Grounded in:** `MASTER_SPEC_v4.md` (the real spec, `noorhassouneh-patch-1`), `AI_PLAN_AND_CONTRACT_UPDATES.md`'s
precedence rule, the actual current state of `src/ai/` (`AI_PROGRESS.md`'s Module status table), and
open items in `PENDING_ACTIONS.md`. Nothing in this document is invented outputs, KPIs, or
architecture that don't trace to one of those four sources or to code that actually exists.

**Explicit exclusions (per instruction):** this document does not cover Demand Forecasting
(`src/ai/forecasting/`, spec §18) or "AI Advisor." The latter term doesn't appear anywhere in
`MASTER_SPEC_v4.md`, `AI_PLAN_AND_CONTRACT_UPDATES.md`, `AI_PROGRESS.md`, or `PENDING_ACTIONS.md` —
it isn't a defined module in this repo. Since spec §21's RAG Chatbot *is* separately and explicitly
in scope below (item 11 of the originating task list asks for RAG architecture), "AI Advisor" is
treated here as a distinct, not-yet-specified feature and nothing is built or written under that name.
If it refers to something specific, flag it and this document gets a follow-up entry.

**Schema basis:** validated against Version A of `init_schema.sql` (21 tables, current default on
every merged AI/ML PR) — per `AI_PLAN_AND_CONTRACT_UPDATES.md`'s own precedence rule, *"the
implemented schema/code wins for anything already built."* `main`'s unreviewed 26-table rewrite
(Version B) is a separate, still-open decision (`PENDING_ACTIONS.md` #29/#30, comparison published
as the [Schema Fork Ledger](https://claude.ai/code/artifact/e96b0b60-3875-4496-b73c-5131e2d5861e)) —
not adopted here.

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
  a price-change guardrail and (once `products.cost` is set) a margin floor, and traces every
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
| Business (core) | `companies`, `products`, `inventory`, `transactions` | Backend/platform | ✅ Real, ingested via Phase 1 |
| Operational — pricing | `competitors`, `competitor_prices` | AI Market Scraper Service (named, not built) | 🔴 Empty (`PENDING_ACTIONS.md` #5) |
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
| Sentiment (`sentiment/`) | Accuracy, Macro F1, Confusion Matrix, Calibration | Not yet — `test_sentiment_model_real.py` checks known-clear-cases classify correctly, not a held-out labeled set |
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

Access: `src/ai/` reads via `psycopg2` connections; as of `PENDING_ACTIONS.md` #25 (resolved), the
correct restricted role for this is the non-superuser `ceopro_app` (RLS-enforced), not `ceopro_admin`.
No `src/ai/` code currently constructs its own MinIO client for `rag/` — callers must inject one
(established convention, see `src/ai/README.md`).

Integration readiness by source, restating item 3 with an explicit readiness verdict:

- `transactions`/`products`/`inventory` — ✅ ready, real data flowing since Phase 1.
- `competitor_prices` — 🔴 not ready. Table and RLS policy exist; no producer. Blocks Phase 5's
  recommendation path and all of Phase 6 (Competitor Ranking).
- `reviews` — 🔴 not ready. Same situation, and per item 3, no owner is even assigned yet.
- `news_record`/`social_mention` — 🔴 not ready, same gap.
- `rag_documents_metadata` + MinIO — 🟡 ready mechanically (ingestion pipeline built and tested), but
  depends on tenants actually uploading documents; nothing seeds this in production either.

Net: of the five modules in scope for this document, **two (`pricing/`, and half of Phase 4) are
integration-ready in code but not in data.** This is the single largest gap between "built" and
"delivering real business value" for this track right now — not a code problem.

## 7. Database Schema Validation Against AI Inputs, Outputs, and Traceability

Validated against Version A (see header). Every table this track's built modules read from or write
to exists with the expected shape:

- **Reads:** `products`, `competitors`, `competitor_prices`, `reviews`, `news_record`,
  `social_mention`, `currency_rates`, `rag_documents_metadata` — all present, columns match what
  every `data_access.py` in `src/ai/` queries (confirmed by the live-DB integration test suite passing
  against a real disposable Postgres running this exact schema).
- **Writes (this track's owned tables per `DATA_OWNERSHIP_AND_CONTRACTS.md`):** `evidence_records`,
  `sentiment_results`, `extracted_entity`, `recommendation_outcomes` — present, correct FKs
  (`tenant_id → companies`, category-specific FKs like `sentiment_results.review_id → reviews`).
- **Traceability (spec §22):** every `evidence_records` row this track writes carries
  `source_record_ids` (JSONB) pointing back to the specific rows that produced it — verified in
  integration tests, not just asserted in code.
- **Gaps found and already tracked:** `model_versions` — the table this track needs for the excluded
  Demand Forecasting module's own artifact tracking — exists in Version A but was silently dropped in
  Version B with no replacement (Schema Fork Ledger). Not a gap in Version A itself, but a live risk
  if Version B is ever adopted without addressing it. `products.cost` was a real gap, resolved
  (`PENDING_ACTIONS.md` #14, margin guardrail now functional).

Nothing in this section required a schema *change* — Version A already supports every AI
input/output/traceability need for the modules in scope.

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
`forecasting/consumer.py` (excluded), which is why `src/ai/db.py`'s `set_tenant_context()` is the only
RLS-context call site outside that one file.

Cross-cutting shared components (not duplicated per module, per spec §22/§23's explicit "one
consistent" requirement):
- `forecasting/evidence.py::insert_evidence_record()` — reused directly by `pricing/`, `sentiment/`,
  `extraction/` (indirectly), and `mpi/` rather than five separate evidence-writing implementations.
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
mirroring `forecasting/consumer.py`'s already-proven pattern exactly (one persistent connection,
`set_tenant_context()` per message, ack-after-success):

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
(the pgvector-backed persistence table) exists in Version A's schema but `rag/pipeline.py` doesn't
write to it — chunks/embeddings are computed in-memory only. **Recommended approach to finalize:**
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

See the separate implementation entry in `AI_PROGRESS.md` (this document is grounding/planning, not
where code changes get logged) — `src/infrastructure/database/seed_demo_data.py` extended to seed
`competitors`, `competitor_prices`, `reviews`, `news_record`, and `social_mention` (all previously
seeded with zero rows, per item 3/6 above). **Written but not yet validated**: Docker was unavailable
in this environment, so the extended seeder has not actually been run against a live database, and no
module's real pipeline has been confirmed to produce non-`UNKNOWN` output against it yet — that
confirmation is a required follow-up before this item is genuinely done, not a formality.

---

## Summary: what's actually open after this document

1. A labeled evaluation set per model family (item 5) — needed for real §25 metrics, not fabricable.
2. Real data for `competitor_prices`/`reviews`/`news_record`/`social_mention` (item 3/6) — this
   track's seed data (item 12) validates the code path, it isn't a substitute for production data.
3. Four missing event contracts + consumers (item 9) — infra provisioning + real consumer classes.
4. The Arabic/English LLM evaluation set + final model selection (item 10).
5. Everything past retrieval in the RAG pipeline (item 11) — blocked on #4.
6. The Version A/B schema fork (item 7's basis) — still awaiting an explicit decision,
   `PENDING_ACTIONS.md` #29/#30.
7. Item 12's seed data was written but never run — Docker was unavailable in this environment. Needs
   a live-DB pass confirming `pricing/`/`sentiment/`/`mpi/`/`extraction/` actually produce non-`UNKNOWN`
   output against it before this item counts as verified, not just implemented.
