# CEOPRO-AI — Feature 03: Market Perception Index (`market_perception`)

## 1. The business problem

A business owner needs to know not only whether products sell, but _how customers perceive the business, individual products, and competitors_. Prices and sales alone do not reveal complaints about quality, delivery, service, or product durability.

### Business scenario — clothing store

Your shop sells jackets for JOD 35; a rival offers them for JOD 30. Your reviews describe good durability and service; the cheaper competitor's reviews describe poor durability. An accurate perception index helps you **investigate whether reputation justifies your pricing**. It must not automatically recommend changing the price or imply that the sample is statistically representative of all customers.

**Decisions supported:** prioritize customer-service improvements; find poorly perceived products; investigate competitors' reputation; detect changes in customer feedback; explain why a score changed.

**Decisions not automatically supported:** precise market share; market presence/visibility; actual sales volume; causal conclusions; optimal price; financial forecasts. These belong to different CEOPRO domains.

## 2. Intended user experience

| View       | Business question                             | Proposed presentation                                                             |
| ---------- | --------------------------------------------- | --------------------------------------------------------------------------------- |
| Business   | How do customers perceive my company overall? | MPI 0–100, review count, label mix, status, last refreshed, explanation/evidence  |
| Product    | What feedback is this product receiving?      | Product-specific index, representative feedback themes, change only if comparable |
| Competitor | How is a tracked competitor perceived?        | Competitor score, sentiment label, sample size and source coverage                |

Use _positive / neutral / negative_ as qualitative labels **alongside** a numeric index where available. Avoid interpreting 50 as “good”: it is the neutral midpoint or potentially low-information result. No-data must show **Unavailable**, never a fabricated 0 or 50.

**Evidence disclosure:** show usable review count, data period, eligible source types, whether a review sample is sufficient, model/revision if provided, and an explanation. If the user selects a date period, make clear whether it actually applies to MPI.

## 3. Actual implementation — frontend

- `frontend/src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx` has a `marketPerception` competitor-table column, rendered using `ToneBadge` with `positive`, `neutral`, `negative` or `—`.
- **The numeric `marketPerceptionScore` delivered by the backend is not displayed** in that table.
- There is **no discovered standalone Market Perception page** for business-wide or product-level scores in the inspected frontend.
- The existing Market Intelligence Overview route has `<FeatureRouteGuard featureCodes="market_intelligence">`. There is no separate `market_perception` guard protecting the embedded competitor perception.
- `frontend/src/features/market-intelligence/api/marketIntelligenceApi.js` requests the Market Intelligence Overview; no dedicated frontend MPI API method was found in that module.
- Export PDF: `frontend/src/features/market-intelligence/pdf/MarketIntelligencePdfDocument.jsx` exports the qualitative `marketPerception` label, not the numeric index.

## 4. Actual implementation — backend

### Direct MPI API

`GET /features/mpi/summary?subject_type=COMPETITOR&subject_id=<UUID>`

- Mounted in `backend/src/app.ts`; authenticated/tenant-scoped via `src/modules/mpi/route/mpi.route.ts`.
- The accepted `subject_type` values are `BUSINESS`, `PRODUCT`, and `COMPETITOR`; `subject_id` is syntactically optional even for a product/competitor (requires review).
- **`requireFeatureAccess("market_perception")` is commented out** in `mpi.route.ts`.
- `src/modules/mpi/repo/mpi.repo.ts` selects up to **100** most recent `reviews` with tenant ID, allowed source/safety status, nonempty text, and collection method in `PUBLIC_API`, `PUBLIC_FEED`, or `MANUAL`. For identified PRODUCT/COMPETITOR requests it filters by product or competitor ID. **For `BUSINESS`, it currently does not filter `subject_type` at all**, which can mistakenly include a tenant’s product and competitor reviews in its own business reputation score; unlike the AI FastAPI pathway, which filters `BUSINESS` explicitly.
- `src/modules/mpi/client/mpi.client.ts` calls the hosted Gradio **models** service operation `market_intelligence`, with positional inputs `[reviews, subject_type, subject_id, country_code, as_of]`. The backend sends `country_code=null` and `as_of=null`.
- AI output is validated for index range **0–100**, labels, confidences and evidence explanation. `src/modules/mpi/service/mpi.service.ts` writes an `evidence_records` row (metric `market_perception_index`) and returns `OK` or `UNKNOWN`.
- If there are no eligible reviews, the backend returns `UNKNOWN` without calling Gradio. Upstream errors are mapped to external-service errors.

### Embedded competitor MPI in Market Intelligence

- `backend/src/modules/market-intelligence/service/market-int.service.ts` enriches **each** competitor in the Market Intelligence response by calling `getMpiSummary`.
- A successful result produces `marketPerceptionScore` (0–100) and `marketPerception` qualitative label, based on the **dominant** positive/neutral/negative count; ties return null.
- Errors are caught per competitor and replaced with null fields, so the rest of the overview can still render.
- The page's `periodDays` filter **is not passed** to MPI; the selected 30/90-day Market Intelligence period is not the perception observation window.
- `backend/src/modules/market-intelligence/route/market-int.route.ts` also has no backend `market_intelligence`/`market_perception` entitlement middleware; frontend route guarding does not secure backend APIs.
- Each page refresh can re-run competitor MPI and create additional evidence records; no reusable cached snapshot or deduplication was identified in these request paths.

### Important implementation risk

`getMpiSummary()` currently derives the returned `sample_size.status` as `OK` whenever upstream `mpi.status` is `OK`, without inspecting upstream `mpi.sample_size` (which the Zod schema accepts as `unknown`). This needs contract tests for the hosted model's real `LOW_SAMPLE_SIZE` behavior, so a thin sample cannot be mistakenly displayed as reliable.

## 5. Actual AI-team code vs hosted Gradio service

The latest AI-team ZIP contains a **separate Python/FastAPI MPI implementation**:

- `ai/src/ai/main.py`: `GET /mpi/summary`.
- `ai/src/ai/mpi/data_access.py`: loads `reviews` **joined** to existing `sentiment_results`, i.e., only reviews with sentiment analysis.
- `ai/src/ai/mpi/scoring.py`: computes weighted MPI.
- `ai/src/ai/mpi/cold_start.py`: minimum sample policy.
- `ai/src/ai/mpi/pipeline.py`: evaluates subject-specific reviews, calculates index and writes evidence.
- `ai/src/ai/mpi/evidence.py`: **writes `evidence_records`**, not `reviews` or `sentiment_results`.

**Do not conflate these paths:** the current Node backend calls **Gradio**, not the Python `GET /mpi/summary` endpoint. The hosted Gradio model's implementation is **not present** in the uploaded AI ZIP. The local Python scoring formula below is confirmed for the FastAPI pathway; its exact match to hosted Gradio must be contract-tested rather than assumed.

## 6. Scoring algorithm in the supplied Python MPI implementation

Per review:

- Sentiment signal: `positive_probability - negative_probability` (−1 to +1) from `sentiment_results`.
- Recency weight: `0.5 ^ (age_days / 90)` by default (90-day half-life, configurable).
- Source reliability: `PUBLIC_API=1.00`, `PUBLIC_FEED=0.85`, `MANUAL=0.60` (configurable source code constants).
- Entity relevance: currently `1.00` for explicitly linked reviews; unlinked reviews are excluded, not fuzzy-scored.
- Combined weight = recency × reliability × relevance.

**Weighted sentiment:** `sum(sentiment_signal × combined_weight) / sum(combined_weight)`.

**Volume confidence:** `min(1, analyzed_review_count / 20)` by default (configurable).

**Index:** `MPI = 50 + 50 × weighted_sentiment × volume_confidence`, rounded to two decimals, from 0 to 100.

If no usable contributions exist, **UNKNOWN**, not 0 or 50. The Python pipeline flags `LOW_SAMPLE_SIZE` for fewer than **5** analyzed reviews (environment-configurable), although it may still compute a provisional index. Cross-subject comparison defaults to a **10-review floor per side** and refuses to return a difference under that threshold.

**Interpretation example:** 20 recent reliable uniformly positive reviews yield an index near 100. A single highly positive review is pulled close to 50 by volume confidence and must be flagged as weak evidence. These example outcomes describe the **Python algorithm**, not a verified Gradio output.

## 7. Data ownership — which tables need feeding?

| Table                                                 | Why it matters                                                                            | Actual ownership/path                                                                                                                                  |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `reviews`                                             | Raw source, subject association, review date, collection method, safety and policy status | AI collection/scraper pipeline or separately accepted feedback imports. MPI **reads** it.                                                              |
| `sentiment_results`                                   | Classified sentiment and positive/negative probabilities                                  | AI sentiment pipeline **writes** it; Python MPI directly reads it. Backend Gradio MPI **does not first join this table** in its review-selection path. |
| `evidence_records`                                    | MPI result, explanation, confidence and provenance                                        | Both the AI FastAPI MPI and the CEOPRO Gradio adapter can write this table **via separate request paths**. Avoid duplicate/unattributed evidence.      |
| `tenant_competitors`                                  | Tenant ownership and tracked competitor linkage                                           | Competitor discovery/management pipeline.                                                                                                              |
| `global_competitors`                                  | Global competitor identity/country context                                                | Competitor management/discovery pipeline.                                                                                                              |
| `products`                                            | Products eligible for product-specific MPI                                                | Business product ingestion.                                                                                                                            |
| `companies`                                           | Tenant identity and country context                                                       | Backend tenant/onboarding.                                                                                                                             |
| `subscriptions`, `plans`, `plan_features`, `features` | Entitlements                                                                              | Backend billing/catalog; not perception input.                                                                                                         |

**No new sales, invoice or inventory template is required** to calculate market perception. The essential input is **permitted, sufficiently numerous, subject-linked customer reviews**. If these are unavailable for a business, improve compliant collection or add an explicit feedback import later; do not invent reviews or treat product sales as opinions.

## 8. Exact flow to verify

### Current CEOPRO flow

`Review scraper/collector → reviews (PostgreSQL) → CEOPRO backend (up to 100 eligible texts) → hosted Gradio market_intelligence → backend validates results → evidence_records → /features/mpi/summary or Market Intelligence competitor enrichment → frontend label`.

### Independent AI FastAPI path

`Review collection → reviews → sentiment pipeline → sentiment_results → Python MPI pipeline → evidence_records → GET /mpi/summary`.

**Outstanding ownership question:** Confirm whether hosted Gradio writes to PostgreSQL directly in addition to CEOPRO's evidence writer. The provided AI ZIP does not establish the hosted service's database side effects.

## 9. Subscription and commercial decision

- `market_perception` exists in feature catalog as boolean/lifetime.
- It is **not included in Starter, Growth or Enterprise** in the production plan manifest, with no separate price configured.
- Production plan documentation explicitly describes it as a **deferred launch feature** until entitlement gates and UX are ready.
- Despite this, `GET /features/mpi/summary` has its `market_perception` middleware **commented out**, and Market Intelligence Overview currently enriches competitors with MPI without checking that separate feature.

**Recommended launch choice:** First decide if `market_perception` is bundled into Growth/Enterprise or is a separately priced add-on. **Until that decision, enforce a server-side feature gate and hide/omit MPI enrichment for unauthorized tenants.** Never silently change active plan entitlements; use the project's production-plan versioning/rollout rules. Track provider compute costs and potential need for caching before assigning an add-on price.

A reasonable commercial option is Growth/Enterprise bundle with explicit entitlements after verification, because these plans already include `market_intelligence` and sentiment-analysis allowances. This is a **recommendation**, not existing access.

## 10. Business acceptance scenarios

1. **Happy path:** ≥5 eligible competitor-linked analyzed reviews, hosted model returns valid `OK`, UI shows the correct label, count and numeric score (once displayed), evidence is stored exactly as intended.
2. **No reviews:** `UNKNOWN`, score unavailable, no invented reputation conclusion.
3. **Thin sample:** 1–4 usable reviews produce unavailable/low-confidence UI status (per agreed contract), not a confident badge.
4. **Source quality:** recent, permitted public API reviews contribute appropriately; unsafe or disallowed sources are excluded.
5. **Subject filtering:** two products/competitors in one tenant yield independent results; BUSINESS must not include COMPETITOR reviews; missing or foreign IDs cannot produce a mislabeled result.
6. **Tenant isolation:** tenant A cannot read or use tenant B's reviews, competitor identities, scores or evidence.
7. **External AI outage:** direct endpoint returns a controlled 502-like error; Market Intelligence page remains usable with MPI unavailable.
8. **Period expectations:** changing the Overview 30/90-day filter never falsely implies MPI was recalculated for that window.
9. **Repeat refresh:** repeated page views do not create unlimited duplicate evidence or unpredictable bills.
10. **Plan gate:** Starter or another tenant lacking `market_perception` cannot invoke or receive the restricted score; Growth/Enterprise behavior reflects the _actual_ chosen launch policy.
11. **Arabic/English:** labels, help text, confidence caveats and RTL presentation are correct.
12. **Export parity:** PDF includes only validated/authorized perception fields with the same unavailable semantics as the UI.

## 11. Implementation and testing checklist

### Existing capabilities to verify end-to-end

- [ ] `reviews` have correct tenant, subject, subject_id, dates, source/safety statuses, de-duplication and substantive feedback text.
- [ ] `sentiment_results` exists where Python MPI pipeline is expected to read it, with valid probabilities.
- [ ] AI workers have actually processed reviews (not merely contain code capable of writing them).
- [ ] Gradio `market_intelligence` returns a shape accepted by the backend Zod schema.
- [ ] The backend persists coherent evidence with correct tenant, subject, metric, confidence, explanation and timestamps.
- [ ] One competitor with sufficient samples shows a positive/negative/neutral label correctly; ties are null.
- [ ] Direct `GET /features/mpi/summary` returns expected subject-specific data.

### Gaps to close

- [ ] Decide feature availability/price and implement backend `requireFeatureAccess("market_perception")`.
- [ ] Apply **separate** entitlement to competitor MPI enrichment inside `/market-intelligence` (not only to direct MPI URL).
- [ ] Fix the `BUSINESS` review query so it **only** includes reviews with `subject_type=BUSINESS` (or an explicitly documented aggregate policy), not competitor/product reviews by accident.
- [ ] Validate subject IDs and verify tenant ownership, require IDs for `PRODUCT` and `COMPETITOR` (unless an explicitly documented aggregate mode exists).
- [ ] Define and verify the exact hosted model low-sample contract; preserve model `sample_size` truthfully.
- [ ] Show numeric `marketPerceptionScore` and evidence/sample count where UX calls for it.
- [ ] Implement or explicitly defer a business/product-level MPI view.
- [ ] Avoid multiplying model calls/evidence records on each overview request; introduce justified caching/snapshot semantics.
- [ ] Display an MPI-specific as-of/review-window indicator; do not borrow the Market Intelligence period label.
- [ ] Verify failure modes, timeouts, and idempotent evidence behavior.
- [ ] Add bilingual translations for any newly surfaced text and parity tests for PDF export.

### Test infrastructure

For deterministic integration tests, create controlled tenant-scoped `companies`, `products`, `tenant_competitors`, `reviews`, and (for Python MPI) `sentiment_results` fixtures. Call the real backend on a dedicated test database. For Gradio contract tests, use a strict expected payload and opt-in external live tests; do not claim a mocked provider result proves a live AI pipeline. Compare API, persisted `evidence_records` and frontend. Log `PASS/FAIL/BLOCKED`, sample eligibility/count, subject ID, score, model status, and a redacted reason without logging raw private customer feedback unnecessarily.

## 12. Files inspected (source traceability)

**Frontend:** `src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx`, `api/marketIntelligenceApi.js`, `hooks/useMarketIntelligenceOverview.js`, `pdf/MarketIntelligencePdfDocument.jsx`, `src/app/router/index.jsx`.

**Backend:** `src/app.ts`, `src/modules/mpi/{route,controller,service,repo,client,types}`, `src/modules/market-intelligence/{route,controller,service,repo}`, `src/modules/features/types/feature.catalog.ts`, `src/config/production-plans.ts`, `prisma/schema.prisma`, `tests/billing/production-plans/PRODUCTION_PLAN_BOOTSTRAP.md`.

**AI team:** `src/ai/main.py`, `src/ai/mpi/{scoring,cold_start,data_access,pipeline,evidence}.py`, `src/ai/tests/test_mpi_{scoring,pipeline,integration_db}.py`.

> This document is a code-backed specification and audit; no live tenant database, hosted Gradio model deployment, or frontend-in-browser E2E run was verified here.
