# KEEL Business Copilot - Architecture Audit, Gap Analysis, and Plan

Written before any implementation in this pass, then updated with exactly
what was actually built. Every claim below is either a direct code
citation (file:line, verified by reading the code) or explicitly marked
as a recommendation/limitation not yet implemented. Nothing here should
be read as "the copilot now understands everything about your business" -
see "What this honestly cannot do yet" at the end.

## 1. What already existed (do not rebuild)

The RAG pipeline was audited file-by-file before any change. It is
substantially more built than "simple RAG":

- **Real hybrid retrieval**: `rag/bm25_index.py` (BM25Plus) + `rag/faiss_index.py`
  (exact cosine, IndexFlatIP) fused via Reciprocal Rank Fusion
  (`rag/hybrid_retrieval.py`), then re-ranked by a real, live multilingual
  Cross-Encoder (`rag/reranking.py`,
  `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`) - not a stub, with a
  logged, non-fatal fallback to RRF order if the reranker call fails.
- **Real live structured facts**: `rag/structured_context.py` runs ~7
  cheap, tenant-scoped queries on every chat turn (sentiment, competitor
  tiers/names, price gaps, forecasts, proactive insights, recent
  competitor activity with direct links) and injects them as a second,
  separately-labeled prompt section - the right answer to "an LLM
  shouldn't have to rely on semantic search finding the one chunk with
  the exact number."
- **Real, confidence-gated web-search fallback**: `rag/web_fallback.py` -
  only fires when both retrieval and structured facts come back
  genuinely empty, requires 2+ corroborating sources, scopes the query to
  the tenant's own business_type/country, never fabricates on failure.
- **Real citations**: `answer_query()` (`rag/llm_client.py`) returns
  `{"answer", "sources"}` - chunk citations (`source_index`, `chunk_id`,
  `score`) and web sources (`url`, `title`) both real, never invented;
  the frontend (`SourceCitationList.jsx`) already renders them.
- **Real multi-turn history support**: `generate_answer(..., history=...)`
  threads a caller-supplied message list into the LLM call, sanitized and
  capped at 12 messages server-side. (Not persisted server-side, and - a
  real gap this pass closed, see §3 below - the frontend never actually
  sent it before this pass.)
- **Real tenant isolation**: every RAG query is both application-filtered
  (`WHERE tenant_id = %s`) and RLS-protected (`FORCE ROW LEVEL SECURITY`,
  `ceopro_app` - a real non-superuser role - via transaction-scoped
  `SET LOCAL`). Verified for real in this pass (§4 below), not just
  inferred from other tables' tests.
- **Real application self-knowledge, as prose**: `rag/structured_summaries.py`'s
  `SLOT_PLATFORM_HELP`/`SLOT_TROUBLESHOOTING_HELP` are real,
  retrieval-eligible documents explaining how KEEL works and how to
  fix common problems - ingested through the exact same pipeline as a
  real uploaded document. This is genuinely useful today, but it is
  static prose, not the route/component/feature_id-addressable
  structured metadata layer described in §14 below - see the honest
  distinction there.
- **Real, substantial test coverage**: 6 offline unit-test files per
  retrieval component, a 14-case live-DB `test_rag_integration.py`
  covering ingest→retrieve→rerank end to end, 24 `test_rag_llm_client.py`
  cases, 14 `test_rag_web_fallback.py` cases, and two ~12/~25-case
  live-DB integration suites for structured facts/summaries.

**None of the above was touched or rebuilt in this pass.**

## 2. Confirmed gaps (the real basis for what to build)

1. **No financial/profitability tooling anywhere.** Grepped
   `margin|profit|cost_price|COGS` across `dashboard/`, `pricing/`,
   `sales/`, `insights/` before writing anything new - the only hits were
   `pricing/guardrails.py`'s price-floor safety clamp (a side effect, not
   a report) and one narrative aside. `dashboard/metrics.py` has revenue
   but no cost/margin. `products.cost_price` exists and is read by
   `pricing/data_access.py::load_own_product`, but never aggregated into
   a profitability report anywhere. This is the single most concretely
   and repeatedly requested capability in the request this work responds
   to ("which products are most profitable", "where did my profit go",
   "which product is losing money").
2. **Structured facts are always-on and fixed, not query-driven.**
   `structured_context.py` runs the same ~7 queries on every single
   message regardless of what was asked - there was no precedent in this
   codebase for "decide which extra queries this specific question needs"
   before this pass.
3. **No agentic/tool-calling orchestration loop.** `llm_client.py` does
   one single-shot chat-completion call. There is no multi-step
   plan→retrieve→calculate→validate loop of the kind MASTER_SPEC_v4.md
   §21 itself describes (query normalization, intent classification,
   entity extraction, date/filter extraction are all named there as
   pipeline stages and confirmed absent from the actual code).
4. **Conversation history existed server-side but the frontend never sent
   it.** `knowledgeBaseApi.js` explicitly declared
   `conversationHistory: false` and never passed `history_json` to
   `/rag/query` - a real, confirmed, low-effort-to-close gap.
5. **No RAG-table-specific tenant-isolation regression test.**
   `test_rls_integration_db.py` never referenced `rag_document_chunks`/
   `rag_documents_metadata` by name - isolation was real (same policy
   pattern as every other table) but unproven by a direct test.
6. **No RAG evaluation dataset.** `AI_ENGINEERING_PLAN.md` (line 136-137)
   already flagged this as an open, un-filled gap before this pass.
7. **No structured, machine-addressable application-knowledge layer**
   (route/component/feature_id/action metadata) - only prose. This is a
   real, substantial, NOT-implemented-in-this-pass gap - see §14.
8. **No conversation persistence table**, no application-action execution
   (add a product, create a campaign, etc. via chat) - both real,
   NOT-implemented-in-this-pass gaps - see §14.

## 3. What was implemented in this pass

Scoped deliberately to the highest-value, most tractable pieces - not all
25 sections of the originating request. Every item below is real,
tested, and (where a live database was available in this sandbox)
verified against actual Postgres, not just asserted.

### 3.1 Financial/profitability structured-data tools (new)

- `dashboard/financial_summary.py` - two deterministic, directly-testable
  functions:
  - `get_profitability_summary()`: business-wide revenue, cost of goods
    sold, gross profit, gross margin %, current window vs. prior window
    of equal length (same two-window convention `dashboard/metrics.py`
    already established).
  - `get_product_profitability()`: per-product ranking (`most_profitable`,
    `least_profitable`), plus a `no_cost_data` list for products sold
    with no `cost_price` on file - **never silently treated as zero
    cost**, which would fabricate an inflated margin. This is the single
    most important honesty behavior in this module.
  - Both are explicit that they compute **gross margin only** - revenue
    minus product cost. Fixed operating expenses, marketing spend,
    discounts/returns, and taxes are named in the output
    (`excludes: [...]`) as NOT included, since this schema has no tables
    for any of those. This directly matches the "state which costs are
    not included" requirement this work responds to.
- `rag/business_tools.py` - the first instance in this codebase of the
  chat pipeline choosing which extra query to run **based on the actual
  question**, rather than running a fixed set on every turn:
  - `is_financial_question()` - a real (English + Arabic) keyword gate,
    deliberately not an LLM-based intent classifier (would add latency/
    cost to every message just to decide whether to run two more
    queries).
  - `build_financial_facts_block()` - only calls the two functions above
    when the gate fires, formats the result with inline
    `(source: table.column)` citations (same discipline
    `structured_context.py` already uses), and returns `""` (never a
    placeholder) when the question isn't financial or there's genuinely
    no revenue to report.
  - Wired into `rag/llm_client.py::answer_query()`: appended to the
    existing `structured_facts` block, so it flows through the exact same
    prompt section, provenance instructions, and citation discipline
    already in place - no new prompt-engineering surface needed.

### 3.2 Conversation history: frontend now actually sends it

- `knowledgeBaseApi.js`: `conversationHistory` flipped from `false` to
  `true` (it is now genuinely true); `chat()` maps the page's own
  `messages` state to `[{role, content}]`, capped client-side at 12
  entries (matching `llm_client.py`'s own server-side cap), sent as
  `history_json` - omitted entirely (not an empty array) on the first
  turn, matching this codebase's "never serialize an explicit empty/null
  for an unset optional field" convention.
- `RagAssistantPage.jsx`: passes its existing `messages` state through to
  the chat mutation - no new state, no new component.
- This is the direct, real fix for the worked example in the request this
  responds to ("show me my best-selling product" → "how much profit did
  it generate?") - `eval/business_copilot_eval_set.py`'s `mix-03`/`mix-04`
  pair exists specifically to verify this end to end.

### 3.3 RAG-table tenant isolation: proven, not just inferred

Added to the existing `test_rls_integration_db.py` (not a new file - same
fixtures, same `ceopro_app`-role convention, extended rather than
duplicated):

- `two_tenant_rag_documents` fixture seeds one document + one chunk each
  for two distinct tenants.
- Four new tests prove: `rag_documents_metadata` scoped to tenant A never
  returns tenant B's document; `rag_document_chunks` scoped to tenant A
  never returns tenant B's chunk text; a connection with no tenant
  context set sees nothing (fail-closed); and - the most direct proof,
  since this is the real call site the chatbot uses -
  `rag/data_access.py::load_tenant_chunks()` itself, called as tenant A,
  never returns tenant B's chunk text.
- **Verified for real** in this pass: a local Postgres instance was
  stood up, the full migration chain applied, the `ceopro_app` role's
  password set, and both the new tests and the full existing
  `test_rls_integration_db.py` suite run against it - 16/16 passed.

### 3.4 Evaluation dataset (new, real, not a scoring harness)

- `rag/eval/business_copilot_eval_set.py` - 20 representative questions
  across the exact categories the originating request named (application/
  company-financial/market/mixed/edge-case), each tagged with an
  `expected_grounding` state (`structured_data` / `application_knowledge`
  / `market_external` / `insufficient_data` / `mixed`) and reviewer
  `notes` naming the SPECIFIC failure mode that question is designed to
  catch - not a generic rubric.
- Includes the `mix-03`/`mix-04` conversation-memory pair (the design
  brief's own "best-selling product → its profit" worked example) and a
  `fin-07` case specifically testing the "no cost data at all" honesty
  path.
- **Explicit, honest limitation**: no automated scorer exists. Running
  this dataset against a real tenant's data and grading the answers is a
  manual (or future semi-automated) activity this file enables but does
  not itself perform - see its own module docstring for exactly how to
  run it today.

### 3.5 Tests added, all passing

- `test_financial_summary_integration_db.py` (6 cases, live-DB, run for
  real against local Postgres in this pass) - including the
  "no-cost-data excluded, never treated as zero" case.
- `test_business_tools.py` (8 cases, offline, mocked) - intent gate
  (English + Arabic), empty-when-no-revenue, full block formatting,
  "never fabricate a loss that isn't real" case.
- `test_business_copilot_eval_set.py` (4 cases) - dataset structural
  sanity (every category present, the conversation-memory pair exists
  and is ordered correctly).
- `test_rls_integration_db.py` +4 cases (see §3.3).
- `knowledgeBase.test.mjs` (frontend, new file) - proves `history_json`
  is sent correctly on a follow-up turn and omitted on the first turn.

## 4. What this pass deliberately did NOT build

Per the originating request's own "do not over-promise" instruction -
named honestly here rather than silently left out:

- **No multi-step agentic/tool-calling loop.** `business_tools.py`'s
  keyword gate is real query-driven tool selection, but it is a single
  additional check, not a general plan→act→observe loop that could
  reason about arbitrary combinations of tools for a genuinely novel
  question. `mix-01`/`fin-06` in the eval set are designed to expose
  exactly this limit.
- **No conversation persistence table.** History still only exists for
  the duration of one browser session's own local state, re-sent on
  every request - not saved server-side, not resumable across devices/
  sessions.
- **No structured application-knowledge layer** (route/component/
  feature_id/version/source_commit metadata, as described in the
  originating request). The two real platform-help/troubleshooting prose
  slots remain the only self-knowledge mechanism. Building the described
  structured layer (a real metadata registry synchronized to the actual
  frontend route table, re-indexed on deploy) is substantial, standalone
  work - a real Phase 2/3 item, not something safely scoped into this
  pass alongside the financial-tooling work.
- **No application-action execution** (the chat cannot add a product,
  create a campaign, or change a price on a user's behalf). Every
  "how do I..." question still only returns instructions, never executes
  anything - matches the originating request's own "if action execution
  is not already supported safely, at least provide precise step-by-step
  instructions" fallback.
- **No root-cause attribution for "why did revenue/profit change"
  questions.** The new financial tool reports WHAT changed (the real
  trend numbers) but cannot yet attribute WHY beyond what
  `insights/pipeline.py`'s existing proactive insights already surface -
  `fin-03`/`mix-01` in the eval set are designed to verify the system is
  honest about this limit rather than guessing a cause.
- **No automated eval scoring harness** - the dataset exists; running and
  grading it does not, yet.

## 5. Recommended architecture (target state, not built here)

The right next evolution, in priority order, building on everything in
§1 and §3 rather than replacing it:

1. **A small, explicit tool registry** (product-profitability,
   competitor-comparison, forecast-lookup, etc. - most of the read
   functions §6 of the original audit already catalogued) with a
   lightweight LLM-based tool-selection step for genuinely ambiguous
   questions - reserving the current cheap keyword gate for the common,
   clearly-financial case, and only paying an extra LLM call's latency
   when the keyword gate itself is uncertain.
2. **A `conversation_sessions`/`conversation_messages` table pair**,
   RLS-protected identically to every other tenant table, so history
   survives a page refresh and multiple devices - a bounded, well-
   understood schema addition, not a redesign.
3. **A structured application-knowledge registry** - a versioned JSON/YAML
   manifest of routes/components/features (generated from the frontend's
   own route config where possible, to avoid manual drift), ingested
   through the exact same `rag/pipeline.py` path `structured_summaries.py`
   already uses, so "how do I..." answers can eventually cite a specific,
   current route rather than static prose.
4. **A real eval-scoring pass** - run `business_copilot_eval_set.py`
   against a real seeded tenant, grade each answer by hand against its
   `expected_grounding`/`notes`, and use the results to prioritize which
   gap actually costs the most in wrong/hedged answers.
5. **Root-cause attribution for revenue/profit changes** - a genuinely
   harder analytical feature (which products/costs moved the most, in
   what direction, contributing what share of the total change) - real
   future work, not a quick addition.

None of this requires new paid infrastructure - every recommendation
above reuses the existing Postgres/pgvector, the existing Groq/local-LLM
choice, and the existing RLS/tenant-isolation model.

## 6. Cost/infrastructure impact of what was actually shipped

Zero. `business_tools.py`/`financial_summary.py` are plain SQL functions
against tables that already exist (`invoices`, `invoice_items`,
`products`) - no new migration, no new external service, no new
dependency. The conversation-history frontend change sends slightly more
request payload per chat turn (capped at 12 short messages) - negligible.
Nothing here changes this service's Render free-tier compatibility.

---

# Phase 2 (this pass): Application Knowledge, Tool Registry, Orchestration, Root-Cause Analysis

Everything below is additive to Sections 1-6 above. Nothing described
there was rewritten - the hybrid BM25+FAISS+RRF+cross-encoder retrieval,
`ceopro_app`/RLS security model, citation-returning `answer_query()`,
always-on structured facts, financial-intent gating, confidence-gated web
fallback, and existing frontend RAG UI are all unchanged and reused.

## 7. Application Knowledge Layer (B1) - what's implemented

`backend/src/ai/knowledge/application_registry.py` - a structured,
dataclass-based registry (`ApplicationFeature`) of 12 curated,
source-verified KEEL features (add/edit a product, quick sale, view/add
a competitor, competitor profile, pricing recommendation, demand
forecast, marketing studio, the RAG assistant itself, the dashboard).
Every entry's `route` was checked against the real
`frontend/src/app/router/routePaths.js`, every `frontend_source_file`
against a real file on disk, every `backend_service` against a real
importable Python path - not invented, not guessed from memory. Each
entry carries `feature_id`, `name`, `route`, `page`, `component`,
`action`, `action_steps`, `fields`, `field_meanings`, `api_endpoint`,
`http_method`, `permissions`, `workflow_dependencies`, `backend_service`,
`frontend_source_file`, `locale`, `source_commit`, `last_synchronized` -
the full schema the original request specified.

**Honest scope**: 12 entries is a curated starting set (the
highest-traffic "how do I..." questions), not exhaustive coverage of
every route in `routePaths.js` (which has ~50). Extending coverage is
pure repetition of the same pattern - real future work, not a
architectural gap.

## 8. Knowledge synchronization (B2) - what's implemented, honestly

**Not automatic.** `backend/scripts/validate_application_knowledge.py` is
a real, runnable staleness DETECTOR: it parses the actual
`routePaths.js`, checks every registry `route` against it, checks every
`frontend_source_file` exists on disk, and checks every `backend_service`
still imports. It exits non-zero and prints exactly which entries are
stale if anything drifted - verified for real in this pass (both the
positive case against the live repo, and a negative case with a
deliberately broken entry - see `test_application_knowledge.py`). It does
**not** run automatically today - no CI workflow calls it yet (this repo
has one existing workflow, `.github/workflows/staging-deployment.yml`,
unrelated to this check). Wiring it into CI (fail a PR that touches
`routePaths.js`/frontend pages/routers without re-running this) is a
one-file addition, deliberately left for a follow-up rather than bundled
into this already-large pass. Running it manually after a route change is
the real, current synchronization process - documented here plainly
rather than claimed as automatic.

## 9. Tool Registry (B3) - what's implemented

`backend/src/ai/rag/tools.py` - 26 read-only tools, each a thin wrapper
around an **already-existing** service function (verified via a
dedicated Explore-agent survey of the codebase before writing a single
tool, specifically to avoid duplicating logic):

| Category | Tools | Reuses |
|---|---|---|
| Application | `search_application_knowledge`, `get_feature_details`, `get_page_workflow` | `knowledge/application_registry.py` |
| Products | `list_products`, `get_product`, `search_products` | `routers/products.py` |
| Sales/financial | `get_sales_summary`, `get_top_selling_products`, `get_revenue_summary`, `get_profitability_summary`, `analyze_margin`, `analyze_revenue_change` | `dashboard/financial_summary.py` |
| Inventory | `get_inventory_summary`, `get_low_stock_products` | `dashboard/inventory.py` (`get_low_stock_products` is genuinely new - see §12) |
| Competitors | `list_competitors`, `get_competitor_activity`, `compare_competitor_prices` | `dashboard/competitors.py`, `competitor_activity.py`, `competitor_pricing.py` |
| Pricing | `get_pricing_recommendation`, `compare_current_price_to_market` | `pricing/pipeline.py` |
| Forecasting | `get_product_forecast`, `get_demand_summary` | `dashboard/forecast_detail.py`, `forecast.py` (presentation-layer reads of already-computed forecasts, never triggers a new model run per chat question) |
| Marketing | `get_campaign_summary`, `get_marketing_performance` | `marketing/data_access.py` |
| RAG | `search_documents`, `retrieve_relevant_context` | `rag/pipeline.py::run_retrieval` (the same retrieval `answer_query()` already uses) |
| External | `web_search` | `rag/web_fallback.py::build_web_fallback_context` |

Every tool is `tool_fn(conn, tenant_id, **kwargs) -> dict`, read-only, no
write path anywhere in this file.

## 10. Intent-driven orchestration (B4) - what's implemented

`backend/src/ai/rag/orchestrator.py` extends the exact keyword-gate
pattern `business_tools.py` already established (real English+Arabic
keyword matching, not an LLM planning call) to 7 more intent categories:
application-help, top-products, inventory, competitors, demand-forecast,
marketing, and root-cause ("why did..."). Wired additively into
`answer_query()` in `llm_client.py` - the existing structured-facts and
financial-facts blocks are computed exactly as before; this pass appends
zero or more labeled blocks on top, only for the categories the
question's own text actually matched (verified: 10 mocked tests proving
unrelated questions call zero tools, and single/multi-category questions
call exactly the matching tool(s) - never every tool). Each block carries
an explicit `TENANT_BUSINESS_DATA` or `CEOPRO_APPLICATION_KNOWLEDGE`
label (B8's source-type distinction), consumed by
`format_blocks_for_prompt()`.

**Honest scope**: this is still not a general agentic tool-calling loop
(no LLM decides which tool to call - the keyword gate does, deterministically).
A real multi-step plan/act/observe loop remains deferred, per the
original PR #7 architecture doc's own recommendation (§5.1).
Per-product tools (`get_pricing_recommendation`, `get_product_forecast`)
are deliberately **not** wired into the automatic gate - they need a real
`product_id`, and guessing one from free text risks calling a tool on the
wrong product and presenting that as the tenant's own data, which is
worse than not answering. They remain in the tool registry, callable by
a future real orchestration layer with proper entity resolution.

## 11. Deterministic financial analysis + root-cause decomposition (B5/B6)

Extended `dashboard/financial_summary.py` with `analyze_revenue_change()`
and `analyze_margin_change()` - both pure, deterministic SQL+arithmetic,
zero LLM involvement:

- `analyze_revenue_change`: exact additive decomposition
  `delta_revenue = units_effect + price_effect` (`units_effect = delta_units
  * prior_ASP`, `price_effect = recent_units * delta_ASP` - standard
  variance-decomposition algebra, not a heuristic), plus a `top_movers`
  list of which specific products' revenue changed most - explicitly
  labeled a correlation/signal ("this is a correlation/signal, not proof
  of causation... no marketing-spend, discount, or competitor-action data
  to attribute a specific cause"), never presented as a proven cause.
- `analyze_margin_change`: splits the gross-profit change into a
  `revenue_effect` and a `cogs_effect` (also exact: their sum equals the
  gross-profit change), reusing `get_profitability_summary()`'s own query
  results rather than a second copy of the SQL.

Both verified with 6 new live-DB integration tests with exact
hand-computed expected values (e.g. "10 units more at the same $10 ASP ->
units_effect == 50.0, price_effect == 0.0" - genuinely checked, not just
"returns something").

## 12. A real, confirmed gap this pass closed

`dashboard/inventory.py::get_low_stock_products()` - the original
`get_inventory_status()` was aggregate-only (a count and percentage);
no function returned the actual list of low-stock products. This is the
one place Phase 2 added real new SQL rather than reusing an existing
function - small (one query, same `stock_quantity <= reorder_level`
definition `get_inventory_status()` already used), and it belongs in the
same file as the function it extends.

## 13. Security (B10) - verified, not assumed

Extended tenant-isolation testing with a new
`test_business_copilot_tools_tenant_isolation.py` - 8 live-DB tests
against the real restricted `ceopro_app` role (not mocked), seeding two
tenants with their own products/sales/inventory/competitors and calling
the actual tool functions (`list_products`, `get_product_profitability`,
`analyze_revenue_change`, `get_low_stock_products`,
`get_inventory_status`, `get_competitor_directory`) scoped to tenant A,
asserting tenant B's data never appears - including the specific case of
a caller passing the WRONG tenant_id as an argument (proving RLS, not the
Python argument, is what actually governs visibility) and a
no-tenant-context case (fails closed). All 8 passed for real.

## 14. Evaluation harness (B12/B13) - what actually ran

`backend/src/ai/rag/eval/run_eval.py` - three honestly-labeled modes:

1. **Deterministic gate-selection check** (always runs, no DB/LLM/network):
   for each of the 20 eval cases, checks whether the question's own text
   triggers the keyword gate its `expected_grounding` implies it should.
   Result against the real dataset: **0 failures** (9 direct PASS, 7
   `mixed`-category cases reported informationally since they may
   legitimately rely on the pre-existing always-on facts block rather
   than a Phase-2 gate, 5 cases honestly marked "not statically
   checkable" since `market_external`/`insufficient_data` depend on
   runtime data state, not question text).
2. **Live-DB check** (`--live-db`, needs a real Postgres): seeds a real
   tenant, runs the actual tool functions the gate selected, checks for a
   real citation marker in the output. Run for real against local
   Postgres: 16 of 16 gate-fired cases produced a citation marker.
3. **Live-LLM check** (`--live-llm`, needs a real API key + network): ran
   for real in this environment and **failed honestly** - this sandbox's
   egress proxy blocks `huggingface.co` (needed to load the embedding
   model before retrieval can even run), so the harness reported the real
   `MaxRetryError`/403 rather than fabricating a result. This is the same
   network restriction documented in the marketing-feature work earlier
   in this project; a real Codespace or Render deployment (see PR A) does
   not have this restriction. **No live LLM call has been verified
   end-to-end for Phase 2** - this is an honest, reported gap, not a
   claimed capability.

## 15. Frontend (B14) - a real bug fixed

`knowledgeBaseApi.js::mapSources()` labeled BOTH a web-fallback source
and a document-chunk source `sourceType: 'knowledge-base'` - meaning the
UI could not actually distinguish external web content from the tenant's
own ingested documents, contradicting this feature's own "never present
external information as if it came from the user's company" requirement.
Fixed: web sources now get `sourceType: 'web'`;
`SourceCitationList.jsx` renders a distinct badge/icon for it and (a
second real gap this closed) makes it an actual clickable link to the
real URL - previously a web source had no `documentId` and therefore
rendered as a non-interactive `<div>`, not clickable at all.

## 16. What Phase 2 deliberately did NOT build

- **A real multi-step agentic tool-orchestration loop.** The
  keyword-gated orchestrator is real, deterministic tool selection, not a
  general LLM-driven planning loop that could compose arbitrary tool
  sequences for a genuinely novel question.
- **Conversation persistence.** Was still session-local only at the time
  Phase 2 shipped - closed in a later gap-closure pass, see §18.
- **Application-action execution (B11).** The tool registry remains
  strictly read-only. No write action was added this pass - not even a
  confirmation-gated one. `search_application_knowledge`/
  `get_page_workflow` give precise instructions instead, per the
  fallback this feature's own request specified.
- **Automatic CI-wired knowledge-sync validation.** Was true at the time
  Phase 2 shipped - closed in a later gap-closure pass, see §18.
- **Root-cause attribution beyond revenue/COGS/units/ASP.** Marketing
  spend, discounts, and competitor-action causality remain untracked and
  unattributed - explicitly stated in every root-cause tool's own output,
  never guessed.
- **Per-product tool auto-resolution from free text** (e.g. "how is my
  iPhone case pricing" automatically resolving a specific `product_id`) -
  deferred pending real entity resolution, to avoid ever calling a
  per-product tool on the wrong product.
- **A live, end-to-end LLM-verified answer for any Phase 2 case** - see
  §14's honest report on why (sandbox network restriction).

## 17. Cost/infrastructure impact of Phase 2

Zero. Every new module (`knowledge/`, `rag/tools.py`,
`rag/orchestrator.py`, the two new `financial_summary.py` functions, the
one new `inventory.py` function) is plain Python/SQL against tables that
already exist - no new migration, no new external service, no new paid
dependency. `frontend/src/features/knowledge-base` changes are a
citation-labeling fix, not new UI surface.

## 18. Gap-closure pass (this pass): conversation persistence, CI wiring, test coverage

Closes three of §16's own gaps for real, verified against a live
Postgres instance and a real GitHub Actions run - not just documented as
closed.

**Conversation persistence.** New `conversation_sessions`/
`conversation_messages` tables (both tenant+user RLS-scoped - a
conversation is one person's chat, not shared company data, so the
policy checks `user_id = current_setting('app.current_user_id', ...)`
in addition to the usual tenant check), `rag/conversation_store.py`,
and an optional `session_id` on `POST /rag/query` (loads real persisted
history when set, creates a new session and returns its id when not) -
plus `GET /rag/sessions` and `GET /rag/sessions/{id}/messages`.
`knowledgeBaseApi.js`/`RagAssistantPage.jsx` now send/receive
`session_id` and restore the last active session's messages from a
per-viewer localStorage pointer on page load - a conversation genuinely
survives a refresh or a new browser tab now, with the server as the
only source of truth. 8 new live-DB tests cover round-trips, ordering
(a `BIGSERIAL seq` column, not `created_at` alone - Postgres's
`CURRENT_TIMESTAMP` is frozen for a whole transaction, and one request
writes both the user and assistant message in one transaction), and
both tenant and per-user isolation within one tenant. Verified end to
end against the running app: a genuine `/rag/query` failure (the same
sandbox network restriction noted in §14) rolls back cleanly with no
orphaned session/message left behind.

Not built: a session-list/switcher UI (the backend and API layer both
support it - `GET /rag/sessions` is real and called - but
`RagAssistantPage.jsx` only ever resumes the single most-recently-active
session on load, it doesn't yet render a picker to jump between older
ones). A real, scoped, standalone follow-up, not silently done.

**CI-wired knowledge-sync validation.** `.github/workflows/pr-checks.yml`
now runs on every PR and push to `main`: a real `pgvector/pgvector:pg15`
service container, the real `scripts/apply_migrations.py`, then
`scripts/validate_application_knowledge.py` (§8's validator - built in
Phase 2, never wired into anything that calls it automatically until
now) and the full backend pytest suite, plus a separate frontend job
(`node --test` + production build). Verified for real, not just written:
the first actual run failed with "No space left on device" (torch's
default Linux wheel drags in a ~4.6GB CUDA/nvidia-* stack this
CPU-only pipeline never uses, on top of a GitHub-hosted runner's already
partly-consumed disk) - root-caused from the real job log and fixed by
reclaiming unused preinstalled toolchains before install, not by
guessing or disabling the check.

**Orchestrator test coverage.** Added the one missing category from §6's
required set (one-tool, multi-tool, irrelevant-tools-not-firing,
missing-data, conflicting-data, tenant-isolation): a question that
plausibly triggers two tools whose facts could look contradictory (the
best-selling product is also critically low on stock) now has a test
locking in that both blocks come back verbatim, unreconciled - the
orchestrator's job is deterministic retrieval only, never picking a
"winner" between two real facts before the LLM synthesis layer sees the
question.

Cost/infrastructure impact: zero. Two new tables (no new database, no
new service), one new GitHub Actions workflow (GitHub-hosted runners are
free for this repo's usage pattern), no new external dependency.
