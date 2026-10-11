# CEOPRO-AI — Feature 06: Product Management

## 1. Executive summary

**Product Management is the business's source of truth for what it sells.** It should let authorized staff add, inspect, edit, search, archive and price products, associate inventory, and understand price changes—without corrupting historical sales or forecasts.

For example, a clothing store imports last month's transactions for a jacket, edits its displayed selling price from JOD 35 to JOD 37, and checks the stock and price history. CEOPRO should preserve the jacket's canonical ID, preserve past transaction prices, record the new catalog price and user attribution, and update downstream screens consistently. Importing another file should not create a duplicate jacket or silently revert its curated price.

**Current conclusion:** Database and sales-import product creation are real; the product-management UI components are placeholders and their API is stubbed. No dedicated Node Product Management CRUD module/routes were identified in the reviewed backend snapshot. AI services support sales extraction and a separate FastAPI Quick Sale but do not replace a proper CEOPRO product-management API.

## 2. Customer-facing business scenarios

1. **Create product:** Enter a product name, selling price, currency, optional Arabic/English brand, category and description, and an optional cost price. New product appears immediately in the correct tenant catalog.
2. **Import products from sales:** Upload an existing sales file. Recognized products are linked to their existing IDs; genuinely new products are created. Transaction history is attached to the correct products.
3. **Change selling price:** An authorized staff member changes a price; the new catalog value is saved and a price-history entry is created. Historical transaction `unit_price` values are untouched.
4. **Review stock:** Product detail shows available inventory with warehouse context and freshness, never confusing unknown stock with zero stock.
5. **Archive a product:** A soft-deleted product disappears from active selection/counts while historic records and related evidence are preserved under an explicit policy.
6. **Record a quick sale:** A completed sale should create a trustworthy sales document and, if stock accounting is supported, update inventory in a consistent transaction. The AI team already has an isolated Quick Sale implementation, but the CEOPRO frontend/backend connection is missing.

## 3. Subscription availability

Verified in `backend/src/config/production-plans.ts`:

| Standard plan              | `product_management` | `tracked_products` limit |
| -------------------------- | -------------------- | -----------------------: |
| Starter — USD 55/month     | Included             |                      250 |
| Growth — USD 140/month     | Included             |                    2,000 |
| Enterprise — USD 350/month | Included             |                   10,000 |

`tracked_products` is a separate **maximum capacity** feature (lifetime), not a monthly allowance. Its existing capacity resolver counts products for the tenant where `deleted_at IS NULL` (`backend/src/modules/features/service/capacity.service.ts`). Do not confuse the ability to manage products (`product_management`) with the allowed number of active products (`tracked_products`). For custom plans, read the actual entitlement rather than hard-coding a standard tier.

**Gap:** The current Data Connection ingestion worker creates products but no `tracked_products` capacity check was identified in that product-creation path. The intended behavior at the limit (reject extra products, quarantine their rows, or allow imports that only reference existing products) needs a deterministic, concurrency-safe policy. Product CRUD must enforce both feature access and the capacity limit server-side.

## 4. Current implementation — verified code

| Layer                                         | Code / behavior                                                                                                              | Assessment                                                                                      |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Frontend product API                          | `src/features/products/api/productsApi.js`: list returns `[]`; get returns null; create/update echo a payload                | **Stub, no persistence**                                                                        |
| Frontend inventory API                        | `src/features/products/api/inventoryApi.js`: returns `[]`                                                                    | **Stub**                                                                                        |
| Frontend quick sale API                       | `src/features/products/api/quickSaleApi.js`: returns `{ok:true,payload}`                                                     | **Stub**                                                                                        |
| Product components                            | `ProductForm`, `ProductTable`, `QuickSaleModal`, `StockLevelBadge`, `PriceHistoryChart`, `MultilingualFieldEditor`           | **Text placeholders**                                                                           |
| Price history hook                            | `src/features/products/hooks/usePriceHistory.js` returns empty history                                                       | **Stub**                                                                                        |
| Product detail page                           | `src/features/products/pages/ProductDetailPage.jsx` reads static `competitorProducts` from Market Intelligence preview data  | **Not the tenant catalog product detail**                                                       |
| Frontend product route                        | `/market/competitors/:competitorId/products/:productId`                                                                      | **Competitor preview**, guarded by `market_intelligence`; no tenant product catalog route found |
| Node backend                                  | No dedicated `src/modules/products` or dedicated product-management CRUD routes found                                        | **Missing**                                                                                     |
| Node ingestion worker                         | `src/modules/dataconnection/repo/ingestion-worker.repo.ts` creates products on first appearance, then creates `transactions` | **Implemented**                                                                                 |
| Dashboard / forecasting / market intelligence | Read existing `products`                                                                                                     | **Data consumer implemented**                                                                   |
| AI extraction                                 | `src/ai/extraction/promotion.py` inserts missing products and sales transactions in its own extraction path                  | **Implemented in AI repository; distinct from current Node Gradio path**                        |
| AI Quick Sale                                 | `POST /sales/quick-sale` in `src/ai/main.py`, implemented by `src/ai/sales/quick_sale.py`                                    | **Creates `invoices` and `invoice_items`; not wired to frontend stub**                          |
| Product price history                         | Baseline SQL trigger `log_price_change`                                                                                      | **Records changes to `current_price` on UPDATE**                                                |

Implementing a new product-management feature should reuse the existing React styling and CEOPRO Route → Controller → Service → Repo conventions, but the routes listed in §9 are proposals, not existing endpoints.

## 5. Database ownership and relationships

| Table                                                   | Role                                                                                                               | Current main writer / reader                                                  |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| `products`                                              | Canonical product identity, bilingual metadata, current and cost price, currency, source, actor IDs, soft deletion | Node ingestion worker; AI extraction promotion; downstream readers            |
| `transactions`                                          | Imported historical quantity, unit price, total, currency and transaction date                                     | Node ingestion worker; AI extraction promotion; forecasting/analytics readers |
| `inventory`                                             | Product stock quantity, reorder level, safety stock, optional warehouse                                            | Existing schema and readers; production feed not verified in reviewed code    |
| `product_price_history`                                 | Old/new catalog selling prices, currency, actor and change time                                                    | PostgreSQL trigger on `products.current_price` updates                        |
| `invoices` + `invoice_items`                            | Manually entered completed sales in AI Quick Sale                                                                  | AI FastAPI Quick Sale                                                         |
| `competitor_product_mappings`                           | Link own products to competitor items                                                                              | Competitor-discovery/mapping workflows                                        |
| `demand_forecasts`                                      | Product-level demand predictions                                                                                   | Forecasting pipeline                                                          |
| `data_sources`, `ingestion_jobs`, `import_staging_rows` | Import provenance, per-row validation, processing status                                                           | Node upload/service/worker, and a separate AI extraction path                 |
| `features`, `plans`, `plan_features`, subscriptions     | Access and product capacity                                                                                        | Billing/entitlement system                                                    |

**Schema facts:** `products.product_id` is a UUID; `tenant_id` scopes it; `product_name`, `brand`, `category` and `description` are JSON fields; `current_price` and `cost_price` use decimal types; `deleted_at` supports soft deletion. The reviewed `products` schema has **no first-class SKU/barcode/external product identifier**. Do not invent one in the UI/API contract; determine whether an additive schema migration is warranted before reliable external synchronization.

## 6. Product creation and identity rules

**Current Node ingestion flow:**

`POST /companies/:companyId/data-connections` → Gradio `extract_file` → local staging (`import_staging_rows`) → Node ingestion worker → product lookup/create → `transactions` insert.

The Node worker matches products using a case-insensitive trimmed **English** product name scoped to a tenant, and creates a product only when no match is found. It uses a Postgres advisory transaction lock to reduce concurrent duplicate creation. Existing product catalog prices are not updated by the import. The AI team's `promotion.py` likewise uses English-name matching and deliberately preserves an existing price when importing historical sales.

**Gaps and decisions:**

- Names alone are unreliable identifiers: typos, spelling variations, language differences and same-name variants can merge or split products incorrectly.
- There is no schema-level tenant + canonical SKU uniqueness in the reviewed model.
- English-only product creation does not automatically populate Arabic translations.
- Re-importing the same sales rows in separate jobs may duplicate `transactions` unless a source-row idempotency policy is introduced; the Node worker's committed staging status only protects retries within a job.
- Resolve conflicts between manually curated fields and later imports with explicit precedence rules; do not overwrite intentional user edits.
- Imports that introduce products must honor `tracked_products` limits without accidental partial/over-capacity creation.

## 7. Business calculations and invariants

| Item                        | Definition                                                                                    | Current implementation / decision                                                            |
| --------------------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Active product count        | `COUNT(products)` where `tenant_id = T AND deleted_at IS NULL`                                | Implemented in dashboard and capacity resolver                                               |
| Available stock for product | Sum of eligible `inventory.stock_quantity` across that product's warehouse records            | **Recommended** aggregation; define warehouse and stale-data policy                          |
| Stock status                | Compare verified available quantity with reorder level / safety stock                         | Define aggregation when inventory spans warehouses; do not treat missing records as zero     |
| Gross margin percentage     | `(selling_price - cost_price) / selling_price × 100` when same currency and selling price > 0 | **Proposed**, not currently exposed as a verified product-management metric                  |
| Product sales units         | `SUM(transactions.quantity_sold)` over an explicit time window                                | Historical-import metric; clarify separate `invoice_items` channel and avoid double counting |
| Product sales value         | `SUM(transactions.total_price)` under explicit period/currency/source rules                   | Not interchangeable with paid invoice revenue; reconcile sources                             |
| Price change %              | `(new_price - old_price) / old_price × 100` when old price > 0                                | **Proposed** display formula; actual DB trigger records old/new prices                       |

**Price-history trigger nuance:** In `prisma/migrations/20260800000000_baseline/migration.sql`, `trigger_log_price_change()` inserts a history row only if `NEW.current_price IS DISTINCT FROM OLD.current_price`. Therefore a newly inserted product has **no initial price-history entry** from this trigger, and a **currency-only change** does not create an entry. Both need a consciously specified audit policy. A selling-price edit must never retroactively change existing `transactions.unit_price` or `invoice_items.unit_price`.

## 8. AI team's role versus CEOPRO backend ownership

**CEOPRO backend should own:** product CRUD, authorization, field validation, tenant isolation, stable product IDs, import matching policy, capacity enforcement, audit attribution, product read APIs, and customer-facing product price-history queries.

**AI/extraction services should own:** extraction/normalization of external sales records and any approved business-data mapping. They can suggest matches but should not become a second unconstrained authority for user-maintained catalog fields.

**AI repository currently implements:** `src/ai/extraction/promotion.py` for product and transaction promotion, and `src/ai/sales/quick_sale.py` for one paid invoice + invoice item per manual sale. AI Quick Sale does **not** create an imported `transactions` row and does **not** update `inventory.stock_quantity` in that function. If CEOPRO promises stock deduction, implement and validate a separate, atomic stock-ledger/reservation policy instead of assuming it already happens.

**Integration question:** CEOPRO's Node data-connection route currently calls hosted Gradio extraction and persists local jobs. That is distinct from AI FastAPI `POST /extraction/upload`. Do not invoke both persistence pipelines for the same file and accidentally duplicate business data. Determine one authoritative production upload path.

## 9. Recommended implementation scope

1. **Product service:** Introduce `src/modules/products/` using `index.ts`, `route/`, `controller/`, `service/`, `repo/`, `types/`, validators, and README per project convention.
2. **Proposed API contract (not implemented):** `GET /companies/:companyId/products`, `POST /companies/:companyId/products`, `GET /companies/:companyId/products/:productId`, `PATCH /companies/:companyId/products/:productId`, `DELETE /companies/:companyId/products/:productId` (soft delete), `GET /companies/:companyId/products/:productId/price-history`, and inventory reads if authorized.
3. **Access:** Enforce `product_management` on product management routes, `tracked_products` capacity on all new product creation paths including imports, and appropriate role-level edit privileges.
4. **Product identity:** Decide canonical SKU/external-ID support, tenant-scoped uniqueness, conflict resolution and naming/translation conventions.
5. **Catalog integrity:** Atomic updates, price history, soft-delete semantics, source precedence, cost/price/currency validation, actor audit fields.
6. **Frontend:** Replace API stubs with real HTTP clients and React Query mutation invalidation. Build tenant product list, form, detail, stock and price-history UI with i18n and RTL support. Do not reuse the competitor-preview route as the own-product CRUD page.
7. **Quick Sale:** Decide whether to expose Node-controlled Quick Sale proxy/service to AI FastAPI. Document whether and how it affects invoices, inventory and transaction-based metrics. Never return success before a record is committed.
8. **Other feature boundaries:** `product_management` provides factual product/stock data; advanced replenishment decisions remain subject to `inventory_intelligence`, and forecasting requires `demand_prediction`.

## 10. Highest-priority gaps

| Priority | Gap                                                              | Why it matters                                                 |
| -------- | ---------------------------------------------------------------- | -------------------------------------------------------------- |
| P0       | Stub frontend product APIs and placeholder components            | Product CRUD appears present in code but has no persistence    |
| P0       | No customer-facing product CRUD backend/API found                | Cannot safely add/edit/archive own catalog                     |
| P0       | `tracked_products` not enforced in import promotion              | A plan's product limit can potentially be exceeded             |
| P0       | Product identity relies heavily on English name                  | Duplicate/wrongly merged products corrupt downstream analytics |
| P1       | No verified automatic inventory feed or functional inventory API | Stock displays cannot be trusted                               |
| P1       | Price history initial/currency-only changes and actor policy     | Historical audit trail may be incomplete                       |
| P1       | Quick Sale stub not integrated with AI endpoint                  | Apparent sales success does not persist                        |
| P1       | Potential duplicate transactions across re-imported files        | Forecasts/sales analytics may be inflated                      |
| P1       | No full tenant product UI / localization flow                    | Users cannot review/manage data reliably                       |
| P2       | SKU/external-ID support and external sync conflict resolution    | Scalability of integrations and product matching               |

## 11. End-to-end test plan

Reuse the existing Dashboard/Market Intelligence/Forecasting Playwright and diagnostic infrastructure; do not start a second runner.

### Deterministic integration and E2E

- [ ] **Create:** Valid bilingual product creates one tenant-owned DB row and appears in list/details.
- [ ] **Validation:** Reject missing names, invalid currency, negative/non-numeric prices, incorrect cost, overlong fields and malformed JSON.
- [ ] **Read/filter:** Search, paginate, sort, filter archived/active records and test RTL/translation displays.
- [ ] **Update:** Changing catalog price records exactly one price-history entry, actor and timestamp; old sales remain unchanged.
- [ ] **Price edge cases:** No false entry for identical price; verify currency-only change policy and first-price baseline.
- [ ] **Capacity:** 250/2,000/10,000 product limits and custom-plan limits; boundary +1; concurrent requests/imports cannot exceed limit.
- [ ] **Imports:** Existing product reused; new product created; different tenants isolated; duplicate names/variants and re-imported files handled per approved identity/idempotency policy.
- [ ] **Archival:** Soft delete excludes active listings and capacity count, but preserves historic references; prohibit unauthorized destructive deletion.
- [ ] **RLS/permissions:** Tenant A cannot read/edit/archive Tenant B products or price history. Test standard role permissions and missing product entitlement.
- [ ] **Inventory:** Known-zero vs unknown stock, warehouse aggregation, stale snapshot and foreign-product records.
- [ ] **Quick Sale:** Real persisted paid invoice and invoice item if integration enabled; no phantom success; no double counting; stock effects match documented behavior.
- [ ] **Downstream consistency:** Dashboard product count, Forecasting product selector, Market Intelligence mappings and sales detail reflect the same canonical IDs.
- [ ] **Reliability:** API timeouts, failed transactions, retries, optimistic/concurrent edits, stale React Query cache, loading/error/empty states.

### Optional real AI integration

- [ ] Upload a real template through the supported production upload path, poll the Node ingestion worker, and verify staging statuses plus product/transaction persistence.
- [ ] Verify AI FastAPI extraction in a **separate, explicitly enabled** contract/integration suite; never double-promote the same source rows.
- [ ] Verify real Quick Sale through AI FastAPI only with safe dedicated test tenant and authorized credentials.

Classify results as PASS, FAIL, SKIP, BLOCKED, or ERROR; log expected DB values, API payloads, UI display, business formulas, source job IDs and failure category. Run against a verified test database only; never truncate Render production or bypass RLS.

## 12. Acceptance criteria / release gate

- [ ] Real product CRUD replaces all success-shaped stubs; no fake records shown as persisted.
- [ ] Product identity, import matching, translation and duplicate handling are specified and tested.
- [ ] Product and capacity entitlements are enforced server-side across manual and imported creation.
- [ ] Prices, history, permissions, currency and source provenance are correct.
- [ ] Inventory information is available, appropriately scoped and accurately labeled as known/unknown.
- [ ] Quick Sale integration and stock behavior have a verified production contract or are clearly hidden/disabled.
- [ ] Dashboard/Forecasting/Market Intelligence consumers continue to work after product edits/archival.
- [ ] E2E, integration, multi-tenant/RLS, localization and error-state tests are green or explicitly blocked with documented prerequisites.

---

**Source-reference map:**

- Frontend: `src/features/products/api/{productsApi,inventoryApi,quickSaleApi}.js`, `src/features/products/components/`, `src/features/products/pages/ProductDetailPage.jsx`, `src/app/router/index.jsx`, `src/app/router/routePaths.js`.
- Backend: `src/config/production-plans.ts`, `src/modules/features/{catalog.ts,service/capacity.service.ts}`, `src/modules/dataconnection/{route/dataconnection.route.ts,service/dataconnection.service.ts,repo/ingestion-worker.repo.ts}`, `src/modules/dashboard/repo/dashboard.repo.ts`, `prisma/schema.prisma`, `prisma/migrations/20260800000000_baseline/migration.sql`.
- AI: `src/ai/extraction/promotion.py`, `src/ai/sales/quick_sale.py`, `src/ai/main.py`.

_This specification documents verified snapshot behavior separately from proposed implementation. Validate against the current working branches before applying code changes._
