# CEOPRO-AI — Business Recommendations: Business & Implementation Specification

## 1. Business objective and outcomes

**What it promises:** Explain to a tenant's decision-maker which meaningful trends warrant attention, why a recommended action is plausible, and which tenant-owned records support that suggestion. Examples: an above-market price plus declining sales; negative feedback combined with decreasing units sold; growing forecast demand suggesting a stock review; or a competitor's observed price drop followed by a decline in the tenant's sales pace.

This feature must not be confused with (a) a dashboard showing raw descriptive KPIs, (b) `ai_pricing`, which recommends specific pricing adjustments, (c) `inventory_intelligence`, which calculates replenishment actions, (d) `system_alerts`, which distributes notifications, or (e) `rag_assistant`, which answers ad hoc questions. Business Recommendations correlates existing signals into **advisory hypotheses**, not automatic customer-account changes. Intended results are better prioritization, explainable decisions and verifiable follow-up—not merely a list of plausible AI-generated paragraphs.

### Business scenarios

| Situation                                             | Evidence required                                                          | Recommendation                                   | Important boundary                                                            |
| ----------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------- |
| Price above peers; recent and forecast demand decline | Product price, latest mapped competitor prices, sales windows and forecast | Investigate/adjust pricing and value positioning | Do not promise causal uplift or profit without margin data                    |
| Sentiment negative and sales falling                  | Customer reviews/sentiment and paid/valid sales                            | Investigate service or product complaints        | Low review counts, stale reviews and cross-product fallback must be disclosed |
| Competitor cuts price; own sales decline after event  | Competitor price history and comparable before/after sales windows         | Review competitor impact                         | Temporal correlation ≠ established causation                                  |
| Forecast up, price competitive                        | Forecast period, recent pace, competitors                                  | Examine replenishment opportunity                | Do not order inventory without actual stock and lead-time data                |
| No supporting signals                                 | Coverage/freshness diagnostics                                             | Show “Not enough evidence”                       | Never create fabricated recommendations                                       |

## 2. Catalog and subscription contract

**Source:** backend `src/modules/features/types/feature.catalog.ts`. The catalog registers `business_recommendations` as a **boolean** feature: access to AI-generated recommendations and actionable insights. There is no recommendation count or billing-period meter defined for this code.

**Source:** backend `src/config/production-plans.ts`, catalog version `2026-10-v2`.

| Standard plan | Published USD/month | `business_recommendations` grant |
| ------------- | ------------------: | -------------------------------- |
| Starter       |                 $55 | Not granted                      |
| Growth        |                $140 | Not granted                      |
| Enterprise    |                $350 | Not granted                      |

The code is not listed in the feature arrays of any standard plan. This is **not** proof of a permanently free or publicly available capability; the subscription layer needs to decide if and how the feature becomes available through custom plans, future plan revisions or separate paid offerings. The presence of a catalog definition is not a subscription grant. Do not silently add it to standard plans during implementation/tests.

**Required authorization contract:** if a tenant is not explicitly granted this boolean feature, the customer-facing recommendation API should deny access and hide/lock customer UI. An expired/suspended subscription or invalid membership should be handled per the same centralized access-granting rules as other CEOPRO features. AI-internal trusted workers should use separate explicitly defined service authorization, rather than making the public feature free by bypassing Node's gate.

## 3. Implementation status — frontend, Node, AI

### Frontend (`frontend(20261009-181226).zip`)

- `src/features/dashboard/pages/DashboardHomePage.jsx` renders DB-backed KPI/chart sections using `dashboardApi.getAggregate(...)`. In the inspected page, it does **not** render a live business recommendation list.
- `src/features/dashboard/components/RecommendationCard.jsx` is a static, translated component referencing `dashboard.recommendation.*`; it neither calls a recommendation API nor has a verified details action. The audit found no current use of this component in dashboard screens.
- `src/features/ai-advisor/api/advisorApi.js` has stubbed `listSessions`, `chat`, and `evidenceTrail` handlers returning local shapes; `src/features/ai-advisor/pages/AiAdvisorChatPage.jsx` is placeholder text; `RecommendationActionButtons.jsx` is placeholder UI.
- `src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx` has a **separate** AI pricing-recommendation feature. It is not the customer-facing implementation of `business_recommendations`.

### Node backend (`CEOPRO-backend-dashboard-diagnostics.zip`)

- `src/modules/dashboard/route/dashboard.route.ts`: current `GET /companies/:companyId/dashboard` with authentication and tenant requirements.
- `src/modules/dashboard/service/dashboard.service.ts` and `repo/dashboard.repo.ts`: dashboard KPI aggregation; no `business_recommendations` entitlement-checked recommendation response or AI proxy identified.
- `src/modules/features/types/feature.catalog.ts`: canonical boolean feature definition.
- `src/modules/features/README.md`: feature module is the central access/usage service; a feature catalog definition does not implement a business workflow.
- No dedicated authenticated `business_recommendations` route/controller/service/repository, API response contract, UI wiring or tested entitlement gate found in this snapshot.

### AI team (`ai codebase latest(1).zip`)

- `src/ai/insights/cross_signal.py`: deterministic rules and scoring for product-level recommendations.
- `src/ai/insights/causal_chain.py`: competitor-price-drop event timing versus before/after sales pacing.
- `src/ai/insights/pipeline.py`: tenant-scoped SQL signal collection and combined ranking.
- `src/ai/dashboard/recommendations.py`: translates ranked insights into a dashboard-friendly `product_id`, `category`, `priority`, `message` response; defaults to top 3.
- `src/ai/main.py`: real `GET /dashboard/recommendations?limit=...` (bounds 1–20) with JWT-based tenant context and an application database role.
- Tests exist, notably `src/ai/tests/test_dashboard_recommendations_integration_db.py`, `test_insights_cross_signal.py`, `test_insights_causal_chain.py`, and `test_insights_pipeline_integration_db.py`. Static existence does not establish the currently deployed environment or test pass state.

**Bottom line:** An AI recommendation engine and direct FastAPI endpoint exist. The inspected React/Node customer pathway does not expose that engine as a properly entitled, evidenced, persisted Business Recommendations feature.

## 4. Architecture and data flow

**Proposed authorized customer path** (not current verified implementation):

1. React requests tenant recommendations using the established authenticated CEOPRO API and loading/error/empty states.
2. Node validates identity, membership and active subscription, then checks `business_recommendations` entitlement.
3. Node forwards an authorized tenant-scoped request to the AI service or reads a trusted materialized result using a documented contract.
4. AI reads the allowed tenant's business signal records under the proper RLS role/context, calculates explainable rule-based findings, and returns evidence-bearing structured recommendations.
5. Node verifies references, maps statuses and provides localized evidence/links to UI; optionally persists snapshots or action tracking in an explicitly owned table.
6. User can inspect evidence, dismiss or acknowledge a recommendation, or navigate to the owning specialist feature. AI does not autonomously edit prices, stock, or customer data.

**Existing AI direct path:** `GET /dashboard/recommendations` → `get_tenant_context` (Bearer JWT with tenant_id and user_id claims) → `db.app_role_connection` → `get_top_recommendations(...)` → `generate_insights_for_tenant(...)` → read-only signal queries. It uses tenant context but **does not establish a Node subscription-entitlement check**. JWT access alone is not a customer subscription grant.

## 5. Database inputs and joins (actual AI signal sources)

| Input                            | Table(s) and join/filter                                                                                                  | Use                                                                 | Owning subsystem                        |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------- |
| Active product catalog           | `products`, filter `tenant_id`, `deleted_at IS NULL`                                                                      | Product identity and current price                                  | Product Management/ingestion            |
| Competitor price position        | `competitor_product_mappings` joined to `competitor_prices` by tenant and mapping; most recent observed price per mapping | Market-relative price gap                                           | Competitor Management/market collection |
| Own recent sales                 | `invoice_items` joined to `invoices` by `(tenant_id, invoice_id)` and grouped by product                                  | Two 30-day unit-sales windows; daily series for event timing        | Sales/invoicing                         |
| Product sentiment                | `reviews` joined to `sentiment_results`, product `subject_type = 'PRODUCT'`                                               | Positive vs negative customer feedback                              | Reviews/Sentiment Analysis              |
| Business-wide sentiment fallback | Business-subject `reviews` joined to `sentiment_results`                                                                  | Fallback when product review sentiment is absent                    | Reviews/Sentiment Analysis              |
| Demand                           | Most recently created `demand_forecasts` per product                                                                      | Expected demand compared to recent sales pace over matching horizon | Demand Prediction                       |
| Competitor price-drop evidence   | Historical `competitor_prices`, mapping/global competitor relationships                                                   | Price events and before/after sales correlation                     | Competitor Management                   |

**Important data gap:** The production Data Connections file-upload worker populates `transactions` and `products`; the inspected AI Business Recommendations engine calculates sales pace using **`invoices` and `invoice_items`**, not `transactions`. A tenant with successfully imported transaction files but no invoices could get _no sales-based recommendations_ despite actual sales data. Reconcile sources and semantics before promising complete analytics. Do not simply sum invoices and transactions without de-duplication and an authoritative sales contract.

The engine's use of `recommendation_outcomes` should **not** be assumed: that Prisma table currently supports forecast/evidence outcomes; this read-only AI recommendation path does not write these generic recommendations into it.

## 6. Calculations and thresholds — reproducible rules

The AI engine is **rule-based and explainable**, not a trained uplift/probability predictor. Thresholds below are implementation defaults from the inspected AI snapshot and may be environment-overridden where shown.

### Price gap

For a product, take the latest available scraped competitor price **per mapped competitor**, then average those prices:

`average_competitor_price = AVG(latest_scraped_price_per_mapping)`

`price_gap_pct = 100 × (own_current_price − average_competitor_price) / average_competitor_price`

The default over/underpricing threshold is **10%** (`INSIGHTS_PRICE_GAP_THRESHOLD_PCT`). Guard against zero prices, stale observations, wrong product mappings, different package sizes, taxes and currency mismatches. The inspected price-gap SQL does not visibly perform a comprehensive per-observation FX/unit normalization, so cross-currency price comparisons are a high-priority validation issue.

### Sales movement

Use comparable 30-day windows (`SALES_TREND_WINDOW_DAYS = 30`):

`trend_pct = 100 × (units_sold_recent_30d − units_sold_previous_30d) / units_sold_previous_30d`

Default meaningful trend threshold **±15%**. The AI implementation returns **undefined (`None`)** when the prior period has zero sales; it must not turn missing history into a 0% trend. Check invoice status, cancellation/refund inclusion and time-zone cutoffs against the intended business definition.

### Sentiment

Aggregate product-level sentiment using weighted counts of provider probability outputs:

`sentiment_score = [Σ(count × avg_positive_probability) − Σ(count × avg_negative_probability)] / Σ(count)`

The default negative threshold is **≤ −0.15** (`INSIGHTS_SENTIMENT_THRESHOLD`). Product-level review results take priority; the engine falls back to business-wide sentiment if product-specific sentiment is unavailable. A fallback signal is lower-specificity evidence and must be clearly labeled. Review volume, period, language, staleness and model coverage require quality checks.

### Forecast direction

Project recent sales pace across the forecast's actual horizon:

`current_pace_projection = (recent_30d_units / 30) × forecast_horizon_days`

`forecast_trend_pct = 100 × (forecast_expected_demand − current_pace_projection) / current_pace_projection`

Default meaningful trend threshold **±15%**. If recent units or valid forecast horizon are absent, return undefined rather than dividing by zero. This is a comparison of forecast against recent pace, not the same as a forecast's own period-over-period growth and not a probability of growth.

### Rules, ranking and limit

- A product's first matching high-priority rule wins (at most one snapshot insight per product).
- Example: overpriced + falling sales + falling forecast → pricing insight with internal heuristic `confidence = 0.9`.
- Other patterns include overpriced + falling sales (`0.7`); overpriced + negative sentiment (`0.7`); negative sentiment + falling sales (`0.8`); underpriced + healthy demand (`0.6`); rising forecast (`0.5`); falling forecast (`0.4`).
- The event-timing detector finds competitor price drops (default ≥10%), then checks 14-day before and after sales periods. A ≥15% post-event decline may yield an insight. A stronger pattern (competitor drop ≥20% and sales decline ≥30%) is ranked higher (`0.85` vs `0.55`). **Event-timing correlation is not scientific proof of causality.**
- The combined pipeline ranks by the heuristic confidence field and returns up to `max_insights`; the AI dashboard wrapper defaults to **3**, while its endpoint allows `limit` 1–20.
- The wrapper converts confidence into internal priority words: `high` for ≥0.8, `medium` for ≥0.5, `low` otherwise. **These confidence values are engineering weights, not calibrated probability scores or guaranteed impact.**
- No qualifying inputs should produce `[]`, not hallucinated advice.

## 7. Recommendation API and presentation contract

**Existing AI endpoint:** `GET /dashboard/recommendations?limit=3`, Bearer JWT, application-role tenant context. Successful top-level shape: `{ "recommendations": [{ "product_id", "category", "priority", "message" }] }`. Categories mapped by `src/ai/dashboard/recommendations.py`: Pricing, Customer Feedback, Demand, Competitor Activity.

**Gaps for a production CEOPRO customer API:** a Node gateway/contract, feature entitlement, stable `recommendation_id`, explicit `as_of` timestamp, source references, observation freshness, period, localization-safe structured message template, status/acknowledgement fields, deduplication identity, and navigation target. Do not fabricate these fields in the frontend when the source cannot provide them.

**Recommended UI:** recommendation title, affected product, category, priority, concise explanation, underlying evidence (readable numerator/denominator and dates), data-confidence/freshness caveat, action button (investigate; no automatic destructive action), and an accurate empty/partial/stale/error state. Must support English/Arabic and RTL, using structured localized templates rather than relying solely on hard-coded English AI messages.

## 8. Ownership and persistence policy

| Concern                                 | Responsible module/team                                           | Current state                                                       |
| --------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| Entitlement, custom plan access         | Node Features/Subscriptions                                       | Catalog available; no customer recommendation gate identified       |
| Source data truth                       | Product, invoicing, competitor, forecasting, sentiment subsystems | Input tables and producers exist, with coverage differences         |
| Signal derivations and ranking          | AI `insights/*` and `dashboard/recommendations.py`                | Implemented in source                                               |
| Read-only recommendation fetch          | AI FastAPI                                                        | Implemented directly; no verified Node customer proxy               |
| API response ownership and eligibility  | Node recommendation module (target)                               | Not implemented/verified                                            |
| Customer recommendation cards           | React dashboard or dedicated recommendations page (target)        | Static/unused recommendation card; Advisor screen stub              |
| Recommendation feedback/action outcomes | Product feature owner with audit and evidence                     | No generic durable lifecycle identified                             |
| `recommendation_outcomes` table         | Forecast/evidence domain                                          | Exists but must NOT be repurposed without schema/ownership decision |

**Decisions required:** Should recommendations be on-demand only or persisted as reproducible snapshots? How long are they valid? How should customer acknowledgments and measured outcomes be stored? Which role can see recommendations and which can act on them? Avoid duplicating evidence already owned by Pricing/Forecasting.

## 9. Data quality, privacy and security

- Tenant identity must be validated at Node, carried securely into AI, enforced by RLS/database app-role context, and applied to every join/subquery and evidence lookup.
- Deny unauthorized tenant, forged JWT, expired membership/subscription and absent `business_recommendations` grant. AI's valid JWT-only direct endpoint is **not** proof of subscription enforcement.
- Restrict all recommendation endpoints to safe, bounded `limit` and date-range arguments; prevent cross-tenant product IDs or foreign evidence references.
- Price gap must compare genuinely equivalent currencies, quantities, product variants and observation dates.
- Sales should use canonical valid sales including documented refunds/cancellations and should reconcile invoice-driven versus transaction-driven ingestion.
- Sentiment must disclose missing product-level data and business-wide fallback.
- Forecasts must be current and horizon-complete; no fake recommendation on missing evidence.
- The word “confidence” should not be presented as a validated statistical probability. Priority labels are currently heuristic.
- Customer decisions need audit and a reversible/approved workflow; advice should not automatically change product price, inventory or customer account data.
- Recommend actionable findings only with enough supporting inputs; otherwise communicate data-readiness gaps.

## 10. Key gaps — prioritized

| Priority | Finding                                                                              | Required action                                                                                              |
| -------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Critical | No standard plan grants `business_recommendations`                                   | Define eligibility and decide whether to assign to plans/custom plans; preserve explicit entitlement rules   |
| Critical | No Node-to-AI customer-facing, entitlement-gated recommendations path                | Implement authorized route/controller/service/client and typed contract only after confirming product policy |
| High     | AI endpoint accepts JWT but does not verify Node subscription feature                | Prevent direct customer bypass; centralize authorized access or enforce trusted entitlement context          |
| High     | Frontend recommendation card static/unused and Advisor pages stubbed                 | Wire real API and truthful data states without replacing current dashboard                                   |
| High     | AI sales signal uses `invoices`/`invoice_items`; file ingestion feeds `transactions` | Reconcile authoritative sales sources, payment/status and import dedupe semantics                            |
| High     | Price comparisons may combine incompatible currencies/products                       | Validate FX/unit/equivalent mapping and freshness before recommending pricing moves                          |
| High     | No evidence identifiers/freshness/lineage in response                                | Return verifiable source refs, time windows and data-coverage metadata                                       |
| High     | AI insights are read-only; no generic durable recommendation/action loop             | Define snapshot, acknowledgement, dismissal, outcomes and audit semantics before building workflows          |
| Medium   | Sentiment fallback can look product-specific                                         | Surface review sample sizes and fallback type; test partial data                                             |
| Medium   | Heuristic confidence may be mistaken for accuracy                                    | Label internal priority explicitly and measure real precision/impact separately                              |
| Medium   | English message templates in AI result                                               | Localization-safe recommendation codes, parameters and translations                                          |
| Medium   | Not enough information for recommendation                                            | Show empty/insufficient-data state with ingestion setup guidance                                             |
| Medium   | Trigger/freshness not defined                                                        | Choose on-demand/cache/scheduled generation with stale-data invalidation and bounded cost                    |
| Medium   | Product action buttons placeholder                                                   | Link to authorized product/competitor/forecast detail, not speculative price changes                         |

## 11. Required E2E and integration acceptance tests

The following 25 acceptance checks form the business test plan; extend the existing Playwright/API/Prisma/AI pytest infrastructure, not create a parallel test framework.

- [ ] **01. Plan access:** Starter/Growth/Enterprise correctly deny the ungranted feature by default; custom plans allow it only when assigned.
- [ ] **02. Tenant authorization:** unauthenticated/expired/falsified JWT and unauthorized membership rejected.
- [ ] **03. Direct AI endpoint policy:** valid AI JWT cannot become a paid-feature bypass through customer exposure.
- [ ] **04. Empty database:** zero insights and useful onboarding guidance, not fabricated data.
- [ ] **05. Price gap:** correct latest-per-mapping average and ≥10% threshold boundaries.
- [ ] **06. Cross-currency/units:** reject or normalize mismatched competitors; no unsafe comparable price.
- [ ] **07. Sales trend:** two comparable 30-day invoice windows and correct denominator handling.
- [ ] **08. Ingestion mismatch:** transactions-only tenant is not falsely reported as having no sales without disclosure.
- [ ] **09. Sentiment:** product-only scores, business-wide fallback and missing probabilities handled correctly.
- [ ] **10. Forecast:** latest forecast and horizon-adjusted recent-sales pace calculation.
- [ ] **11. Multi-signal rule:** produce insight from verified combination; no insight from isolated insufficient signal unless the explicitly documented derived exception applies.
- [ ] **12. Event timing:** competitor price-drop event followed by measured 14-day sales-pacing change; no unsupported causal claim.
- [ ] **13. Category/priority mapping:** return Pricing/Customer Feedback/Demand/Competitor Activity and high/medium/low labels.
- [ ] **14. Ranking/limit:** stable ordering, default 3, parameter boundaries 1..20, graceful no-results.
- [ ] **15. Evidence lineage:** product, price mapping, review sample, invoice window and forecast refs belong to tenant.
- [ ] **16. Freshness:** stale competitor price or old forecasts marked/filtered per approved rule.
- [ ] **17. Duplicate conflicting inputs:** no duplicate recommendations caused by duplicate imports or mappings.
- [ ] **18. Cross-tenant isolation:** Tenant A cannot see Tenant B's recommendation texts, IDs or source evidence.
- [ ] **19. Node/AI failure:** timeout, 502, malformed response, empty response, retries and error status accurately surfaced.
- [ ] **20. Real React UI:** dashboard/recommendation page shows only actual backend results; static card does not masquerade as live data.
- [ ] **21. Locale/RTL:** structured messages and details render appropriately in English and Arabic.
- [ ] **22. Action/navigation:** recommendations link to owning specialist screen with valid tenant-scoped product context.
- [ ] **23. User decision and audit:** acknowledgement/dismissal/outcome state tested only if a supported lifecycle exists; otherwise BLOCKED, not PASS.
- [ ] **24. AI deterministic tests:** reuse existing pytest logic, including missing-signal rules and edge thresholds.
- [ ] **25. Live integration:** opt-in call to actual Python API with dedicated test DB, restricted role and evidence-backed output; don't claim deployed success from source inspection.

### Example deterministic fixture

Tenant owns an Espresso Machine with price 100 JOD. Comparable latest competitor price is 80 JOD: price gap = `(100−80)/80 ×100 = 25%`. Prior 30-day sales = 20 units and recent 30-day sales = 10 units: sales trend = `(10−20)/20 ×100 = −50%`. If forecast also declines relative to the matched current pace, the high-priority pricing rule should fire with correct product attribution. This example is not a live CEOPRO record and must be created inside a safe test tenant.

### Required test modes and diagnostics

1. **Pure Python rule tests:** deterministic thresholds, missing data, ranking and confidence-label translation.
2. **AI database integration:** real isolated PostgreSQL with `AI_TEST_DATABASE_URL`, restricted role, fixture rollback/cleanup and RLS assertions; use existing AI tests.
3. **Node API integration:** tenant authentication, feature entitlement, input validation and AI error handling, provider-simulated only when explicitly labeled.
4. **Browser E2E:** real frontend + Node + safe test DB; no mock recommendation API responses in true E2E.
5. **Live AI opt-in:** actual hosted Python endpoint, with controlled fixtures and explicit environment safety checks; mark BLOCKED if unavailable.

For each test record PASS/FAIL/SKIP/BLOCKED/ERROR, product and tenant IDs, checked signals/formulas, plan/grant, data timestamp, actual vs expected result, relevant API/SQL evidence and likely failure owner. Never run fixture writes against the Render production database or disable RLS.

## 12. Definition of done and release decision

**Business readiness:** Plan eligibility documented; no customer without a valid grant can access recommendation data; recommendation is presented as advice with verifiable evidence and no unsupported causation; meaningful insufficient-data states exist; a customer can navigate to relevant details safely.

**Engineering readiness:** Authenticated and entitled Node route with typed AI client; tenant isolation at each read; source formula reconciliation and comparable data; actual React integration; localization; bounded/cached computation where appropriate; source freshness; auditable results if persisted; deterministic, integration, E2E and optional live AI tests passing in a safe environment.

**Release status from inspected snapshots:** **Not yet production-complete.** The AI rule engine and its tenant-scoped FastAPI dashboard endpoint are real source implementations; subscription entitlement, customer-facing Node/React wiring, evidence-ready responses and authoritative sales-source reconciliation are unresolved. Live behavior is unverified.

---

## File-by-file source index

**Backend**

- `src/modules/features/types/feature.catalog.ts` — canonical boolean feature.
- `src/config/production-plans.ts` — absence of standard-plan grant.
- `src/modules/features/README.md` — central entitlement semantics.
- `src/modules/dashboard/route/dashboard.route.ts` — existing authenticated dashboard route only.
- `src/modules/dashboard/repo/dashboard.repo.ts` — existing dashboard KPI aggregation.
- `prisma/schema.prisma` — input models and `recommendation_outcomes`/`evidence_records` distinction.

**Frontend**

- `src/features/dashboard/pages/DashboardHomePage.jsx` — actual dashboard composition.
- `src/features/dashboard/api/dashboardApi.js` — existing dashboard aggregate API.
- `src/features/dashboard/components/RecommendationCard.jsx` — static legacy card.
- `src/features/ai-advisor/api/advisorApi.js` — stub API.
- `src/features/ai-advisor/pages/AiAdvisorChatPage.jsx` — placeholder UI.
- `src/features/ai-advisor/components/RecommendationActionButtons.jsx` — placeholder actions.

**AI**

- `src/ai/main.py` — `GET /dashboard/recommendations` and JWT tenant context.
- `src/ai/dashboard/recommendations.py` — presentation shape and priority labels.
- `src/ai/insights/cross_signal.py` — business rules, thresholds and rankings.
- `src/ai/insights/pipeline.py` — tenant data SQL joins and computed signals.
- `src/ai/insights/causal_chain.py` — before/after price-event signal correlation.
- `src/ai/tests/test_dashboard_recommendations_integration_db.py` and `src/ai/tests/test_insights_*` — test sources, not proof of current execution.
