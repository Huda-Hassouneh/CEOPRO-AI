# Dashboard diagnostics

The Playwright suite compares the real React dashboard and Express API with a read-only, tenant-scoped PostgreSQL calculation. It does not stub the dashboard endpoint or modify the database in standard mode.

## Verified path and formulas

- `/dashboard` → `useDashboardAggregate` → `GET /companies/:companyId/dashboard?periodDays=7|30|90`.
- Backend auth/tenant middleware; controller validates company ID and period. Prisma repository sets `app.current_tenant_id` and `app.current_user_id` transaction-locally and includes tenant filters.
- `Paid Invoices`: count of `invoices` with `payment_status=PAID`, company primary currency, selected `created_at` date range.
- `Revenues`: sum of those invoices' `total_amount`; no currency conversion/refund adjustment in this query.
- `Growth`: `(current - previous) / previous × 100`, rounded to one decimal; null when previous revenue is zero.
- `Total Products`: active `products` count (`deleted_at IS NULL`).
- `Inventory Status`: current inventory rows for active products; zero=out, positive through reorder level=low, remaining=in stock. Health=`round(inStock / inventory rows × 100)`, or null without rows.
- `Tracked Competitors`: `tenant_competitors` count with `is_tracked=true`.
- `Review Sentiment`: average score for in-period tenant reviews marked `ALLOWED` and `SAFE`; >0.1 positive, <-0.1 negative, otherwise neutral.
- Sales chart: UTC daily buckets over the same paid invoice set. Inventory, forecast, competitor and activity sections are not all filtered by the sales period.
- Forecast: up to four product groups for an upcoming seven-day window, gated by `demand_prediction` plan feature.
- Competitor table: active products/mappings/tracked links and latest available, exact, allowed same-currency price; this query has no maximum-age filter.
- Activity: up to 20 newest tenant `audit_logs`.

Dashboard sales are **business invoices**, not Stripe subscription invoices or `transactions`.

## Producer matrix (source inspection only; no runtime AI calls executed)

| Output | Tables read | Producer path found |
| --- | --- | --- |
| Paid invoices/revenue/growth/chart | `invoices` | AI quick-sale can write invoices/items. AI file promotion writes products/transactions, not invoices. |
| Products | `products` | CEOPRO ingestion worker creates/reuses products; AI promotion also writes products. |
| Inventory | `inventory`, `products` | No inventory writer found in inspected extraction promotion path. |
| Tracked competitors | `tenant_competitors` | Market collection/onboarding manages tenant links. |
| Competitor price | mapping/link tables, `competitor_prices` | AI market scraper persists observations. |
| Sentiment | `reviews`, `sentiment_results` | AI sentiment pipeline reads reviews and writes sentiment results. |
| Forecast | `demand_forecasts`, `products` | AI forecast pipeline writes forecast rows; backend gates/summarizes. |
| Recent activity | `audit_logs` | CEOPRO audit records; dashboard does not read ingestion jobs or AI activity endpoint. |

Code-level write capability is not runtime proof. AI code is not modified by this suite.

The backend upload calls the analytics Gradio `extract_file` API through `gradioClient`; it does not call the AI team's FastAPI `/extraction/upload` route. That AI endpoint is a separate code path. The backend persists its extraction response as staged rows, then the CEOPRO ingestion worker promotes valid rows into `products` and `transactions`.

## Test modes and safety

Default API/UI mode reads real app/database data and checks formulas, display values, modals and periods. It is observational; it does not create a clean tenant. Existing `npm run seed:dashboard` provides deterministic Growth/Sentiment records only and requires a pre-existing active product and a DEV/TEST database. It is not a complete dashboard fixture.

**Source-inspection finding to verify:** the backend always fills `salesOverview.points` with one zero-valued bucket per date, while the UI selects its no-sales empty state only when `points.length` is zero. With no qualifying invoices, the chart branch therefore remains selected and the no-sales empty state cannot appear. The suite has a conditional regression assertion for a zero-paid-invoice tenant; it is not runtime verified until that scenario is run.

Live mode uploads a real file to `POST /data-connection`, then polls its real ingestion job. It requires the real Gradio extraction service, `document_extraction` entitlement, a valid canonical template file, and a running worker. It leaves job/import rows as evidence and must only be used on a disposable test tenant.

The DB helper requires a database name containing `test`, `testing`, `qa`, or `e2e`; runs `BEGIN READ ONLY`; sets tenant/user context; leaves RLS enabled; rejects superuser and `BYPASSRLS`. It performs no inserts, updates, deletes, resets or migrations. Reports omit tokens, connection strings and API response bodies.

## PowerShell setup

From the backend repository root, install Playwright and Chromium:

```powershell
npm install
npm install --save-dev @playwright/test
npx playwright install chromium
```

Run backend and frontend servers separately, then:

```powershell
$env:DASHBOARD_TEST_FRONTEND_URL = "http://127.0.0.1:5173"
$env:DASHBOARD_TEST_API_URL = "http://127.0.0.1:5000"
$env:DASHBOARD_TEST_DATABASE_URL = "postgresql://READ_ONLY_TEST_USER:...@localhost:5433/ceopro_ai_test"
$env:DASHBOARD_TEST_ACCESS_TOKEN = "<short-lived local test token>"
$env:DASHBOARD_TEST_TENANT_ID = "<tenant UUID>"
$env:DASHBOARD_TEST_USER_ID = "<token user UUID>"
$env:DASHBOARD_TEST_PERIOD_DAYS = "30"
npm run test:dashboard

# All KPI assertions run together in the cross-layer test
npx playwright test --config playwright.config.ts tests/e2e/dashboard/dashboard.spec.ts -g "metrics agree"

# Focus one KPI across DB, API and UI (valid values: totalSales, totalProducts,
# trackedCompetitors, revenues, growth, inventoryStatus, marketSentiment)
$env:DASHBOARD_TEST_METRIC = "revenues"
npx playwright test --config playwright.config.ts tests/e2e/dashboard/dashboard.spec.ts -g "metrics agree"
Remove-Item Env:\DASHBOARD_TEST_METRIC

# Headed/browser UI modes
$env:DASHBOARD_TEST_HEADED = "1"
npm run test:dashboard:headed
npm run test:dashboard:ui

# Real AI ingestion, only on a disposable test tenant
$env:DASHBOARD_TEST_LIVE_INGESTION = "1"
$env:DASHBOARD_TEST_INGESTION_FILE = "C:\path\to\valid-sales-import.csv"
npm run test:dashboard:live

# Reports
npx playwright show-report tests/reports/dashboard/html
Get-Content tests/reports/dashboard/diagnostics.json
```

`DASHBOARD_TEST_DATABASE_URL` is a read-only verification account, not the backend runtime URL.

| Variable | Meaning |
| --- | --- |
| `DASHBOARD_TEST_FRONTEND_URL`, `DASHBOARD_TEST_API_URL` | Real app origins; local defaults are 5173/5000 |
| `DASHBOARD_TEST_DATABASE_URL` | Read-only test DB connection |
| `DASHBOARD_TEST_ACCESS_TOKEN` | Valid short-lived tenant member token |
| `DASHBOARD_TEST_TENANT_ID`, `DASHBOARD_TEST_USER_ID` | IDs in token, DB, and tenant RLS context |
| `DASHBOARD_TEST_PERIOD_DAYS` | 7, 30, or 90; defaults to 30 |
| `DASHBOARD_TEST_METRIC` | Optional KPI ID to focus a run on one metric |
| `DASHBOARD_TEST_OTHER_TENANT_ID` | Optional unrelated tenant for isolation probe |
| `DASHBOARD_TEST_HEADED` | `1` opens Chromium visibly |
| `DASHBOARD_TEST_LIVE_INGESTION` | Exactly `1` enables live upload test |
| `DASHBOARD_TEST_INGESTION_FILE` | Valid canonical CSV/XLSX for live mode |

## Reports and coverage limits

Playwright produces HTML/JSON outcomes, failure screenshots, video and traces. `tests/reports/dashboard/diagnostics.json` adds PASS/FAIL/SKIP/BLOCKED/ERROR, duration, tenant, metric expected/actual notes and failure category. Missing configuration is BLOCKED, not passed. Browser failures log method/path and sanitized message only. Generated reports are gitignored.

| Feature | UI | API | DB | AI link | Current evidence |
| --- | --- | --- | --- | --- | --- |
| Products | KPI | count | `products` | Ingestion | Implemented; not run |
| Paid invoices | KPI | count | `invoices` | Quick-sale; file import doesn't write invoices | Implemented; not run |
| Revenue | currency display | sum | `invoices` | Same | Implemented; not run |
| Growth | signed/null | formula | current/previous invoices | Same | Implemented; not run |
| Inventory | KPI/chart/modal | totals | inventory/products | No extraction writer found | Implemented; not run |
| Sentiment | label/null | label | reviews/results | Sentiment AI | Implemented; not run |
| Competitors | count/table | count/rows | links/mappings/prices | Market scraper | Implemented; not run |
| Sales chart | render/periods | daily points | invoice date buckets | Invoice producer | Implemented; not run |
| Forecast | presence | gated rows | forecast/product/plan | Forecast AI | Presence only; numeric DB reconciliation not implemented |
| Recent activity | table/modal | recent rows | `audit_logs` | CEOPRO audit writer | UI/modal only; row reconciliation not implemented |
| Entitlements | route/forecast | access behavior | plan features | N/A | Needs a separate no-entitlement tenant |
| Live ingestion | N/A | actual upload | job/staging | Gradio + worker | Opt-in; blocked until configured |

An uploaded file is staged, then CEOPRO's worker promotes valid sales into `products` and `transactions`. Dashboard Paid Invoices and Revenue read `invoices` only. A successful sales import alone should not be interpreted as proof those KPIs changed.
