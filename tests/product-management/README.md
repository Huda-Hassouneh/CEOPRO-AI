# Product Management diagnostics

This suite reuses the shared Playwright configuration, HTML/JSON reporters, and the read-only RLS database support used by Dashboard, Market Intelligence, and Demand Prediction. It does not create products or replace the missing Product Management module with fake CRUD behavior.

## Current implementation map

| Workflow/layer | Source checked | Current behavior | Evidence status |
|---|---|---|---|
| Product list/create/update client | `frontend/src/features/products/api/productsApi.js` | List returns `[]`; detail returns `null`; create/update echo payload with `ok: true`; no HTTP request | Source-contract test PASS; real CRUD E2E BLOCKED |
| Product components/routes | `frontend/src/features/products/components/*`, `frontend/src/app/router/index.jsx` | ProductForm/ProductTable/QuickSaleModal are placeholders. The only `ProductDetailPage` is a competitor preview route under `/market/competitors/...`; no tenant catalog route is registered | Source-contract test PASS; UI lifecycle BLOCKED |
| Node product API | `backend/src/modules/` | No dedicated products/Product Management module or route found | Source-contract test PASS; CRUD/security E2E BLOCKED |
| Product database | `backend/prisma/schema.prisma`, baseline migration | Tenant UUID identity, bilingual JSON metadata fields, nonnegative current/cost prices, currency, source, `deleted_at`; inventory, imports, forecasts, invoices and competitor mappings reference the composite tenant/product key | Source-contract test PASS; live RLS snapshot requires named test DB and active test membership |
| Price history | `backend/prisma/migrations/20260800000000_baseline/migration.sql` | Trigger logs `current_price` changes on UPDATE only. No initial-price row; currency-only change is not captured. It records `NEW.currency` with the price change | Source-contract test PASS; trigger execution BLOCKED without approved DB |
| Standard-plan access and capacity | `backend/src/config/production-plans.ts`, `backend/src/modules/features/service/capacity.service.ts` | `product_management` is included in Starter/Growth/Enterprise; `tracked_products` caps are 250/2,000/10,000; usage counts rows with `deleted_at IS NULL` | Source-contract test PASS; write enforcement BLOCKED because no manual product write route exists |
| Imported product matching | `backend/src/modules/dataconnection/route/dataconnection.route.ts`, `backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts` | Upload is authenticated/tenant-scoped and requires `document_extraction`; response means extraction queued. Worker matches tenant + trimmed lower-case English name, uses advisory transaction lock, reuses existing ID, and does not update existing price. New rows are `source=IMPORTED`; completed staging rows protect worker retries within a job | Source-contract test PASS; live service+DB path BLOCKED (no approved fixture setup) |
| Repeated upload / identity | Worker resolver and `products` schema | No first-class SKU/external product identifier. Arabic-only names do not have an explicit Arabic matching branch. No file/source-row idempotency key was found in the Node worker; new jobs can repeat transaction rows | Source-contract test PASS; duplicate-prevention E2E BLOCKED; keep as regression risk |
| Import capacity | Worker SQL and `20261006120000_business_data_ingestion_worker` | Worker is granted product SELECT/INSERT and transaction INSERT. No `tracked_products` check appears in the product creation transaction | Source-contract test PASS; `PRODUCT_LIMIT_BYPASS` retained as a live regression target |
| Inventory | `inventory` Prisma model and migration | Multiple warehouse rows per product are allowed. `stock_quantity >= 0`; reorder and safety thresholds default to 10 and 5. No unique tenant/product inventory constraint dictates aggregation | Source-contract test PASS; live warehouse data/aggregation BLOCKED |
| Quick Sale | `ai/src/ai/main.py`, `ai/src/ai/sales/quick_sale.py`, frontend `quickSaleApi.js` | AI FastAPI exposes authenticated `/sales/quick-sale`, writing one PAID invoice and invoice item. This route is separate from the frontend's `{ok:true,payload}` stub. The request model has no positive quantity/nonnegative price bounds or idempotency key; DB constraints reject invalid writes after the request reaches persistence. Quick Sale does not write imported `transactions` or decrement inventory in this function | Source-contract test PASS; connected frontend persistence BLOCKED |
| Downstream data | Dashboard, forecasting, competitor mapping and sales schema | These use tenant/product identity and have composite foreign keys. There is no CRUD write to exercise rename/archive lifecycle consistently | Existing feature suites are unchanged; mutation consistency BLOCKED |
| RLS | Baseline migration | Product, price history and inventory tables enable/force RLS with tenant context and membership checks. Cross-tenant product/history E2E still needs two verified identities and product API routes | Source-contract test PASS; live RLS check BLOCKED |
| AI/extraction ownership | Node Gradio client, `ai/src/ai/extraction/{ingestion_pipeline,promotion}.py`, Node ingestion worker | Node upload calls hosted Gradio extraction and its own staging/worker pipeline. AI FastAPI also has `/extraction/upload` and synchronously promotes to products/transactions. They are separate writers and were not run together | Local source contract PASS; neither actual hosted Gradio nor AI DB path runtime-verified |

## Coverage matrix (current run evidence)

| Test area | Frontend | Backend | Database | AI/Worker | Result |
|---|---|---|---|---|---|
| Product create/read/update/archive | Stubs/placeholders | No CRUD module | Schema/RLS contract only | N/A | **BLOCKED_NOT_IMPLEMENTED** |
| Search/filter/pagination/localization | No tenant catalog page | No list API | No fixture | N/A | **BLOCKED_NOT_IMPLEMENTED** |
| Price history | Hook/component placeholders | No update API | Trigger source inspected; initial/currency-only gaps confirmed | N/A | Contract PASS; trigger DB execution BLOCKED |
| Standard plan product limits | No product flow | Catalog and usage resolver exist; no write endpoint | No test DB | Worker bypass check absent | Catalog contract PASS; write enforcement BLOCKED / regression gap |
| Duplicate prevention / curated price | No import UI | Worker matching code inspected | No safe fixture DB | Worker enforces per-tenant English-name match only | Source contract PASS; repeated-file E2E BLOCKED / dedupe risk |
| File ingestion | Upload UI exists for data connections, not product CRUD | Extract→stage→worker route exists | Live writes not attempted | Gradio extraction/worker path not live-verified | Contract PASS; live AI BLOCKED |
| Inventory relationships | Inventory API returns empty list | No Product Management inventory API | Multi-row schema inspected | Inventory feed not verified | Schema contract PASS; UI/API BLOCKED |
| Quick Sale | API returns success locally | No Node connector | AI integration DB fixture not run | AI endpoint + invoice persistence code exists | AI source contract PASS; frontend persistence BLOCKED |
| Downstream consistency | Dashboard shows active product count | Existing readers remain unchanged | Read-only helper added | N/A | Existing suite coverage preserved; product mutation flow BLOCKED |
| Tenant isolation | No product route/UI | Route checks unavailable for products | RLS and FK contracts inspected | N/A | Static contract PASS; two-tenant runtime test BLOCKED |
| AI extraction | No connected product path | Node's Gradio/worker flow | No fixture DB | AI repo extraction implementation inspected separately | Not runtime-verified |

`PASS` on a source-contract test means the test correctly verified the inspected implementation/schema contract; it does **not** mean the blocked business workflow works. The Playwright reporter maps explicit `test.skip` gates to `BLOCKED` and preserves the failure category and recommendation.

## Execution record

- `npm run test:product-management:contract`: **11 passed, 0 failed**. Checks frontend/API stubs, missing backend CRUD routes, schema and RLS relationships, price trigger scope, plan limits, import identity/capacity, both AI import ownership paths, Quick Sale separation/request gaps, and the read-only test helper/reporter.
- `npm run test:product-management:e2e`: **13 BLOCKED**, 0 pass/fail. Product UI/API routes and approved fixtures are absent. These are deliberate block results, not successful lifecycle tests.
- `npm run test:e2e`: **25 BLOCKED**, 0 pass/fail. Existing Dashboard, Market Intelligence, and Demand Prediction E2E cases also had no configured credentials/servers; all stayed in the shared report as BLOCKED. Product Management added 13 explicitly categorized cases.
- `npx tsc --noEmit`: **passed** for the backend TypeScript project.
- `npm run test:dashboard:contract`: **passed**. `npm run test:demand-prediction:contract`: **29 passed**. Existing `npm run test:market-intelligence:contract`: **2 passed, 4 failed** on its pre-existing missing `market_intelligence`, `ai_pricing`, and `market_perception` backend entitlement guards; no Market Intelligence source/tests were changed.
- Python AI tests and PostgreSQL integration tests were **not run**: `pytest` is not installed, and no safe dedicated test database/tenant credentials are configured. No database writes or live AI calls were made.
- The Product Management specification and completion checklist were read from Library. The exact Library `ai codebase.zip` record was resolved, but materialization failed with `hosted apps tools/list request failed: network`; therefore the AI code status above is based on the checked-out local `ai/` tree, not a verified byte-for-byte comparison with that ZIP.

Shared artifacts from the combined Playwright run: `tests/reports/e2e/html/index.html`, `tests/reports/e2e/playwright-report.json`, `tests/reports/e2e/diagnostics.json`, and `tests/reports/e2e/artifacts/`. Skipped product tests have no screenshots/traces because Playwright only captures those on failure.

## Tests and modes

- `tests/product-management/product-management-contract.test.ts`: source/schema contracts for stubs, route absence, trigger behavior, RLS relations, entitlements, import matching/capacity, and AI Quick Sale separation. It does not mock product CRUD.
- `npm run test:product-management:integration` is the source/schema integration-contract alias. No destructive/live PostgreSQL integration is run until a dedicated test database, safe role, and fixture cleanup plan are available.
- `tests/e2e/product-management/product-management.spec.ts`: real lifecycle scenarios are explicitly blocked until there are real routes, a frontend, or an approved test fixture. Each row records expected/actual behavior, tenant/product IDs (if supplied), related tables, component ownership, category, and investigation recommendation in the shared diagnostic report.
- `tests/support/diagnostics/dashboard-db.ts`: adds a read-only Product Management snapshot across products, price history, inventory, transactions, invoices/items, forecasts, and competitor mappings. It rejects ambiguous DB names, production mode, superuser/BYPASSRLS roles, and non-UUID product IDs; sets tenant and user context and starts a read-only transaction.
- `tests/support/diagnostics/dashboard-reporter.ts`: recognizes Product Management modes/categories and includes blocked-test annotations in JSON/console diagnostics. Playwright already retains failure screenshots and traces.
- Live upload is not executed by default. Even with the opt-in script, no upload is made until there is a known disposable DB/tenant plus a safe cleanup/ownership contract. AI tests using `AI_TEST_DATABASE_URL` were not run because this workspace has no approved DB configured and the existing Python fixtures do not prove a non-superuser/RLS-safe test target before inserts.

## Database tables inspected

`products`, `product_price_history`, `inventory`, `transactions`, `invoices`, `invoice_items`, `competitor_product_mappings`, `demand_forecasts`, `data_sources`, `ingestion_jobs`, `import_staging_rows`, plus plan/feature catalogs and tenant membership used by RLS.

No fixture writer or cleanup script is included. This suite will not create tenants/products, disable RLS, mutate unrelated tenants, truncate tables, or call an external AI service.

## PowerShell commands

Run from `backend`:

```powershell
npm run test:product-management:contract
npm run test:product-management:integration
npm run test:product-management:e2e
npm run test:product-management
npm run test:product-management:headed
npm run test:product-management:single -- tests/e2e/product-management/product-management.spec.ts -g "Quick Sale"
$env:PRODUCT_TEST_LIVE_INGESTION = "1"; npm run test:product-management:live-ai
npm run test:e2e:report
npm run test:all-features
```

The AI ingestion command remains blocked until the database and cleanup requirements documented above are satisfied. Existing Dashboard, Market Intelligence and Demand Prediction tests/scripts are preserved. `npm run test:feature-e2e` runs their E2E suites plus Product Management diagnostics; `npm run test:all-feature-contracts` runs their contract checks and the new Product Management source contract.

Reports use the shared locations under `tests/reports/e2e/`: `html/`, `playwright-report.json`, `diagnostics.json`, and failure artifacts in `artifacts/`.
