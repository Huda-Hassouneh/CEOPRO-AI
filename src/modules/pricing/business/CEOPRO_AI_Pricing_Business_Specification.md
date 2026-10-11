# CEOPRO-AI — Feature 15: AI Pricing Recommendations (`ai_pricing`)

## 1. Executive summary and business purpose

`ai_pricing` is a **metered recommendation feature**: the owner requests a product-specific recommendation to **raise**, **lower**, or **hold** a selling price. The system should use tenant-owned product information, reliable competitor prices, currency controls, bounded changes, and product-cost protection. It must not change a real selling price automatically. A useful output identifies the product, current price, proposed price, currency, explanation, guardrails, evidence provenance, and any uncertainty.

Differentiate this from:

- `market_intelligence` (boolean entitlement to market-analysis surfaces and derived pricing/competitor information);
- `business_recommendations` (cross-signal recommendations combining sales, sentiment, demand, and competition);
- custom-plan **subscription pricing** (what CEOPRO charges its customers, implemented in a separate subscription pricing domain).

The present customer-facing flow exists, but subscription-gating, idempotency, evidence depth, confidence semantics, and provider-contract verification prevent calling this fully production-ready.

## 2. Subscription catalog and availability

`src/modules/features/types/feature.catalog.ts` defines `ai_pricing` as:

- `FeatureType.limit`;
- unit `recommendations` (Arabic `توصية`);
- `AggregationType.sum`;
- `ResetCycle.billing_period`.

It has a legacy alias `pricing_intelligence -> ai_pricing`. `src/config/production-plans.ts` catalog `2026-10-v2` includes **no `ai_pricing` grant** in Starter ($55 USD/month), Growth ($140), or Enterprise ($350). The catalog does register the feature for prospective custom-plan/admin usage. Custom plans can assign a numeric allowance; the exact entitlement must be read from the **tenant's accepted active plan**, never inferred from the tier name.

**Critical code finding:** `src/modules/pricing/route/pricing.route.ts` includes the disabled statement `// requireEntitlement("ai_pricing")`. The route uses `authenticateUser` and `requireTenant` but does not deny missing/exhausted `ai_pricing` allocation. Thus, a standard-plan user can reach the AI service even though none of the standard plans purchase `ai_pricing`.

The client must not be the enforcement point. Production must check both inclusion and remaining quota before AI invocation, with correct handling of no subscription, trialing/active status, custom-plan limits, renewal, exhaustion, and concurrent requests. Do not retroactively add this feature to standard plans without a commercial decision.

## 3. Implementation architecture and API contracts

### Production-facing Node → hosted Gradio pathway

1. Frontend `src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx` calls `usePricingRecommendation`, which uses `pricingApi.generateRecommendation(productId)`.
2. `pricingApi.js`: `POST /features/pricing/recommend?product_id=<uuid>`; product ID must not equal `all`.
3. `src/app.ts` mounts the pricing domain at `/features/pricing`.
4. `src/modules/pricing/route/pricing.route.ts`: authentication, tenant context, UUID query validation; **no active `ai_pricing` entitlement middleware**.
5. `controller/pricing.controller.ts`: reads tenant/user/product ID and maps missing product and provider errors.
6. `service/pricing.service.ts`: fetches the tenant's product, 30-day eligible competitor observations, and available FX-rate metadata; calls AI; persists local evidence/outcome records; increments metered usage.
7. `client/pricing.client.ts`: shared AI transport, service `analytics`, API name `recommend`, positional input `[product, competitor_prices, exchange_rates]`. Validates `result` (`OK`/`UNKNOWN`) and `persisted_records`.
8. React displays the new recommendation for the chosen product in its Market Intelligence pricing section; the result lives in `pricingByProduct` component state. `GET /market-intelligence` separately provides a **derived** pricing row; it is not the same as a fresh AI recommendation.

### Separate AI-team FastAPI pathway — not equivalent to Gradio

The supplied AI repository exposes `POST /pricing/recommend?product_id=...` in `src/ai/main.py`, with validated tenant context and direct database access. `src/ai/pricing/pipeline.py` reads DB product/competitor data itself and directly persists `evidence_records` and `recommendation_outcomes`.

By contrast, Node's active hosted Gradio integration **supplies a product and competitor price arrays** and **persists its own evidence**. The uploaded AI FastAPI implementation does **not** prove the hosted Gradio `recommend` service is deployed or has identical algorithms, output fields, or persistence side effects. In particular, avoid dual persistence/duplicate outcomes if the pathways are combined later. Real Gradio behavior needs separate opt-in runtime verification.

## 4. Database sources and ownership

| Database records                                                  | Purpose                                                                                        | Canonical writer / owner                                                   |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `products`                                                        | Tenant product ID, multilingual name, `current_price`, `cost_price`, `currency`, soft deletion | CEOPRO Product Management / ingestion                                      |
| `tenant_competitors`, `global_competitors`                        | Tracked competitor identity and display alias                                                  | Competitor domain / monitoring                                             |
| `competitor_product_mappings`                                     | Active tenant-specific mapping from product to competitor                                      | Competitor Management                                                      |
| `competitor_prices`                                               | Competitor observations, prices, currencies, timestamps, exactness and source policy           | AI market scraper / competitor collection                                  |
| `currency_rates`                                                  | FX rate, timestamp and source for contextual cross-currency reference                          | Rate provider / currency subsystem                                         |
| `evidence_records`                                                | Locally stored recommendation evidence and explanation                                         | Pricing domain (active Node pathway); also AI standalone pathway when used |
| `recommendation_outcomes`                                         | Recommended-action outcome linked to evidence, not evidence of an applied price                | Pricing domain (active Node pathway); also standalone AI pathway           |
| `subscription`, `plan_features`, `features`, `subscription_usage` | Entitlements and per-period recommendation usage                                               | Subscription and Features domains                                          |
| `product_price_history`                                           | Historical price updates from product changes; not written when a recommendation is generated  | Product domain/database triggers                                           |

**Tenant ownership:** Node's product and competitor data reads set `app.current_tenant_id` and `app.current_user_id` in Prisma transactions and constrain queries by `tenant_id`. Node also writes its own evidence/outcome within tenant-context transactions. FX rates are global reference data; access to the rate table and row validity need testing.

**Important provenance gap:** Node persists product ID, market counts, action, confidence and explanation but its evidence `source_record_ids` currently contains only `{ product_id }`, not the selected competitor price observation IDs. The AI standalone pipeline records competitor-price IDs; however, that information is not safely inherited into Node's active evidence rows. As a result, consumers cannot fully reproduce exactly which competitor observations caused a particular saved recommendation.

## 5. Product and market input selection

Active Node pricing context (`repo/pricing.repo.ts`):

- Own product: `tenant_id` plus `product_id`, `deleted_at: null`, `product_name`, `current_price`, `cost_price`, `currency`.
- Competitor mappings: same tenant/product, active mapping, tracked competitor.
- Eligible competitor prices: `is_available=true`, `is_exact_data=true`, `source_status='ALLOWED'`, and `observed_at` within the previous **30 days**.
- Competitor display name: tenant custom alias where present, otherwise global competitor name.
- Currency-rate rows: `from_currency` in observed currencies, `to_currency` equals own product currency, including `exchange_rate`, `last_fetched`, `source`.

**Calculation limitation:** The Node query includes **all eligible historical observations within 30 days** per mapping, ordered newest first; it does not clearly collapse to the latest price per competitor. A frequently scraped competitor may contribute many more data points than one scraped less often. This can bias both the reported mean/median and the AI's competitor match count. Confirm whether the intended business policy is latest reliable observation per distinct competitor/product, rather than one vote per scrape.

**FX quality risk:** The Node FX query checks the currency pair but does not reject old rate timestamps or stale values. The node service sends those rate rows to hosted Gradio; actual consumption must be verified. The Node response's `market_*` summary explicitly uses only raw **same-currency** competitor prices, while the AI team's standalone implementation treats cross-currency converted prices as **reference information only**, never as the local recommendation average.

## 6. Calculations: market statistics

Node `summarizeMarketPrices` works over same-currency valid nonnegative numeric observations:

- Market minimum: `min(prices)`.
- Market maximum: `max(prices)`.
- Market average: `sum(prices) / count(prices)`.
- Market median: middle ordered observation; for even count, average of the two middle values.
- Count: number of price observations (not necessarily distinct competitors).
- If empty, return null for min/max/average/median, count zero.

Example, three valid independent competitor observations in JOD: `80`, `90`, `100`. Average = `90`, median = `90`, min = `80`, max = `100`. A same-currency average should never directly blend a USD price with JOD values. Invalid, zero, stale, duplicated, or mis-mapped prices require a documented policy and tests; the Node summary currently accepts zero-valued observations (its filter is `>= 0`), whereas zero is generally not a legitimate retail market price.

## 7. AI algorithm and pricing guardrails (AI-team FastAPI repository)

**These formulas are verified in the supplied Python source, but the hosted Gradio deployment used by Node has not been proven to match them.**

`src/ai/pricing/recommendation.py` implements a rule-based heuristic, not a trained price-optimization model:

- Default competitiveness threshold `PRICING_COMPETITIVENESS_THRESHOLD_PCT = 0.05` (5%).
- Let `M` be the average of eligible comparable competitor prices in the same currency.
- If `current_price > 1.05 × M`, action `lower`, raw suggestion `M`.
- If `current_price < 0.95 × M`, action `raise`, raw suggestion `M`.
- Otherwise action `hold`, raw suggestion `current_price`.
- No eligible competitor observations ⇒ `UNKNOWN`, not a fabricated market recommendation.

`src/ai/pricing/guardrails.py`:

1. **Price movement cap**: default `PRICING_MAX_CHANGE_PCT=0.15` (15%). Proposed price is clamped to `[current×0.85, current×1.15]`.
2. **Cost protection**: if `cost_price` exists, default `PRICING_MIN_MARGIN_PCT=0.10` yields floor `cost×1.10`. Suggested price is raised to at least that floor.
3. If cost price is missing, margin protection is not applied; this should be explicitly reported to users rather than interpreted as safe profitability.
4. **Important economics detail:** `cost × (1 + 0.10)` implements 10% _markup on cost_, not a 10% _gross margin on selling price_ (`cost / (1 - 0.10)`). Decide and document which concept the business actually promises.
5. **Order-of-operations risk:** The cost-floor adjustment runs _after_ the 15% movement cap. It can raise the final suggestion above the price-change guardrail when the floor demands it. This must be intentional and tested.

**Illustration:** Own price 100 JOD, competitor average 80 JOD, cost 60 JOD. Raw suggested price 80, movement-capped to 85, cost-floor 66 ⇒ final suggestion 85 JOD. If cost were 90 JOD, floor 99 ⇒ final 99 JOD (the floor overrides the 85 reduction). If cost were 120 JOD, floor 132 JOD, potentially beyond the ordinary +15% movement cap.

Confidence in `recommendation.py`: `round(min(0.75, 0.25 + 0.10 × min(n, MIN_COMPETITORS_FOR_CONFIDENCE×2)), 2)`, with default `MIN_COMPETITORS_FOR_CONFIDENCE=3`; `n` is the number of matched rows. Default confidence: 1 -> 0.35, 2 -> 0.45, 3 -> 0.55, 5 -> 0.75. This is a **heuristic indicator**, not an empirically calibrated probability. The `MIN_COMPETITORS_FOR_CONFIDENCE` setting affects the cap rather than strictly requiring three competitors before issuing a recommendation.

## 8. API outputs, persistence, and action handling

Node `client/pricing.client.ts` accepts a hosted response shaped as `{result: {status: 'UNKNOWN' } | {status:'OK', action, current_price, suggested_price, guardrail_clamped, margin_guardrail_clamped, matched_competitor_count, confidence_score}, persisted_records: [...]}`. `readPricingExplanation` scans `persisted_records` for `explanation_text`.

Node's public normalized result contains `status`, `action`, `current_price`, `suggested_price`, `market_min`, `market_max`, `market_avg`, `market_median`, `matched_competitor_count`, `confidence_score`, `guardrail_clamped`, `margin_guardrail_clamped`, `clamped`, `explanation`, `evidence_id`, `outcome_id`, `currency`. `max_change_pct`, `min_margin_pct`, and `floor_price` are explicitly returned as **null** because they are not in the current hosted contract; do not imply users can currently inspect the applied threshold values.

`persistPricingRecommendation` writes:

- an `evidence_records` row for `OK` **and** `UNKNOWN` statuses; and
- a `recommendation_outcomes` row only for an `OK` result with an action.

A row in `recommendation_outcomes` represents a **proposed recommended action**, not proof that a product price was changed or that an outcome was measured. No automatic product price update is found in this path. Recommended business lifecycle: generated → reviewed → accepted/rejected → explicitly applied (separate authorized product action) → measured; only implement if approved.

## 9. Usage metering and billing correctness

The active Node service ends with `incrementUsage(tenantId, 'ai_pricing')` after provider invocation and local persistence.

- **One request/result currently increments by one**, including `status='UNKNOWN'`, provided the tenant has a usage allocation. This is a product-policy issue: should an unanswerable result consume a recommendation credit? Set the intended rule explicitly.
- **Missing entitlement:** `incrementUsage` returns `null` when no eligible plan feature is found; the service ignores that return and can still return a recommendation. Combined with the commented-out route guard, the current code is a commercial access bypass.
- **Capacity:** the service does not atomically reserve a unit before invoking AI; concurrent requests can exceed an assigned allowance once a guard is re-enabled unless concurrency is solved.
- **Partial success:** local evidence/outcome persistence and `incrementUsage` are separate transactions; a usage failure may leave evidence while the response fails, and retries may double-persist evidence/charge.
- **Repeated refresh:** frontend lets users generate the same product recommendation repeatedly; without idempotency or clear charging disclosure, repeat clicks can consume additional units and produce duplicate evidence rows.
- **Billing reset:** cumulative SUM usage should correspond to the accepted subscription's current billing period and reset only with a new period allocation. Upgrades/downgrades/custom plans require boundary tests.

Proposed invariant: A chargeable unique generation request uses at most one recommendation credit; no tenant exceeds the effective allowance; all charged results have durable, tenant-owned request/outcome evidence. Define idempotency and `UNKNOWN` charging semantics before implementation.

## 10. Frontend and localization

`src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx` has a real Generate/Refresh button; it sends the selected product ID through the `usePricingRecommendation` React Query mutation. The new recommendation is stored per product in component state and shown in the pricing table. It displays `raise/lower/hold`, price, market summary, confidence, explanation and guardrail indicator where available. The page handles API errors with a toast. The broader overview supplies **derived** pricing rows even without an AI call; do not imply all displayed price suggestions were freshly generated by AI.

Gaps/considerations:

- No distinct persisted recommendation history retrieval on page reload; locally generated state disappears.
- Pricing-generation button visibility is not synchronized with the `ai_pricing` entitlement; unauthorized standard-plan customers can attempt requests.
- No explicit remaining-credit display/charge warning attached to the action is verified.
- The provider explanation is free text in the inspected contract, frequently English; frontend translations for button labels do not translate upstream explanation content.
- USD plan price and customer product currencies are distinct concepts; never display product prices using subscription checkout currency.
- On `UNKNOWN`, show insufficient eligible market data, not an invented suggestion or a failure disguised as success.

## 11. Most important defects and decisions

| Priority | Gap                                                                          | Recommended decision / fix                                                                           |
| -------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Critical | `requireEntitlement('ai_pricing')` commented out                             | Restore server-side plan inclusion and exhausted-quota enforcement before AI call                    |
| Critical | No atomic reservation for metered AI calls                                   | Introduce concurrency-safe quota reservation/charge, idempotency, reconciliation                     |
| High     | `incrementUsage()` null ignored                                              | Fail closed when entitlement/allocation is absent, no free provider call                             |
| High     | Hosted Gradio vs AI FastAPI contracts differ                                 | Freeze/version the active contract and test real provider; clarify one authority for evidence writes |
| High     | Multiple historical price observations per competitor bias average           | Define and implement latest eligible observation per competitor/product or approved sampling policy  |
| High     | Missing full evidence provenance                                             | Persist/serve actual price observation IDs, timestamps, currency, and rule version                   |
| High     | Pricing margin floor is markup and can override movement cap                 | Clarify economics and rule priority; test contradictory guardrails                                   |
| High     | FX rates lack freshness enforcement and market summary is same-currency only | Check rate timestamp/source; keep cross-currency prices labeled reference-only                       |
| High     | Insufficient data / `UNKNOWN` still charged                                  | Define transparent charging policy and customer messaging                                            |
| High     | Repeated requests create new evidence/usage                                  | Implement idempotent generation keys and consistent persistence                                      |
| Medium   | Custom plans can grant feature but UI doesn't show allowance                 | Expose quota, remaining calls, exhaustion, subscription upgrade action                               |
| Medium   | User-facing response omits actual threshold/floor values                     | Add provider-approved explainability fields rather than guessing                                     |
| Medium   | Recommendation status not persistent in UI                                   | Add authorized retrieval/history if product requirements demand it                                   |
| Medium   | Only English free-text explanations verified                                 | Localize structured action/explanation or return keyed bilingual rationale                           |
| High     | Live provider behavior and multi-tenant isolation not verified               | Implement safe E2E tests with restricted DB roles and approved test tenant                           |

## 12. Responsibility boundaries

**Frontend:** choose product, show current vs suggested prices, evidence, status, credits, reasons, errors and localization. No authority to supply raw competitor data or change pricing automatically.

**Node pricing domain:** authenticate tenant, enforce `ai_pricing` entitlement/capacity, read tenant-owned data under RLS, select correct comparable records, validate provider request/response, persist local evidence and charge usage with idempotency.

**AI team / hosted provider:** produce explainable rule-based recommendation, confidence indicator and guardrail metadata without cross-tenant state leakage. Hosted Gradio implementation must be independently contracted and verified; the separate AI FastAPI algorithm is the source of only its own pathway's behavior.

**Market scraper / competitor domain:** keep exact-data and source-policy flags, price observations, timestamps, mappings and competitor tracking accurate.

**Product Management:** own current/cost prices, price edits and actual price history; recommendation generation must not write to `products.current_price`.

**Subscriptions / Features:** own catalog availability, accepted plan limits, billing-cycle allocations, charging policy and safe reconciliation.

## 13. Test modes and fixtures

A. **Deterministic calculation tests:** run Python pricing unit tests and controlled Node market-statistics cases, no external provider needed.

B. **Database/Node integration:** dedicated PostgreSQL test tenants, real Prisma RLS reads/writes and plan entitlements; stub only upstream provider for specifically labeled contract tests.

C. **Browser E2E:** real React + Node + dedicated database; verify Generate/Refresh and errors, independent usage/evidence checks. A stubbed hosted AI provider means _provider-simulated E2E_, not live AI E2E.

D. **Opt-in live hosted Gradio:** controlled products, test JWT, approved AI credentials, real end-to-end request and response, evidence row and usage check. Never infer hosted behavior from separate Python FastAPI tests.

E. **Opt-in standalone AI FastAPI integration:** run separately with its restricted test DB role and test cases, explicitly report it is a different API from production-facing Gradio.

Avoid prod DB changes on Render; refuse mutating tests if the DB identity isn't proven safe. Reuse Playwright fixtures, existing Python tests, API contract tests, RLS helpers, diagnostics, screenshots and HTML/JSON reporting. Record PASS/FAIL/SKIP/BLOCKED/ERROR truthfully.

## 14. E2E acceptance checklist (30 scenarios)

- [ ] 1.  Starter/Growth/Enterprise requests are denied when `ai_pricing` is absent from their plans.
- [ ] 2.  An enabled custom-plan tenant can request a recommendation within its allowance.
- [ ] 3.  Missing/expired/suspended subscriptions are handled according to effective access policy.
- [ ] 4.  Usage decreases remaining credits by exactly one per intended chargeable generation.
- [ ] 5.  Exact limit, exhausted limit and period renewal return correct results.
- [ ] 6.  Simultaneous final-credit requests cannot exceed allowance.
- [ ] 7.  Duplicate request retries cannot create duplicate charges/outcomes.
- [ ] 8.  Provider failure and invalid response cannot leave inconsistent usage/evidence records.
- [ ] 9.  `UNKNOWN` is shown and charged/refunded per explicitly documented policy.
- [ ] 10. Product not found, deleted or belonging to another tenant is denied safely.
- [ ] 11. One tenant cannot read or infer another tenant's pricing observations/evidence.
- [ ] 12. Market input includes only active mappings and tracked competitors.
- [ ] 13. Market input excludes unavailable, non-exact, restricted and stale observations.
- [ ] 14. One competitor with many historical samples cannot unintentionally dominate pricing.
- [ ] 15. Market min/max/mean/median independently match chosen approved sampling set.
- [ ] 16. Same-currency pricing is not blended with other currencies.
- [ ] 17. FX reference uses correct pair, positive rate, timestamp/source, and freshness policy.
- [ ] 18. No eligible observations produce `UNKNOWN`, not invented pricing guidance.
- [ ] 19. 5% comparison threshold and boundary behavior match the actual active AI algorithm.
- [ ] 20. Raise/lower/hold actions match a controlled price dataset.
- [ ] 21. 15% movement guardrail clamps suggestions correctly.
- [ ] 22. Cost protection behaves correctly with missing cost, zero cost, and conflicting guardrails.
- [ ] 23. Heuristic confidence score increases/caps as documented and is not marketed as certainty.
- [ ] 24. Hosted Gradio response parsing rejects malformed/forged numeric or status fields.
- [ ] 25. Evidence IDs and outcome IDs belong to the correct tenant, product and source observations.
- [ ] 26. Generating a recommendation does not update the actual selling price.
- [ ] 27. Frontend button operates on the selected product and shows loading/errors correctly.
- [ ] 28. Derived Market Intelligence pricing rows are distinguished from actual new AI recommendations.
- [ ] 29. Arabic/English status labels, pricing units and RTL display work; AI explanations have an approved localization policy.
- [ ] 30. Live hosted Gradio, worker/database and frontend integration is either verified with evidence or labeled BLOCKED.

## 15. Immediate production-readiness priorities

1. **P0 authorization:** restore and test `requireEntitlement('ai_pricing')` (or more comprehensive gate), with zero-credit, plan, and API-bypass checks.
2. **P0 metering integrity:** atomic reservation/idempotency; no free calls for missing entitlement; reconcile partial failures.
3. **P1 calculation integrity:** deterministic latest-observation market inputs, zero/missing prices, FX freshness, confidence and cost guardrail semantics.
4. **P1 provider/evidence contract:** confirm deployed Gradio behavior, guarantee tenant-bound provenance, avoid duplicate evidence writers, document `UNKNOWN` charging.
5. **P1 frontend truthfulness:** entitlement-aware action, remaining credits, persisted history if needed, and localized/grounded explanations.
6. **P1 E2E verification:** independently verify complete tenant→Node→Gradio→Postgres→UI lifecycle, preserving all prior test suites.

**Bottom line:** The customer-facing Generate action, Node data preparation, Gradio adapter, evidence write, and usage increment exist. The critical missing element is **commercially safe, concurrency-safe entitlement enforcement**, closely followed by reproducible price evidence and a verified active-AI contract. Do not change plan availability or silently turn recommendations into automatic price updates.
