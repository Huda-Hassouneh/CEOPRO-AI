# CEOPRO-AI — Demand Prediction

## 1. Business problem and value

Demand Prediction helps a store owner answer: **How many units of each product are likely to sell in the next 7 or 30 days, and what should I do before demand arrives?** It supports purchase planning, staffing discussions, and earlier recognition of demand changes. A forecast is an _estimate_, not a guaranteed future sale.

**Scenario — grocery shop:** A shop predicts 120 bottles of mineral water will sell over the next 7 days. It currently holds 45 bottles, and its desired safety stock is 20. The resulting indicative shortfall is `max(0, 120 + 20 − 45) = 95` bottles. This is **an inventory decision based on a forecast**; it should be presented as a conditional recommendation, not a purchase order. The business owner must consider lead time, supplier minimum order quantities, promotions, expiring stock, and available cash.

### What a customer needs to decide

| Decision                            | Supporting information                                          | What CEOPRO should avoid                    |
| ----------------------------------- | --------------------------------------------------------------- | ------------------------------------------- |
| Which products to prepare for?      | Product-level expected demand over a clear horizon              | Calling a one-day projection a 30-day total |
| How much inventory could be needed? | Expected demand, verified stock and safety stock                | Treating unknown inventory as zero          |
| Which products are rising/falling?  | Trend backed by comparable periods or daily forecasts           | Inventing a trend from one aggregate point  |
| How trustworthy is this forecast?   | Historical coverage, error metrics, model/baseline, timestamps  | Presenting AI output as certain             |
| What if this product is new?        | Cold-start warning and lower-confidence baseline where possible | Fabricating history or high confidence      |

## 2. Scope and boundaries

- **This feature owns:** demand forecasts, trend presentation, provenance and evaluation of forecast quality.
- **`dashboard_analytics`:** may display a summary, only when entitled and adequately covered.
- **`inventory_intelligence`:** owns more sophisticated replenishment decisions, supplier/lead-time constraints and multi-location inventory optimization. Demand Prediction may show an _existing_ recommendation that is demonstrably backed by a stored result, rather than automatically claiming full inventory intelligence.
- **`product_management`:** owns product catalog and stock records.
- **`document_extraction`:** provides historical sales when imported through the existing business-file pipeline.
- **`market_intelligence`:** provides external context, not a mandatory input to the currently inspected forecasting model.

## 3. Actual current frontend functionality

The inspected frontend has:

1. **Demand Prediction Overview** (`DemandPredictionOverviewPage.jsx`): product and 7/30-day period filters; five metric cards (`next30Forecast` label adapts to the selected horizon, products forecasted, predicted increase/decrease, stable demand); date-based total forecast chart; per-product table with stock, forecast, target date, confidence range, trend and stored recommendation; PDF export.
2. **Product Forecasts List** (`ProductForecastsListPage.jsx`): search, category/trend filters, 7/30-day period selection, paginated forecast table and navigation.
3. **Product Forecast Detail** (`ProductForecastDetailPage.jsx`): stock, expected demand, target date, confidence range, model-performance indicator, historical actual-vs-forecast chart, stored recommendation, PDF export.
4. Additional **inventory recommendation/model accuracy** pages/components exist, but some are minimal placeholders or depend on data not returned by the current response. Do not classify them as a complete separate forecasting capability without another code review.

Current frontend API client reads `GET /forecasting/demand` and `GET /forecasting/demand/:productId`. **It does not expose a client method invoking the backend generation POST route** in the inspected snapshot.

## 4. Actual backend routes and entitlement

`src/modules/forecasting/route/forecasting.route.ts`:

- `GET /forecasting/demand?periodDays=7|30&productId=all|<uuid>` — persisted forecast overview.
- `GET /forecasting/demand/:productId?periodDays=7|30` — persisted product detail.
- `POST /forecasting/demand/:productId/generate` with `{ "horizon_days": 1..60 }` — requests a new prediction through hosted Gradio and persists it.

All routes apply authentication, tenant checks and `requireFeatureAccess("demand_prediction")`. **Verify all effective plan/tenant entitlements in E2E tests**, including that Starter cannot invoke the generation endpoint directly. Read views accept 7 or 30 days; generation supports a broader 1–60 range.

## 5. Table ownership and data requirements

| PostgreSQL table                                      | Used for                                          | Primary writer/owner in inspected code                               | Required for                                                                          |
| ----------------------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `products`                                            | Product identity, category, current price         | CEOPRO product/business ingestion                                    | Every forecast                                                                        |
| `transactions`                                        | Historical daily units and prices                 | CEOPRO sales ingestion                                               | Data-driven forecasts                                                                 |
| `inventory`                                           | Current stock and safety stock                    | Separate inventory import / other business system                    | Stock display and stock-aware recommendations; not necessarily forecasting generation |
| `demand_forecasts`                                    | Persisted predicted demand and forecast windows   | CEOPRO Gradio generation route **and** separate AI forecast consumer | Dashboard/overview/detail forecast output                                             |
| `evidence_records`                                    | Forecast evidence/confidence/provenance           | Backend generation and AI forecasting pipeline                       | Auditing/explaining generated forecasts                                               |
| `model_versions`                                      | Training and evaluation metrics                   | AI forecasting pipeline                                              | Model-performance display when correctly mapped                                       |
| `recommendation_outcomes`                             | Existing stored inventory-related recommendation  | Independent recommendation producer                                  | Optional action on detail page                                                        |
| `companies` / tenant membership / entitlement catalog | Currency/tenant context and feature authorization | Platform/backend                                                     | Access and isolation                                                                  |

`data_sources`, `ingestion_jobs`, and `import_staging_rows` are upstream ingestion infrastructure; the demand read service does not require them for every API request. `invoices` and `invoice_items` are **not directly required** by the current forecasting repository.

### Input readiness

The current Gradio-generation backend reads up to one year of `transactions`, grouped by product/day. The AI team's separate Python forecaster builds a gap-free daily history and defaults to a **30-day minimum for its model sufficiency policy**. This 30-day policy is specific to that Python implementation, not independently verified for the hosted Gradio model. Inventory is useful but missing inventory must be disclosed, not treated as zero stock.

## 6. Forecast calculation and aggregation contracts

### 6.1 Backend overview

The overview requests an upcoming 7- or 30-day UTC window, and also reads the preceding equivalent horizon for trend comparison.

- Per product, the backend chooses an **exact forecast covering that horizon**, if present; otherwise it may sum **complete daily forecasts** or another non-overlapping tiling.
- Incomplete/overlapping coverage must not be represented as a trustworthy complete-horizon figure.
- Tenant total = sum of **only products with complete forecast coverage**. `productsForecasted` reflects how many contributed. A product with no forecast is not assumed to have zero demand.
- Overall daily chart only gets a numeric value for a day if **all selected products have a true daily forecast** for that date. A 30-day aggregate should not be evenly divided across 30 chart points.
- Trend uses first versus last daily prediction when a full daily series exists, or comparable complete previous/current horizons; otherwise it is unavailable.
- Historical actual quantities come from recorded transactions; missing days in the current backend detail query are _unknown_, not automatically zero.

### 6.2 Inventory illustration

For a qualifying stored `restock` recommendation and complete stock/safety-stock observations, the backend computes:

`Suggested units = max(0, forecast expected demand + safety stock − current stock)`

A missing `recommendation_outcomes` row means the backend does not invent a recommended action.

### 6.3 Confidence and model accuracy

- The backend uses persisted `confidence_range_lower/upper` only when one forecast row represents the requested horizon; it does not sum independent confidence ranges.
- Product detail resolves model metrics from `model_versions` only when the selected rows map **unambiguously** to exactly one version.
- **MASE is an error measure, not an accuracy percentage.** Lower is better. UI labels and formatting must reflect that distinction.

## 7. Two different forecast generation paths — critical distinction

### Path A — backend → hosted Gradio → backend persistence

`POST /forecasting/demand/:productId/generate` reads local `products`, `transactions`, and `inventory`, calls hosted Gradio `forecast`, and inserts `demand_forecasts` and `evidence_records`.

The inspected backend creates a date interval **ending at `forecast_target_date` and spanning `horizon_days`**, stores `expected_demand` as that interval's forecast, and sets `confidence_range_lower/upper` to `null`. It does **not** create `model_versions` from the response. Therefore an unspecified confidence interval or model-performance card may legitimately appear unavailable even when a forecast exists.

**Critical contract test:** Confirm whether hosted Gradio `expected_demand` means **units expected across the entire horizon** or **units on the final target day**. Backend persists it as a horizon total; using the wrong semantic meaning would make 7/30-day figures misleading.

### Path B — AI Redis event consumer → Python pipeline → direct database persistence

The AI repository contains `src/ai/forecasting/consumer.py` consuming `ceopro:stream:demand_forecast_requested` and `pipeline.py` using historical `transactions`, a baseline and potentially XGBoost with walk-forward checks; it inserts `demand_forecasts`, `evidence_records`, and sometimes `model_versions`.

**Two gaps found in supplied source:**

1. The current frontend/backend archives contain **no publisher for that Redis forecast-request event**, so this AI consumer cannot be assumed to run as part of the standard CEOPRO ingestion flow.
2. The Python `pipeline.py` stores `expected_demand = forecast_values[-1]` (final-day prediction), and its SQL writer records a `forecast_target_date` without an explicit multi-day window. This is **not semantically equivalent** to a total expected demand over 7 or 30 days. The data contract between the Python producer and the backend's horizon-based summaries requires reconciliation before the sources can be mixed.

The hosted Gradio `forecast` service source itself is not part of the AI ZIP; its runtime behavior remains unverified.

## 8. Business scenarios that must pass

1. A product with complete 7-day forecast: show forecast, date and coverage status.
2. A product with complete 30-day forecast: show **30-day units**, not an end-day quantity.
3. One product complete and another missing: total uses only complete products and clearly states the coverage count.
4. No transaction history: show no valid prediction or justified cold-start baseline; never fabricate a confident forecast.
5. Insufficient history: use the model's documented fallback/low-confidence pathway, not a full-confidence model claim.
6. Missing inventory: forecast can be separate; stock/reorder quantities should remain unavailable.
7. Partial or overlapping forecast coverage: do not present complete-horizon metrics.
8. Historical forecast compared to actual transactions: only use predictions actually created before the evaluation window (no look-ahead leakage).
9. Generated forecast lacks confidence bounds: show unavailable interval, not made-up numbers.
10. Growth/Enterprise authorized; Starter/unauthorized tenant denied on both reads and generation.

## 9. Test matrix

| Area           | Verification                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------------ |
| Frontend       | KPI cards, list, product detail, filters, charts, export, Arabic/English, RTL, empty/error/loading states    |
| API            | `/forecasting/demand`, product detail, generation; validation of 7/30 read and 1–60 generation horizons      |
| Database       | Correct tenant, product and transaction relationships; forecast coverage and deduplication behavior          |
| AI integration | Actual Gradio `forecast` response semantics, confidence, model source; timeout/failure handling              |
| AI worker      | Event production/consumption, direct DB writes, RLS, retry and duplicate-message handling                    |
| Accuracy       | Historical out-of-sample backtesting; compare baseline and XGBoost MAE/RMSE/MASE, no future leakage          |
| Safety         | No cross-tenant data; missing data never disguised as zero; forecast not treated as guaranteed purchase plan |
| Plans          | `demand_prediction` belongs to Growth/Enterprise; all backend routes deny unauthorized plans                 |

Run deterministic DB-backed Playwright tests separately from opt-in live Gradio/AI tests. Record source table counts, forecast model provenance, period coverage, expected/API/UI values, and failure classifications.

## 10. Backend completion checklist

- [ ] Verify sales ingestion creates enough correctly dated and tenant-scoped `transactions` for selected products.
- [ ] Verify inventory availability separately; never default missing stock to zero.
- [ ] Verify Gradio `forecast` endpoint with real payloads and identify its `expected_demand` horizon semantics.
- [ ] Reconcile Gradio forecast windows with the Python event-consumer writer and the `demand_forecasts` read contract.
- [ ] Implement or confirm a controlled forecast trigger/schedule; document if manual generation is the intended policy.
- [ ] Verify complete coverage for 7/30-day views and accuracy of daily charts.
- [ ] Verify confidence range, model version, and performance-data availability without inventing values.
- [ ] Verify recommendation ownership and keep advanced inventory intelligence separately entitled.
- [ ] Enforce feature entitlement and tenant isolation in GET and POST tests.
- [ ] Add end-to-end UI/API/DB tests and opt-in live AI tests with detailed failure diagnostics.

## 11. Ownership and decisions still open

| Question                                                                         | Accountable party                                                           |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Is one `expected_demand` value a daily or horizon total?                         | AI team (both hosted model and Python pipeline), backend agrees on contract |
| Who triggers forecast generation on product ingestion, on schedule, or on click? | Backend + AI team                                                           |
| Who writes and owns the authoritative forecast when two pipelines exist?         | Backend + AI team                                                           |
| How are multiple forecast revisions deduplicated/selected?                       | Backend with AI producer contracts                                          |
| Who produces optional `recommendation_outcomes`?                                 | AI/recommendation feature owner                                             |
| Should model performance be shown only for backtested versions?                  | Product/backend/AI                                                          |

## 12. Source files reviewed

**Frontend:** `src/features/forecasting/api/forecastingApi.js`, `pages/DemandPredictionOverviewPage.jsx`, `pages/ProductForecastsListPage.jsx`, `pages/ProductForecastDetailPage.jsx` and the related hooks/components.

**Backend:** `src/modules/forecasting/{route,controller,service,repo,client}`, `forecasting.calculations.ts`, associated contract tests and entitlement middleware.

**AI:** `src/ai/forecasting/{pipeline,consumer,data_access,evidence,model,cold_start,features}.py` and forecasting README.

**Evidence level:** Verified against available source archives only, not a live environment. Revalidate if the frontend, backend, or AI service has changed since the archived snapshots.
