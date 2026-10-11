# CEOPRO-AI — Feature 05: Inventory Intelligence

W

## 1. Executive business purpose

Inventory Intelligence should help merchants decide **which products need replenishment, which risk sitting unsold, and what purchasing action is justified by actual sales history and stock levels**. It should reduce lost sales caused by stockouts and avoid tying up cash in excessive inventory.

Unlike `demand_prediction`, which forecasts _units customers may buy_, `inventory_intelligence` uses that forecast with actual stock and other replenishment constraints to make **actionable, explainable stock decisions**. Unlike `product_management`, it is _not_ the canonical inventory editor or warehouse ledger.

### Example — small retailer

| Item          | Stock on hand | Predicted next 30-day sales | Likely business action                       |
| ------------- | ------------: | --------------------------: | -------------------------------------------- |
| Bottled water |      45 units |                   120 units | Evaluate replenishment immediately           |
| Milk          |     200 units |                   185 units | Monitor / consider shelf life                |
| Chocolate     |     500 units |                   160 units | Review purchasing and potential excess stock |

**Business questions:** What will run out? When? What should I buy? How urgent is it? What cash is tied up? Can I trust the recommendation? The current code can partially answer **what action a forecast-vs-stock gap suggests**, but not all the stronger questions (especially supplier lead time, stockout date, existing purchase orders, profitability and carrying cost).

---

## 2. What exists in the reviewed implementation

| Layer                | Code location                                                     | Verified behavior                                                                                       | Important limitation                                                                                                           |
| -------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| DB schema            | `prisma/schema.prisma` → `inventory`                              | Product + tenant, stock quantity, reorder level, safety stock, warehouse location                       | No stock-ledger or supplier/lead-time/purchase-order model in this read path; multiple inventory rows per product are possible |
| Forecast store       | `demand_forecasts`                                                | Stores expected demand, dates/horizon, model version, optional interval                                 | Valid complete horizon and freshness are critical                                                                              |
| Recommendation store | `recommendation_outcomes`                                         | Contains forecast-linked actions and decisions                                                          | Existing Node.js service reads these; no feature-specific writer was found in the reviewed Node modules                        |
| AI route             | `src/ai/main.py` → `GET /dashboard/inventory-recommendations`     | Tenant-scoped FastAPI handler invokes rule-based query                                                  | No verified Node.js connection to this AI route; this is not the same as hosted Gradio                                         |
| AI rules             | `src/ai/dashboard/inventory_recommendations.py`                   | `RESTOCK_NOW`, `REDUCE_ORDER`, `MONITOR`, signed gap, priority, explanatory reason                      | See formula and correctness risks below                                                                                        |
| Backend              | `src/modules/forecasting/route/forecasting.route.ts`              | `GET /forecasting/demand`, `GET /forecasting/demand/:productId`; reads stock and stored recommendations | All routes gated on `demand_prediction`, not a dedicated inventory-intelligence backend permission                             |
| Backend              | `src/modules/forecasting/service/forecasting.service.ts`          | Reads a **stored** recommendation action; derives replenishment quantity when possible                  | It does not generate or persist a new inventory recommendation                                                                 |
| Frontend             | `src/features/forecasting/pages/InventoryRecommendationsPage.jsx` | Page and tab route exist                                                                                | Currently renders Coming Soon                                                                                                  |
| Frontend             | `src/features/forecasting/api/forecastingApi.js`                  | `getRecommendations` filters forecast rows where a `recommendedAction` exists                           | Not a dedicated Inventory Intelligence API; depends on existing forecast responses                                             |
| Frontend             | `src/features/products/api/inventoryApi.js`                       | Placeholder returns `{ levels: [] }`                                                                    | No live stock-management client here                                                                                           |
| Frontend             | `src/app/router/index.jsx`                                        | Inventory page uses `FeatureRouteGuard` for both `demand_prediction` and `inventory_intelligence`       | UI guard is not equivalent to server-side enforcement                                                                          |
| Document ingestion   | `src/modules/dataconnection/`                                     | Existing extracted sales rows populate product/transaction records                                      | No production inventory write path identified                                                                                  |

**Classification:** DB structure = implemented; independent AI heuristic = implemented; backend presentation = partial; separate frontend experience = missing; actual data ingestion = missing; end-to-end = not verified.

---

## 3. Required database tables and ownership

| Table                                        | Essential?                | Input / output                                                                                 | Who should feed it?                                                   | Status                                                                |
| -------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `products`                                   | Yes                       | Canonical product identity, name, current selling price, currency                              | CEOPRO product/sales import                                           | Existing writer identified                                            |
| `transactions`                               | Yes for forecast creation | Actual historical product sales used by forecasting                                            | CEOPRO sales extraction/ingestion                                     | Existing writer identified                                            |
| `inventory`                                  | **Yes**                   | On-hand stock, reorder/safety stock, optional warehouse                                        | **Your backend Inventory CSV/XLSX import or authorized POS/ERP sync** | Production feeder not identified                                      |
| `demand_forecasts`                           | **Yes**                   | Future unit-demand forecasts                                                                   | AI forecast worker and/or backend forecast-generation service         | Implemented writers; verify execution and horizon contract            |
| `recommendation_outcomes`                    | Conditional               | Stored action/decision attached to a forecast; required by current Node recommendation display | A recommendation producer must be explicitly designated               | Read exists; production inventory-specific write path not established |
| `evidence_records`                           | Useful                    | Forecast evidence, confidence and provenance                                                   | AI/backend forecasting                                                | Writers exist; correctness and join must be verified                  |
| `model_versions`                             | Optional                  | Model performance / MASE                                                                       | AI forecasting                                                        | Not necessary to compute a simple stock gap                           |
| `features`, `plan_features`, `subscriptions` | Access control            | Availability and tenant entitlement                                                            | CEOPRO billing/entitlement system                                     | Catalog feature exists, standard-plan assignment absent               |

No dedicated invoices template is required for this feature. The **Inventory import template already created for Dashboard Analytics** supplies the principal missing input, provided its backend processor is implemented and its records are consistently mapped to `inventory`.

### Data prerequisites

- Match each stock record to the correct tenant-owned product (prefer immutable product UUID; use reviewed name mapping only if unambiguous).
- Define whether `stock_quantity` is on-hand or sellable/available stock; reservations and incoming orders cannot silently be counted as available stock.
- If there are several warehouse rows per product, define **per-warehouse** versus **aggregated total** and avoid duplicate snapshot uploads.
- Require observation timestamps or otherwise record inventory freshness; a successful file upload timestamp is not necessarily the stock's observation date.
- Treat missing stock as **unknown**, not zero. Treat genuinely verified zero stock as **zero**, not missing.
- Preserve tenant isolation, source references, import jobs and validation failures.

---

## 4. Two DIFFERENT calculation paths already exist

### 4.1 AI-team rule-based endpoint (verified in Python repository)

Let `D` = stored forecast's `expected_demand`, `S` = current inventory row's `stock_quantity`.

`gap_percent = (D − S) / S × 100`, provided `S > 0`.

`quantity_gap = round(D − S)` (signed).

Current Python action policy:

| Condition                 | Output         | Priority                                     |
| ------------------------- | -------------- | -------------------------------------------- |
| `gap_percent >= 20%`      | `RESTOCK_NOW`  | High if absolute gap ≥ 50%; otherwise Medium |
| `gap_percent <= -20%`     | `REDUCE_ORDER` | High if absolute gap ≥ 50%; otherwise Medium |
| Gap between −20% and +20% | `MONITOR`      | Low                                          |

For restock rows only, Python computes `estimated_revenue_impact = quantity_gap × products.current_price`. **This is an approximate potential sales value, not actual revenue, realized savings, or profit.** The code does not use purchase cost, fulfillment costs, taxes or margins.

**Known rule limitations:**

1. Python explicitly filters `i.stock_quantity > 0`, so a genuine zero-stock product disappears instead of becoming the most urgent stockout case.
2. The query uses `SELECT DISTINCT ON (df.product_id)` with an `inventory` join. With multiple warehouse rows, one stock row can be selected rather than the sum across warehouses.
3. It uses the latest forecast by creation time without verifying that it represents a complete 30-day horizon; a target-day forecast is not automatically a 30-day total.
4. Label `model_accuracy_pct` is populated from an evidence **confidence_score**. Confidence and measured forecast accuracy are not interchangeable.
5. `REDUCE_ORDER` uses a negative `suggested_qty`: this must not be interpreted as automatically removing stock or requesting a return.
6. `limit` is applied after producing aggregate action counts, so counts may cover more items than the returned list; the UI should explain scope.

**Do not directly ship these figures as a fully validated automated purchasing policy.**

### 4.2 CEOPRO Node.js forecasting detail (verified in backend)

The backend forecasts service **does not derive the action from the gap**. It retrieves linked rows in `recommendation_outcomes`, selects a stored `recommended_action` (`restock`, `reduce`, or `monitor`), and only then calculates a quantity for a `restock` action when all required values exist:

`restock_suggested_quantity = max(0, forecast.expected_demand + safety_stock − current_stock)`.

It sums stock and complete safety stock across inventory rows, and requires a single selected complete-horizon forecast to use its associated stored action.

**Consequences:** The Python route and Node.js service are not the same recommendation contract, and may produce different quantities or availability statuses for one product. You should select one authoritative calculation/ownership path before building the public UI.

### 4.3 Business recommendation for calculation policy

Start with a **transparent, deterministic, non-automated recommendation** using verified inputs:

`required_units = max(0, covered_horizon_demand + applicable_safety_stock − usable_on_hand − confirmed_inbound)`.

If inbound data is not actually supported, explicitly omit the field and state that the figure excludes incoming orders. Do not silently use zero for unavailable inbound data.

For a credible purchasing action, later add supplier lead time, reorder cycle, pack sizes, minimum order quantity, warehouse aggregation, stock reservations and forecast uncertainty. Do not claim this advanced optimization already exists.

---

## 5. What should the merchant see? (product requirements)

**Recommended initial UI** (proposed, not implemented):

1. **Priority actions**: restock now / monitor / review excess stock, with tenant/product filter.
2. **Stock versus forecast**: quantity on hand, forecast horizon and expected demand, safety stock and coverage status.
3. **Suggested units**: integer value with clear reason and calculation breakdown.
4. **Urgency and evidence**: stock freshness, forecast generation date, horizon completeness, confidence/accuracy labels kept distinct.
5. **Exceptions**: stock is zero; inventory missing; stock is stale; forecast missing/partial; warehouse mismatch; new product without sales history.
6. **Action tracking** (phase 2): accept/reject/dismiss recommendation; capture outcome after enough time for evaluation.

Do **not** create or submit a purchase order, adjust stock, or infer supplier commitments unless an explicit confirmed business workflow is implemented.

### Example product row

| Product       | Stock | Forecast (30d) | Safety | Proposed quantity | Data state                                    |
| ------------- | ----: | -------------: | -----: | ----------------: | --------------------------------------------- |
| Bottled water |    45 |            120 |     20 |                95 | Indicative; supplier inbound not tracked      |
| Chocolate     |   500 |            160 |     20 |                 0 | Consider excess; no automatic stock reduction |

---

## 6. Feature boundaries

| Feature                    | Owns                                                                                                    |
| -------------------------- | ------------------------------------------------------------------------------------------------------- |
| `product_management`       | Manage products, quantities, reorder levels, warehouse details; canonical stock records                 |
| `demand_prediction`        | Forecast unit demand and identify changes in demand patterns                                            |
| `inventory_intelligence`   | Turn demand + inventory into prioritized, explainable stock actions                                     |
| `dashboard_analytics`      | Show current inventory health/availability in high-level KPIs                                           |
| `business_recommendations` | Potential higher-level prioritization across business operations; avoid double-counting the same advice |

A plain stock alert (`stock_quantity <= reorder_level`) can be a basic inventory/status function. An **AI forecast-informed replenishment plan** is the specialized entitlement.

---

## 7. Subscription and access contract

- `inventory_intelligence` exists as a Boolean, lifetime-reset catalog feature in `src/modules/features/catalog.ts`.
- In the provided standard-plan matrix, it is **not assigned to Starter, Growth, or Enterprise** and has no separately configured customer price.
- The inventory page route checks **both** `demand_prediction` and `inventory_intelligence` via the frontend's `FeatureRouteGuard`.
- Backend forecasting routes enforce **`demand_prediction` only**, and can return a `recommendedAction` when stored data exists. This is not dedicated server-side `inventory_intelligence` enforcement.
- The AI FastAPI route authenticates tenant context, but entitlement handling must be verified at the CEOPRO API integration boundary.

**Release decision needed:** Choose if Inventory Intelligence is an Enterprise benefit, Growth+Enterprise bundle, or explicit add-on. Do not silently enable it to all demand-prediction users.

**Minimum security requirements:** enforce the exact entitlement at the backend recommendation route and output serialization, tenant-scope all queries, prohibit cross-tenant product identifiers, and prevent restricted recommendations leaking through the general forecast endpoint.

---

## 8. Gap/risk register and backend priorities

| Priority | Issue                                                            | Owner                     | Acceptance condition                                                                          |
| -------- | ---------------------------------------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------- |
| P0       | Inventory has no verified production feeder                      | Backend (data connection) | User Inventory CSV/XLSX or connected source produces validated, deduplicated `inventory` rows |
| P0       | Dedicated Inventory Recommendations page is Coming Soon          | Frontend + Backend        | Real API-backed list, detail, filters, states and bilingual UI                                |
| P0       | AI heuristic endpoint and Node stored-action pathway disagree    | Backend + AI team         | One authoritative, versioned recommendation contract and output schema                        |
| P0       | Missing per-feature server enforcement                           | Backend                   | No `inventory_intelligence` data leak when disabled                                           |
| P0       | Zero-stock rows are excluded in AI Python                        | AI team                   | Verified zero stock participates, no division-by-zero                                         |
| P0       | Latest single forecast may be wrong horizon                      | Backend + AI team         | Use complete, current, matching forecast window or show unavailable                           |
| P1       | Multiple warehouses can be mishandled by Python                  | AI team + Backend         | Explicit correct aggregation or warehouse-level recommendations                               |
| P1       | Confidence displayed as model accuracy                           | AI team + Frontend        | Correctly label confidence vs independent forecast accuracy                                   |
| P1       | Stock freshness not guaranteed                                   | Backend ingestion         | `observed_at` or defensible equivalent; stale/partial values disclosed                        |
| P1       | No proven live recommendation persistence / action decision flow | Backend + AI team         | Stored actions linked to correct forecast, idempotent generation and audit trail              |
| P2       | Lead times, inbound orders and supplier constraints not included | Product + Backend         | Add only if business workflow requires; label assumptions before then                         |
| P2       | Reproducible results / explanation and decision tracking         | Product + QA              | Show formula, sources, version, decision and outcome                                          |

**Recommendation:** Resolve P0 correctness and entitlement issues before customer-facing launch. Do not market rule-based gap classification as trained optimization.

---

## 9. End-to-end test scenarios

Test against a dedicated tenant-scoped PostgreSQL test database, real CEOPRO backend and Playwright UI. Use separate opt-in AI/live worker tests.

| Scenario                                       | Expected outcome                                                                  |
| ---------------------------------------------- | --------------------------------------------------------------------------------- |
| No products                                    | Empty product state; no fabricated recommendations                                |
| Product without inventory                      | Missing-data state, **not zero stock**                                            |
| Verified zero stock + future demand            | Urgent stockout/replenishment classification without division by zero             |
| Product stock > forecast                       | Explain excess; do not auto-adjust inventory                                      |
| Product stock ≈ forecast                       | Monitor only, with correct threshold handling                                     |
| Multiple warehouses                            | Aggregate or segment correctly according to documented policy                     |
| Missing `safety_stock`                         | Quantity requiring safety is unavailable; do not silently substitute zero         |
| Incomplete/stale forecast                      | No full-horizon recommendation; show coverage/freshness issue                     |
| Daily + 30-day forecasts overlap               | Select correct horizon once; do not double-count                                  |
| Very old inventory                             | Flag staleness even if recent import succeeded                                    |
| Forecast confidence with no measured accuracy  | Do not display confidence as model accuracy                                       |
| Missing product price / cost                   | Do not invent monetary value, profit or savings                                   |
| Duplicate imports or worker retries            | Idempotent stock states; no accidental addition of snapshot rows                  |
| Tenant A vs Tenant B                           | No cross-tenant data leakage in API/UI/AI DB queries                              |
| Starter, Growth, Enterprise and custom plan    | Enforce actual configured `inventory_intelligence` plus dependent feature rules   |
| AI API unavailable                             | Stable, informative error and preserved last known valid data where policy allows |
| English and Arabic                             | Correct labels, quantities, RTL and explanation text                              |
| User acts on recommendation (when implemented) | Authorized, idempotent decision and auditable outcome                             |

### Minimum regression coverage

- **Unit:** gap thresholds, signed quantities, confidence labeling, null/zero cases, forecast horizon validation.
- **Database/integration:** tenant isolation, stock importing, warehouse aggregation, forecast joins, source dates, recommendation_outcomes producer.
- **API:** feature gates, error handling, response shape, stale data and no-data.
- **Playwright:** UI cards, table, filters, action explanations, empty/partial/error states, Arabic/English.
- **Live AI:** endpoint execution against realistic seeded stock/forecasts, with worker logs and verifiable rows; `BLOCKED` where external prerequisites are absent.

Diagnostic logging should include metric/action name, product and tenant IDs, source tables, stock and forecast timestamps, forecast horizon, expected/actual API value, actual UI value, producer, and failure category. Redact secrets.

---

## 10. Proposed implementation sequence

1. **Finish Inventory import** using the previously created CSV/XLSX template; validate product mapping, warehouse semantics, snapshot-vs-delta behavior, negative quantities, and RLS.
2. **Agree on one recommendation contract** with AI team: forecast horizon, zero stock, warehouse aggregation, safety stock, thresholds, confidence vs accuracy and storage ownership.
3. **Introduce dedicated backend route/service/repository** for authorized inventory-intelligence results (or a carefully isolated reusable forecasting subservice). Do not expose a direct AI endpoint from the browser.
4. **Persist or deterministically calculate** versioned recommendations with source provenance; handle repeat generation, stale inputs and absence of valid forecasts.
5. **Implement the Inventory Recommendations frontend** using the actual API, with English/Arabic and no-data explanations.
6. **Decide plan assignment and enforce** `inventory_intelligence` server-side; verify Growth/Enterprise dependency policies explicitly.
7. **Add deterministic and opt-in live AI E2E tests** using the project's shared testing infrastructure and diagnostic reports.

### Suggested minimum API contract (proposal only)

`GET /inventory-intelligence/recommendations?periodDays=30&productId=all`

Return tenant-scoped products with stock availability, stock observation date, horizon-validated expected demand, safety stock status, recommended action, suggested quantity, explanation, severity, evidence/model metadata and availability state. A post/feedback endpoint should be added **only if** decisions are genuinely persisted and authorized.

This route is **not present** in the supplied backend; do not document it as existing.

---

## 11. Acceptance checklist (initially unchecked)

- [ ] Inventory CSV/XLSX data reliably feeds `inventory` for real tenants.
- [ ] Stock snapshots, product identity, warehouse aggregation and freshness are defined and tested.
- [ ] Zero-stock and missing-stock cases are distinguished.
- [ ] Forecast source represents a complete, relevant and current horizon.
- [ ] AI and backend use the same inventory recommendation contract and formula policy.
- [ ] Recommendations can be explained directly from recorded inputs; uncertainties disclosed.
- [ ] Confidence is not mislabeled as historical model accuracy.
- [ ] Dedicated backend route enforces tenant and `inventory_intelligence` access.
- [ ] Standard/custom plan inclusion policy is documented and implemented.
- [ ] Inventory Recommendations page renders real API-backed data in English/Arabic.
- [ ] No automatic purchasing or stock changes happen without authorized user action.
- [ ] Unit, API, DB, UI and optional live AI E2E checks pass with supporting logs.

---

## 12. Source-code audit references

**Frontend:**

- `src/features/forecasting/pages/InventoryRecommendationsPage.jsx`
- `src/features/forecasting/components/InventoryRecommendationCard.jsx`
- `src/features/forecasting/api/forecastingApi.js`
- `src/features/forecasting/hooks/useInventoryRecommendations.js`
- `src/features/products/api/inventoryApi.js`
- `src/app/router/index.jsx`; `src/features/billing/components/FeatureRouteGuard.jsx`

**Backend:**

- `src/modules/features/catalog.ts`
- `src/modules/forecasting/route/forecasting.route.ts`
- `src/modules/forecasting/service/forecasting.service.ts`
- `src/modules/forecasting/service/forecasting.calculations.ts`
- `src/modules/forecasting/repo/forecasting.repo.ts`
- `src/modules/dataconnection/`
- `prisma/schema.prisma` (models: `products`, `transactions`, `inventory`, `demand_forecasts`, `recommendation_outcomes`, `evidence_records`)

**AI team:**

- `src/ai/main.py` (`/dashboard/inventory-recommendations`)
- `src/ai/dashboard/inventory_recommendations.py`
- `src/ai/dashboard/inventory.py`
- `src/ai/tests/test_dashboard_inventory_recommendations_integration_db.py`

_Scope caveat:_ This is a code-level audit, not a validation of a deployed service or live tenant. Source snapshots may differ from subsequently modified working branches. Existing integration tests being present does not guarantee execution or passing against the current environment.
