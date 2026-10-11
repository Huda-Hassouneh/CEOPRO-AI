# CEOPRO-AI — Feature 02: Market Intelligence

W

## Contents

1. [Business problem and intended outcomes](#1-business-problem-and-intended-outcomes)
2. [Real-world business scenarios](#2-real-world-business-scenarios)
3. [What the current UI actually displays](#3-what-the-current-ui-actually-displays)
4. [Database ownership and data prerequisites](#4-database-ownership-and-data-prerequisites)
5. [Metrics and calculation contract](#5-metrics-and-calculation-contract)
6. [API and end-to-end data flow](#6-api-and-end-to-end-data-flow)
7. [Feature and plan boundaries](#7-feature-and-plan-boundaries)
8. [Data-quality, empty-state and trust policy](#8-data-quality-empty-state-and-trust-policy)
9. [Acceptance scenarios](#9-acceptance-scenarios)
10. [Technical risks and implementation priorities](#10-technical-risks-and-implementation-priorities)
11. [End-to-end verification checklists](#11-end-to-end-verification-checklists)
12. [Calculation and ownership verification register](#12-calculation-and-ownership-verification-register)

---

## 1. Business problem and intended outcomes

**Business need:** A business owner needs to understand competition, market signals and changing commercial conditions before adjusting pricing, product strategy or growth plans. Internal revenue alone cannot show whether sales changed due to competitors, customer perception, shifting prices or customer demand.

**Market Intelligence should help an owner answer:**

- Which tracked competitors offer a comparable product and how do their verified prices compare to mine?
- Did any comparable competitor change its price recently? When was that observed?
- What evidence suggests a competitor is relevant or active in the market?
- Are recorded sales or review-sentiment signals rising or falling, and is there enough evidence to show a meaningful trend?
- Which product categories deserve investigation? How complete is the evidence for that conclusion?
- What decision requires a human judgment, and what data is missing to support it?

**What success looks like:** An owner uses a trusted, current competitor comparison to investigate a price gap, notices an actual change in market conditions and can trace every observation back to its source. They do **not** receive unsupported assertions about overall market size, guaranteed growth or customer opinion.

**Boundary with `dashboard_analytics`:** The Dashboard reports the tenant's own business. Market Intelligence combines the tenant's product and sales records with competitor, market and review signals.

**Boundary with other AI capabilities:** Market Perception Index and AI Pricing have separate feature keys and separate inference flows. Their results should not implicitly become free, unlimited capabilities just because `market_intelligence` is enabled.

## 2. Real-world business scenarios

### Scenario A — Competitor undercuts a product

**Given:** A clothing retailer lists a jacket at JOD 35. Three valid comparable competitor offers are JOD 30, 32 and 40, observed recently in the same currency.  
**Question:** Is the jacket priced outside its observed comparison range?  
**Expected:** Show min JOD 30, median JOD 32, max JOD 40, own price JOD 35, matched-competitor count 3, and observation dates and sources where available. Separate price facts from AI-generated recommended actions.  
**Business value:** Enables a pricing review, not an automatic price cut.

### Scenario B — Market prices change

**Given:** A tracked, correctly mapped competitor's product was observed at JOD 32 and later JOD 29 in the requested window.  
**Expected:** Recent Price Changes shows direction, old/new prices and detection time.  
**Business value:** Provides a timely, verifiable signal for purchasing, promotion or pricing decisions.

### Scenario C — Too little market coverage

**Given:** No qualifying competitor price observations exist within the selected period.  
**Expected:** Pricing statistics and price recommendations are unavailable; never fabricate a competitor price or claim the product is competitive.  
**Business value:** Avoids decisions based on stale or incomplete evidence.

### Scenario D — Sales are growing for a second product

**Given:** Product B has recorded unit sales in two complete equal-length periods and the recent window grew.  
**Expected:** Expansion Opportunities presents B as an **internal sales growth signal to investigate**. It must not claim to have proven market-wide demand or opportunity size.  
**Business value:** Suggests a product for deeper market research.

### Scenario E — Reviews and perception disagree

**Given:** Reviews exist but have insufficient eligible sample size, or the MPI provider returns `UNKNOWN`.  
**Expected:** Market Perception is unavailable with an appropriate explanation. No fabricated sentiment or score is displayed.  
**Business value:** Prevents unjustified conclusions about customer opinion.

### Scenario F — AI provider unavailable

**Given:** MPI service is unavailable, but competitor and price records exist.  
**Expected:** Retain DB-backed competitor comparisons; only MPI enrichment should become unavailable. AI Pricing failure should not erase baseline market statistics.  
**Business value:** Graceful degradation.

## 3. What the current UI actually displays

The reviewed `src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx` renders:

| Current section         | UI elements                                                                            | State in reviewed implementation                                                  |
| ----------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Filters                 | Product selector; last 30 or 90 days                                                   | Wired to backend overview query                                                   |
| Four KPI cards          | Total Competitors; Average Pricing Score; Average Composite Score; Top Segment Score   | Database-based/derived, subject to qualifying data                                |
| Market insights         | Sales/review/pricing/activity drivers and summary                                      | **Rule-based** summary assembled by backend, despite “AI” label                   |
| Competitor comparison   | Pricing, composite and relevance scores; market presence; market perception badge      | DB-backed with optional MPI enrichment                                            |
| Pricing recommendations | Current and proposed price, market range, matched competitors; Generate/Refresh button | Separate AI Pricing API invoked on demand; baseline algorithmic values also exist |
| Expansion opportunities | Other products with higher recent unit sales                                           | Derived from tenant `transactions`, **not** externally proven market expansion    |
| Recent price changes    | Latest two qualified competitor price observations                                     | Data-backed when two distinct prices exist                                        |
| PDF export              | Section-by-section export from loaded data                                             | Implemented in frontend                                                           |

**Other Market Intelligence pages:** The reviewed Industry Trends, Market Opportunities, Leaderboard and Reports pages are still **Coming Soon previews** using preview datasets. They must not be included in production-verified market coverage claims.

**Empty root condition:** When the tenant has no active products, the overview returns an empty payload and frontend offers Connect Data. This is not the same as saying there is no competitive activity in the external market.

## 4. Database ownership and data prerequisites

| Table / source                  | Purpose in current market overview                      | Data producer / ownership to verify                     | Required for                                 |
| ------------------------------- | ------------------------------------------------------- | ------------------------------------------------------- | -------------------------------------------- |
| `products`                      | Tenant product list, categories, current price/currency | Backend sales/document ingestion and product management | Starting point for overview                  |
| `transactions`                  | Recorded unit sales in current/prior windows            | Backend/AI sales extraction ingestion                   | Internal sales drivers and expansion signals |
| `tenant_competitors`            | Tracked competitor and match-rate information           | AI discovery and competitor management                  | Competitor eligibility                       |
| `global_competitors`            | Competitor identity/name                                | AI discovery                                            | Competitor names                             |
| `competitor_product_mappings`   | Product-to-competitor comparison relationships          | AI discovery/mapping                                    | Comparable products                          |
| `competitor_prices`             | Observed prices, currency, timestamps, quality flags    | Market scraper                                          | Pricing scores, range, price changes         |
| `competitor_score_snapshots`    | Composite, relevance and market-activity scores         | AI competitor scoring                                   | Composite/relevance/presence metrics         |
| `reviews`                       | Eligible tenant review evidence                         | AI scraping / review collection                         | Sentiment and MPI                            |
| `sentiment_results`             | Scores linked to reviews                                | Sentiment pipeline                                      | Sentiment segment and insights               |
| `demand_forecasts`              | Expected demand by product/time window                  | AI forecasting                                          | Demand component of segment scores           |
| `market_events`                 | Observed competitor activity                            | Market scraper                                          | Activity driver                              |
| `evidence_records`              | Evidence/audit of MPI inference                         | Backend MPI service                                     | MPI traceability                             |
| Pricing outcome/evidence tables | Persisted AI pricing results/evidence                   | Separate pricing domain                                 | On-demand pricing recommendation             |

**Ingestion conclusion:** Unlike Paid Invoices and Inventory in Dashboard Analytics, **the existing market overview does not obviously require a new structured-document template**. It primarily depends on existing product/sales ingestion **plus** competitor discovery, scraping, scoring, review/sentiment and forecast pipelines working end-to-end. New templates should only be proposed after validating a specific missing business input and its rightful system owner.

**Runtime limitation:** Presence of a writer in the code does not prove that the worker executed, a scraper was allowed, or the live tenant has qualifying rows.

## 5. Metrics and calculation contract

These are implementation-observed calculations, followed by business-meaning qualifications and recommended changes.

### 5.1 Total Competitors

Current logic counts active `competitor_product_mappings` for the selected product whose related `tenant_competitors.is_tracked = true`.  
**Meaning:** Tracked, mapped competitors for that specific product, **not** every global or tenant competitor.  
**Need:** Show scope in metric tooltip and require valid tenant/product mapping.

### 5.2 Average Pricing Score (0–10)

For a positive tenant price `own` and competitor price `comp` in a matching currency, current backend calculates:

`score = clamp(10 - abs(1 - own / comp) × 10, 0, 10)`.

Score **10** means prices are close; it does **not** prove own pricing is profitable or advantageous. Invalid or absent price → score unavailable. Aggregate is the mean of available scores.  
**Need:** Name this **Price Similarity Score** or explain clearly that higher scores represent price closeness, not lower or better prices.

### 5.3 Average Composite Score (0–100)

Current backend retrieves the most recent `competitor_score_snapshots` row per mapped competitor (ordered by `calculated_at DESC, score_id DESC`), then averages available `composite_score` values.  
**Need:** Display calculation freshness; these score snapshots are **not constrained to the selected 30/90-day period** by the current raw-SQL query.

### 5.4 Market Presence and Relevance

Market Presence currently reads the snapshot's `market_activity_score`; Relevance prefers snapshot `relevance_score` and otherwise falls back to `product_match_rate × 100` if the match rate is 0–1.  
**Need:** Confirm with the AI team whether `market_activity_score` is a valid proxy for **market presence** before presenting it as such. These are conceptually different constructs.

### 5.5 Top Segment Score (0–10)

A **segment** is currently taken from `products.category`. The code combines:

| Component | Nominal weight | Source / calculation                                                                     |
| --------- | -------------: | ---------------------------------------------------------------------------------------- |
| Demand    |            50% | Forecast expected demand, normalized across comparable segments on a 0–10 relative scale |
| Sentiment |            30% | Eligible product review sentiment transformed from approximately −1…+1 to 0…10           |
| Pricing   |            20% | Available competitor price-similarity scores                                             |

**Current implementation:** Missing components are excluded and the remaining weights are re-normalized, so a “Top Segment Score” can be based on only one signal. Demand normalization is unavailable if there are fewer than two comparable segments or equal raw values.  
**Recommended:** Return/display component coverage and confidence; avoid ranking a one-signal segment on equal footing with a fully supported segment.

### 5.6 Market Insights

The `aiMarketIntelligence` payload is composed using **deterministic backend business rules**, from observed sales comparisons, sentiment, competitor price decreases and `market_events`. Its status is `derived`; confidence is `null`.  
**Business rule:** Present as an evidence-based insight summary, **not** as a newly generated AI-model explanation. A valid driver requires qualifying data; no driver → unavailable.

### 5.7 Expansion Opportunities

The current code finds other products with valid sales in both comparable 30/90-day windows and increasing unit sales:

`growthPercent = round((recentUnits - priorUnits) / priorUnits × 100)` where `priorUnits > 0`.

Returns up to three results.  
**Business rule:** This is **relative internal unit-sales growth** and a signal for investigation. It is not proven national or market-wide expansion potential.

### 5.8 Pricing ranges and recommendations

For the selected product, accepted competitor prices are sorted and min/max/mean/median computed. The overview also includes a simple **derived** hold/raise/reduce suggestion based on own price relative to the median (below 90% → raise toward 95% of median; above 110% → reduce toward 105%). The frontend has an explicit button calling a separate AI Pricing endpoint and merges its result for display.

**Business rule:** Price recommendations require margin/cost guardrails, product comparability and evidence before any action. **An on-demand AI recommendation is distinct from the baseline market-intelligence entitlement.**

### 5.9 Recent Price Changes

Uses the two latest qualifying `competitor_prices` rows for each selected mapping in the requested window; a change is emitted if values differ. This is _observed change_, not guaranteed change in the seller's entire catalog. Include observed time and source.

### 5.10 Market Perception Index

Current service reads eligible reviews (tenant scoped, `ALLOWED`, `SAFE`, supported collection methods, nonempty text), up to 100, then calls the hosted Gradio `market_intelligence` model. Valid score is 0–100; an insufficient review sample or `UNKNOWN` produces no number. The overview enriches competitors one by one and does not fail the page if MPI fails. Its data window is **not controlled by the overview's 30/90-day filter**.

**Feature boundary:** `market_perception` is separately catalogued and is not assigned to a standard plan in the supplied plan list. Whether this derived/AI enrichment belongs inside `market_intelligence` or requires its separate entitlement must be explicitly decided.

## 6. API and end-to-end data flow

```text
Owner selects a product + period
  ↓
React MarketIntelligenceOverviewPage
  ↓
useMarketIntelligenceOverview → marketIntelligenceApi.getOverview
  ↓
Backend Market Intelligence route/controller/service/repository
  ├─ tenant products and recorded sales
  ├─ active tracked competitor mappings
  ├─ valid scraped competitor price records
  ├─ latest score snapshots
  ├─ reviews/sentiment and forecast records
  ├─ competitor market events
  └─ optional MPI enrichment via separate Gradio AI service
  ↓
Response: metrics, competitors, derived insights,
          expansion signals, price ranges, price changes
  ↓
React cards/tables + PDF export

[Separate user action]
Generate pricing recommendation button
  ↓
POST /features/pricing/recommend?product_id=...
  ↓
Pricing domain → AI provider + persistence, per its own contract
```

**Observed frontend request:** `GET /market-intelligence` with `productId` and `periodDays`. The reviewed backend router is also mounted under `/market-intelligence` in its module. Exact external gateway prefixes should be validated in the running application.  
**Observed supported periods:** 30, 90 days (controller falls back to 30 for unsupported values).  
**Review-needed behavior:** A missing/invalid requested product ID silently falls back to the first active product, which can conceal an invalid selection.

## 7. Feature and plan boundaries

| Plan                    | `market_intelligence` availability | Related limits                                         |
| ----------------------- | ---------------------------------- | ------------------------------------------------------ |
| Starter ($55/month)     | **Not included**                   | No standard tracked competitors                        |
| Growth ($140/month)     | **Included**                       | Up to 10 tracked competitors; daily monitoring         |
| Enterprise ($350/month) | **Included**                       | Up to 50 tracked competitors; monitoring every 6 hours |

**Billing:** No separate standard-plan price configured for `market_intelligence` itself. Vendor monitoring costs can still be part of internal pricing.

**Separate catalog features requiring decisions:**

| Key                     | Relationship and recommendation                                                                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `competitor_management` | Managing tracked competitors/sync cadence is operationally linked, but not identical to reading market insights                                              |
| `tracked_competitors`   | Enforce 10/50 maximum in backend, not just UI                                                                                                                |
| `market_perception`     | Separate catalog key, not included in the supplied standard plans; decide if preview/summary is bundled or gated                                             |
| `ai_pricing`            | Separate catalog key, not included in supplied standard plans; should not silently become generally usable through overview                                  |
| `sentiment_analysis`    | Review-sentiment processing has its own record limits; data may be reused only within explicit entitlement policy                                            |
| `demand_prediction`     | Forecast source used for segment scoring; agree on whether this is permissible as a market-intelligence dependency and whether forecast values must be gated |

**Implementation finding requiring action:** The reviewed `market-intelligence` router only applies authentication and tenant middleware, without an explicit `requireEntitlement("market_intelligence")`. The `pricing` router has its `requireEntitlement("ai_pricing")` call commented out. Confirm any upstream global feature guard before concluding an effective access-control bypass, and test the complete route perimeter.

## 8. Data-quality, empty-state and trust policy

- Every observation must be tenant-scoped and sourced; never show cross-tenant prices or reviews.
- Price comparisons must require valid active mapping, tracked competitor, matching currency, accepted source status, exact/available observation and requested time range.
- Show the number of comparable competitors and when their data was last observed. A single record is an observation, not statistically robust market evidence.
- Do not substitute stale prices when a selected window has no data without visibly identifying their age and changed scope.
- Represent `0`, `no_data`, `partial`, `stale`, `insufficient_sample`, `provider_unavailable` and `permission_denied` as distinct states.
- Competitor mapping is not proof of like-for-like products; require user-reviewable similarity evidence.
- Present rule-based derived summaries as **derived**, and provider-inference results as **AI-generated** with available evidence and provider status.
- A failed MPI/AI pricing call should not erase database-backed competitor data.
- No fabricated confidence percentage when the system has not produced one.
- Price recommendation should never automatically update product prices.
- Protect separate premium AI features with effective backend authorization and usage controls.

## 9. Acceptance scenarios

| Case  | Setup                                                                       | Expected outcome                                                                                   |
| ----- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| MI-01 | Growth tenant with valid product and three recent mapped price observations | 3 comparable competitors and correct min/median/max                                                |
| MI-02 | Starter tenant                                                              | Market Intelligence response denied, if not entitled, not only hidden in UI                        |
| MI-03 | Tenant A asks for Tenant B product/competitor data                          | No cross-tenant data or leakage                                                                    |
| MI-04 | Competing price observation wrong currency                                  | Exclude from current product price comparison                                                      |
| MI-05 | Price row `source_status != ALLOWED`, not exact, or unavailable             | Exclude from pricing/statistics                                                                    |
| MI-06 | Two valid price observations with different prices in range                 | One correctly dated price-change entry                                                             |
| MI-07 | One qualified observation only                                              | Show price without inventing a change                                                              |
| MI-08 | No priced competitors                                                       | Show unavailable price metrics, not zero-price competitors                                         |
| MI-09 | No score snapshot                                                           | Show composite/presence unavailable, not computed from invented values                             |
| MI-10 | Five-plus eligible review input but provider yields `UNKNOWN`               | MPI remains unavailable without fabricated score                                                   |
| MI-11 | MPI provider times out                                                      | DB-derived overview still succeeds, MPI unavailable                                                |
| MI-12 | Period changes 30 → 90                                                      | Correct window-based data changes; avoid claiming MPI/snapshot reflect same window if not filtered |
| MI-13 | Two complete internal sales periods for another product                     | Accurate computed expansion signal; labeled as internal sales                                      |
| MI-14 | Only a single component exists for segment score                            | Score shows insufficient coverage or clear component limitations                                   |
| MI-15 | AI pricing button called without separate entitlement                       | Enforced decision; no unauthorized inference/charges                                               |
| MI-16 | PDF export in English and Arabic                                            | Export reflects the same current selected product/period and real displayed numbers                |
| MI-17 | Tracked competitor count exceeds plan limit                                 | Block and report appropriate entitlement error                                                     |
| MI-18 | All qualifying market data absent                                           | Proper no-data states and actionable explanation                                                   |

## 10. Technical risks and implementation priorities

| Priority | Issue from source inspection                                        | Next backend action                                                            |
| -------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| P0       | No explicit market-intelligence entitlement guard in reviewed route | Confirm global checks, then enforce server-side feature boundary               |
| P0       | Pricing route comments out `ai_pricing` entitlement guard           | Make an explicit catalog/UX decision; enforce protected calls                  |
| P0       | AI pipeline _code_ isn't evidence of live competitor collection     | Run end-to-end tenant-scoped discovery→scrape→score and review→sentiment tests |
| P1       | Score snapshots ignore requested reporting period                   | Expose snapshot timestamp/coverage or align with selected window               |
| P1       | Market Presence uses `market_activity_score`                        | Confirm naming/semantic equivalence with AI owners                             |
| P1       | Top Segment Score rescales weights when evidence missing            | Expose component coverage; avoid misleading rankings                           |
| P1       | “AI Market Intelligence” content is deterministic derived text      | Rename/label clearly; keep separate from actual AI inference                   |
| P1       | Separate MPI entitlement is unresolved                              | Document/gate/price independently as designed                                  |
| P1       | Requested invalid product silently falls back                       | Decide and enforce explicit invalid-product behavior                           |
| P2       | Other Market Intelligence pages are Coming Soon previews            | Do not count them as shipped capabilities; prioritize based on business value  |
| P2       | AI pricing is an independent recommendation domain                  | Preserve isolation, evidence trail and failure handling                        |

**New document templates?** None are clearly required for the **current overview** based on inspected code. Focus first on existing product/sales ingestion and AI worker output, not on introducing a duplicate competitor template.

## 11. End-to-end verification checklists

### Business and entitlement

- [ ] Growth and Enterprise can open the feature; Starter is denied in backend.
- [ ] `tracked_competitors` quota enforced under each plan.
- [ ] Decision recorded for `market_perception` entitlement.
- [ ] Decision recorded for `ai_pricing` entitlement and billing/usage.
- [ ] Recommendation is advisory; no automatic price mutations.
- [ ] Business claims distinguish real market evidence from internal signals.

### Source pipelines

- [ ] Product records imported or created for test tenant.
- [ ] Product categories, currencies and current prices valid.
- [ ] AI competitor discovery creates valid tracked mappings.
- [ ] Market scraper writes fresh and accepted price observations.
- [ ] Scoring pipeline produces snapshots, timestamps and relevant score values.
- [ ] Review collector stores eligible tenant reviews.
- [ ] Sentiment pipeline processes review scores.
- [ ] Demand forecast pipeline provides qualifying forecast rows where needed.
- [ ] Market-event pipeline writes qualifying events, where available.
- [ ] External AI MPI integration returns valid/unknown results safely.

### UI, API and data quality

- [ ] All four KPI values matched to independent DB calculations.
- [ ] Product and 30/90-day filters produce correct scoped responses.
- [ ] Missing, low-quality, stale, wrong-currency observations excluded or labeled.
- [ ] Composite/relevance/presence semantics and source timestamps visible.
- [ ] Pricing metrics calculated from comparable accepted prices only.
- [ ] Recent price changes derived from two genuine observations.
- [ ] Derived insight text corresponds to stored records.
- [ ] Expansion opportunities derived from two comparable periods.
- [ ] MPI failure gracefully degrades without hiding competitors.
- [ ] AI pricing call only runs through entitled pathway.
- [ ] PDF exports are consistent with displayed data in English and Arabic.
- [ ] Cross-tenant isolation verified via API and PostgreSQL RLS.
- [ ] Both no-data and zero-value scenarios are handled correctly.

## 12. Calculation and ownership verification register

Fill this during actual live testing; do not mark complete merely because source code contains a writer.

| Market component        | Table(s) / system                                                                    | AI/Backend owner confirmed | Runtime rows verified | API correct | UI correct | Evidence / date |
| ----------------------- | ------------------------------------------------------------------------------------ | -------------------------- | --------------------- | ----------- | ---------- | --------------- |
| Product selector        | `products`                                                                           | ☐                          | ☐                     | ☐           | ☐          |                 |
| Total Competitors       | `competitor_product_mappings`, `tenant_competitors`                                  | ☐                          | ☐                     | ☐           | ☐          |                 |
| Pricing Score           | `products`, `competitor_prices`                                                      | ☐                          | ☐                     | ☐           | ☐          |                 |
| Composite Score         | `competitor_score_snapshots`                                                         | ☐                          | ☐                     | ☐           | ☐          |                 |
| Presence/Relevance      | Score snapshots, match rate                                                          | ☐                          | ☐                     | ☐           | ☐          |                 |
| Top Segment Score       | `products`, `demand_forecasts`, `reviews`, `sentiment_results`, `competitor_prices`  | ☐                          | ☐                     | ☐           | ☐          |                 |
| Market Insight Drivers  | `transactions`, `reviews`, `sentiment_results`, `market_events`, `competitor_prices` | ☐                          | ☐                     | ☐           | ☐          |                 |
| Expansion Signals       | `transactions`, `products`                                                           | ☐                          | ☐                     | ☐           | ☐          |                 |
| Price Changes           | `competitor_prices`                                                                  | ☐                          | ☐                     | ☐           | ☐          |                 |
| Market Perception       | `reviews`, Gradio MPI, `evidence_records`                                            | ☐                          | ☐                     | ☐           | ☐          |                 |
| AI Price Recommendation | Pricing domain/Gradio + outcome/evidence                                             | ☐                          | ☐                     | ☐           | ☐          |                 |
| PDF Export              | Current frontend payload                                                             | N/A                        | N/A                   | N/A         | ☐          |                 |

### Grounding / source files inspected

**Frontend:** `src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx`, `hooks/useMarketIntelligenceOverview.js`, `api/marketIntelligenceApi.js`, and reviewed Industry Trends, Opportunities, Leaderboard and Reports pages.

**Backend:** `src/modules/market-intelligence/{route,controller,service,repo}`, `src/modules/mpi/{service,repo,client}`, `src/modules/pricing/route/pricing.route.ts`.

**AI:** Latest AI team ZIP checked for extraction, competitor discovery/scoring, scraping and MPI modules. Precise live collector execution and hosted Gradio service deployment **not verified**.

---

**Next feature in the agreed catalog:** `market_perception` (Feature 3 of 21). Do not move to it until the user says **Next**.
