# Demand Prediction Testing and Diagnostics

This suite reuses the existing Playwright configuration, `DashboardDatabase` read-only/RLS helper, and diagnostics reporter. It adds no schema changes and does not seed, modify, or delete application data. The deterministic calculation and service tests use controlled in-memory rows; real database writes require the explicitly enabled Live AI test.

## Source ownership and actual flow

| Stage | Source of truth in this checkout |
|---|---|
| Sales ingestion | CEOPRO's transaction ingestion writes `transactions`; forecast input uses `tenant_id`, `product_id`, `transaction_date`, `quantity_sold`, and `unit_price`. The source code in this flow does not read invoices as sales history. |
| Active backend generation route | `POST /forecasting/demand/:productId/generate`, behind authentication, tenant membership, and `demand_prediction` feature access. Body is `{ horizon_days?: 1..60 }`, default 7. It calls Gradio service `analytics`, API name `forecast`, with positional data `[transactions, horizonDays, currentPrice, currentStock, category, productName]`. The checked React API client exposes only GET methods, so the UI does not trigger this route. |
| Backend input/persistence | `forecasting.repo.ts` reads up to 365 days of tenant-scoped transactions grouped by UTC day, summing quantity and calculating weighted unit price, plus inventory positions. The backend receives a result and writes `demand_forecasts` plus linked `evidence_records` in a Prisma transaction. The response's `persisted_records` array is schema-checked but ignored by the backend. |
| Separate AI worker path | `ai/src/ai/forecasting/consumer.py` consumes Redis stream `ceopro:stream:demand_forecast_requested`; it calls `pipeline.run_forecast()` and writes forecasts/evidence directly with the restricted AI DB role. It retries messages and dead-letters after configured attempts. The checked backend contains no producer for this Redis event. |
| AI service source | The local AI repository contains the Python forecasting pipeline and FastAPI dashboard readers, but no implementation of the backend's Gradio `analytics/forecast` API contract was found. A hosted Gradio service may exist outside this checkout; it is not verified here. |
| Read path and UI | Backend GET `/forecasting/demand` and `/forecasting/demand/:productId` read persisted forecasts, inventory, model versions, and (detail only) transaction history. React uses those routes for `/demand`, product lists, and detail pages. |

This means there are two distinct generation paths in the checked source: a synchronous backend-to-Gradio route and an AI-owned Redis worker. The active app POST route is concrete, but the local AI repository does not prove the remote Gradio endpoint is running or compatible. No recurring schedule or backend Redis producer was found in the checked backend source. The named business specification confirms the React API client has no generation method in its reviewed snapshot; the live test invokes the real backend route directly rather than inventing a UI trigger.

## Metric-to-database and calculation map

| Output | Source and rule in the backend | Independent test method |
|---|---|---|
| `next30Forecast` / selected period total | Sum only product totals whose requested window is complete. A forecast row may represent its inclusive start/end interval, or a target date when both interval fields are null. Exact horizon rows win; otherwise complete daily rows or non-overlapping interval tiles may sum. | Pure scenarios in `forecasting.test.ts`; E2E optional raw SQL reader recalculates from `demand_forecasts` without importing the backend calculation helper. |
| `productsForecasted` | Count products with complete requested coverage, not products with any row. | Service contract test; real check in overview E2E when credentials are configured. |
| Increase/decrease/stable counts | Trend from complete daily first/last points, or compare complete aggregate horizons with the preceding equivalent period. | Pure/service contracts; actual tenant comparison requires the authenticated E2E. |
| Chart points | Only daily forecasts are shown as daily points. Aggregate rows are not spread across days. The overview chart is null when not every selected product has a daily value for that date. | Service contract plus UI E2E. |
| Product stock | Sum inventory warehouse `stock_quantity` rows for the tenant/product. Missing inventory is null. Safety stock is exposed only when every contributing row has a finite value. | Service contract. |
| Detail actuals | `transactions` grouped by UTC transaction date; dates without recorded rows remain null in the chart. | Service contract; SQL read-only snapshot exposes sales rows for live E2E diagnosis. |
| Confidence range | Use stored lower/upper only when both are valid and contain expected demand. Do not add marginal intervals across independent forecasts. | Pure calculation tests. |
| Model performance | Read `model_versions.metrics` only when forecast rows resolve unambiguously to one registered version; absent metrics remain null. | Service contract covers unknown accuracy as null; registry-backed DB check is blocked without DB credentials. |
| Restock quantity | Only for an explicit stored `restock` recommendation on one complete horizon row: `max(0, horizon forecast + all safety stock - all stock)`. No priority is inferred. | Service contract. |

The backend demand routes require `demand_prediction`. The separate frontend Inventory Recommendations route requires both `demand_prediction` and `inventory_intelligence`; the source contract asserts this boundary.

All app query reads set `app.current_tenant_id` and `app.current_user_id` within their database transaction. The test DB reader starts `BEGIN READ ONLY`, verifies a non-superuser without `BYPASSRLS`, and refuses database names without `test`, `testing`, `qa`, or `e2e` markers.

## Test layers and coverage

| Area | Coverage in this suite | Execution status in this workspace |
|---|---|---|
| 7-day totals and complete coverage | Exact inclusive window and daily sum; partial periods remain unavailable | PASS: deterministic contract |
| 30-day totals | Aggregate period total; no prorating a horizon row | PASS: deterministic contract |
| Partial, overlap, duplicate revisions | Partial is null; latest exact-window revision wins; exact horizon has precedence over daily alternatives without double counting | PASS: deterministic contract |
| AI client request/response | Positional request shape, 1–60 horizon validation, missing/null/string/negative/non-finite demand, invalid source, bad confidence | PASS: contract/component test with a fake Gradio client |
| AI transport | Shared Gradio token/API transport, malformed SSE/JSON, HTTP authentication/upstream failures, bounded timeout and no implicit retries | Existing `tests/ai/gradio-client.test.ts` is included in the Demand Prediction contract command |
| Backend route, RLS context, entitlement | Query and generation validation, tenant-scoped snapshot, tenant mismatch, boolean feature middleware, Growth/Enterprise catalog inclusion | PASS: in-memory Prisma boundary and source contract; not a real RLS database test |
| Persistence | Service code persists forecast and evidence transactionally; live row check is implemented | BLOCKED: no dedicated DB or test credentials configured |
| React/API/DB comparison | Real route, values, period/product selectors, PDF signature, Arabic RTL, optional independent SQL calculation | BLOCKED: no authenticated test tenant and local services configured |
| Cross-tenant API isolation | Separate tenant product ID check | BLOCKED: requires two disposable tenants and credentials |
| Starter plan denial | Real API denial check | BLOCKED: requires a disposable Starter token |
| Live AI forecast | Calls the real app generation route once, verifies returned dates and persisted forecast/evidence; bounded to 45 seconds | BLOCKED unless explicitly opted in and configured |
| Historical gaps | AI `data_access.load_daily_demand()` fills every missing calendar date with quantity zero. It does not distinguish verified zero sales from absent rows or a failed ingestion. | APPLICATION RISK FOUND by source audit; needs ingestion completeness semantics before a real-world data-quality test can classify those cases |
| Model predictive quality | Python has 30-day cold-start threshold, baseline comparison, walk-forward validation, MAE/RMSE/MASE and optional XGBoost. No arbitrary exact future-value assertion is used here. | Existing AI unit/backtest suite is separate; live DB/product-quality evaluation was not run |

## Confirmed application integration risk

The Python `pipeline.run_forecast()` creates a multi-step horizon array but sets `expected_demand = forecast_values[-1]`, which is the final step's prediction. The backend Gradio response contract does not include a `prediction_type`, period-total flag, or daily series. The backend then stores the returned scalar with `forecast_start_date = target_date - horizon_days + 1` and `forecast_end_date = target_date`. The GET calculation treats a stored multi-day interval's `expected_demand` as the total for that interval.

The local Python pipeline and backend interval contract have different semantics. Because the hosted Gradio service source was not present in the checked AI repository, I cannot establish that the hosted endpoint returns the same scalar as the Python worker; the live wire behavior remains unverified. The live test logs this ambiguity; it does not claim a correct 7/30-day total from one scalar.

The Python worker writes single-target rows (the interval columns are null) and uses a different persistence path. The app's synchronous backend path stores an interval. These paths therefore cannot be assumed to have interchangeable row semantics.

## Fixture and data safety

- Calculation/service fixtures are in-memory and deterministic, covering complete 7-day rows, incomplete coverage, exact period totals, revisions, overlap, confidence bounds, history actuals, stock aggregation, tenant filters, generation input validation, plan catalog inclusion, and the separate inventory entitlement. 19 forecasting-specific contract assertions passed in the current run; the shared Gradio transport checks are also run by the command.
- No disposable PostgreSQL URL, test tenant, or tokens were configured in this workspace, so no database fixtures were created and no live E2E or AI call was attempted.
- E2E database reads are read-only and RLS-scoped. The live AI run is opt-in because it makes an external call and creates owned forecast/evidence rows; it never truncates or cleans unrelated rows.
- Do not use production credentials. Use a dedicated migrated test DB and a non-superuser application role without `BYPASSRLS`.

## Commands

From `backend/`:

```powershell
# Pure calculations, AI request/transport contracts, controller/service, and entitlement tests
npm run test:demand-prediction:contract

# Real API/UI checks; absent prerequisites are reported as BLOCKED
npm run test:demand-prediction:e2e

# All Demand Prediction modes
npm run test:demand-prediction

# All three dashboard, Market Intelligence, and Demand Prediction E2E suites
npm run test:analytics-e2e

# One E2E file or case
npm run test:demand-prediction:single -- tests/e2e/demand-prediction/overview.spec.ts --grep "overview API"

# Headed browser
$env:DASHBOARD_TEST_HEADED = '1'
npm run test:demand-prediction:headed

# Open the shared Playwright HTML report
npm run test:e2e:report
```

Configure the read-only E2E values in the current PowerShell session before running live checks:

```powershell
$env:DEMAND_PREDICTION_TEST_ACCESS_TOKEN = '<test access token>'
$env:DEMAND_PREDICTION_TEST_TENANT_ID = '<disposable tenant UUID>'
$env:DEMAND_PREDICTION_TEST_USER_ID = '<tenant member UUID>'
$env:DEMAND_PREDICTION_TEST_API_URL = 'http://127.0.0.1:5000'
$env:DEMAND_PREDICTION_TEST_FRONTEND_URL = 'http://127.0.0.1:5173'
$env:DEMAND_PREDICTION_TEST_DATABASE_URL = '<dedicated test/qa/e2e PostgreSQL URL>'
$env:DEMAND_PREDICTION_TEST_OTHER_TENANT_PRODUCT_ID = '<product UUID from a second disposable tenant>'
$env:DEMAND_PREDICTION_STARTER_ACCESS_TOKEN = '<disposable Starter tenant token>'
```

The Live AI test also needs a test product with historical transaction rows. It performs one request with a 45-second timeout and writes forecast/evidence rows:

```powershell
$env:DEMAND_PREDICTION_RUN_LIVE_AI = '1'
$env:DEMAND_PREDICTION_LIVE_AI_PRODUCT_ID = '<seeded test product UUID>'
$env:DEMAND_PREDICTION_LIVE_AI_HORIZON_DAYS = '7'
npm run test:demand-prediction:live-ai
```

Screenshots, traces, HTML, Playwright JSON, and structured diagnostic JSON use the shared `tests/reports/e2e/` output. Missing setup is shown as `BLOCKED`; it is not counted as a pass.

## Known limits before release sign-off

1. The test DB, tenants, UI server, API server, browser runtime, and hosted analytics Gradio service were not available/configured here; UI/API/DB consistency and live forecast generation remain unverified.
2. There is no fixture writer/cleanup script yet. The existing tests avoid destructive DB setup, and the workspace has no verified dedicated DB to safely seed.
3. The exact prediction meaning in the active hosted Gradio response needs an owner-confirmed contract. The checked Python pipeline's final-day scalar conflicts with the backend's interval-total interpretation.
4. The AI loader's zero-fill behavior conflates absent calendar rows with verified zero demand.
5. The frontend also has product listing/search/filter/pagination, detail history/charts, model accuracy, inventory recommendations, and PDF components. The Playwright suite now exercises overview values, period/product selection, list search/category/trend filters, pagination state, detail navigation, PDF validity, and Arabic RTL; its real browser/API executions remain blocked until an authenticated environment is configured.

