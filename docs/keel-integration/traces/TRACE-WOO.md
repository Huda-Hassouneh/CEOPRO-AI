# Source trace refinement — WOO

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified WOO lineage](../evidence/phase0r/SCHEMA_LINEAGE_WOO.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: IMPORT-001

## WOO-001 — HTTPS URL SSRF DNS protection

Proposed behavior remains: Retain provider URL canonicalization/public-address pinned transport and redirect refusal; Python target guard is shared dependency.

Acceptance specification: `AT-WOO-001` — Private/loopback/IP literal; DNS rebinding; embedded credentials. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64. UI: dataConnectionsApi.connectStore/syncStore; ConnectDataPage.jsx REST credential form.

**Exact source roots:** `ai/src/ai/connectors/woocommerce.py:11::store_url | ai/src/ai/connectors/transport.py:32::get_json | ai/src/ai/connectors/transport.py:16::PublicConnection.connect`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: No WooCommerce UI/adapter/normalizers; nearest generic API is /onboarding/connect/api.

**Exact source roots:** `backend/src/market_scraper/network_security.py:39::assert_connector_target | backend/src/ai/routers/onboarding.py:28::_check_target`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Dedicated WOO flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## WOO-002 — REST key verification rotation

Proposed behavior remains: Verify actual shop credentials/currency and store encrypted in Python vault; failed verification never consumes permanent source slot.

Acceptance specification: `AT-WOO-002` — 401/403; insufficient scope; key rotation mid-job. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64 | POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33. UI: dataConnectionsApi.connectStore/syncStore; ConnectDataPage.jsx REST credential form.

**Exact source roots:** `ai/src/ai/connectors/woocommerce.py:41::WooCommerce.verify | backend/src/modules/dataconnection/store/connections.repo.ts:31:10::storeConnections.connect`.

**Schema/access:** public.audit_logs; public.companies; public.data_sources; public.ingestion_jobs; public.store_connections; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133. UI: No WooCommerce UI/adapter/normalizers; nearest generic API is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:133::onboarding_connect_api`.

**Schema/access:** public.billing_trials; public.data_sources; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Dedicated WOO flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## WOO-003 — Pagination rate bounds backoff

Proposed behavior remains: Retain bounded Woo pages, modified-time overlap and repeated-page detection in durable Python jobs.

Acceptance specification: `AT-WOO-003` — 429/timeout; missing totals; >250 equal-time records. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.connectStore/syncStore; ConnectDataPage.jsx REST credential form.

**Exact source roots:** `ai/src/ai/connectors/woocommerce.py:29::WooCommerce.call | ai/src/ai/connectors/woocommerce.py:81::WooCommerce.products | ai/src/ai/connectors/woocommerce.py:104::WooCommerce.orders | backend/src/modules/dataconnection/store/sync.repo.ts:115:1::syncStorePage`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: No WooCommerce UI/adapter/normalizers; nearest generic API is /onboarding/connect/api.

**Exact source roots:** `backend/src/market_scraper/api_connector_sync.py:85::build_api_fetch_page | backend/src/market_scraper/api_connector_sync.py:176::sync_api_connector_source`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.tenant_storage_objects

**Missing/unequal edge:** Dedicated WOO flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## WOO-004 — Simple variable product inventory

Proposed behavior remains: Port Woo products/variations/barcode and normalized inventory; use shared canonical product/warehouse service.

Acceptance specification: `AT-WOO-004` — Variation lacks parent stock; invalid GTIN; untracked stock. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64. UI: dataConnectionsApi.connectStore/syncStore; ConnectDataPage.jsx REST credential form.

**Exact source roots:** `ai/src/ai/connectors/woocommerce.py:81::WooCommerce.products | ai/src/ai/connectors/inventory.py:10::normalize_inventory`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** PATCH /products/{product_id}/inventory @ backend/src/ai/routers/products.py:616. UI: No WooCommerce UI/adapter/normalizers; nearest generic API is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/routers/products.py:438::upsert_inventory`.

**Schema/access:** public.inventory; public.products

**Missing/unequal edge:** Dedicated WOO flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## WOO-005 — Order status refund normalization

Proposed behavior remains: Port explicit status set, refund line allocation and exact Decimal reconciliation; unsupported refunds fail with operator-visible reason.

Acceptance specification: `AT-WOO-005` — Amount-only refund; negative tax; cancelled paid order. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.connectStore/syncStore; ConnectDataPage.jsx REST credential form.

**Exact source roots:** `ai/src/ai/connectors/orders.py:28::normalize_order | backend/src/modules/dataconnection/store/invoices.repo.ts:29:1::commitStoreInvoice`.

**Schema/access:** public.invoice_items; public.invoices; public.store_order_item_links; public.store_order_links

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /sales/quick-sale @ backend/src/ai/routers/sales.py:27. UI: No WooCommerce UI/adapter/normalizers; nearest generic API is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/sales/quick_sale.py:66::record_quick_sale`.

**Schema/access:** public.inventory; public.invoice_items; public.invoices; public.products

**Missing/unequal edge:** Dedicated WOO flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## WOO-006 — Backfill incremental reconnect live proof

Proposed behavior remains: Persist since/until/excluded IDs and credential version; certify against authorized Woo sandbox after fixture/native tests.

Acceptance specification: `AT-WOO-006` — Historical replay; credential revoked; live sandbox unavailable. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | POST /data-connection/store/:sourceId/sync @ backend/src/modules/dataconnection/store/routes.ts:36. UI: dataConnectionsApi.connectStore/syncStore; ConnectDataPage.jsx REST credential form.

**Exact source roots:** `backend/src/modules/dataconnection/store/sync.repo.ts:91:1::claimStorePage | backend/src/modules/dataconnection/store/sync.repo.ts:115:1::syncStorePage | backend/src/modules/dataconnection/store/connections.repo.ts:69:7::storeConnections.sync`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120 | POST /onboarding/sources/{source_id}/sync @ backend/src/ai/routers/onboarding.py:246. UI: No WooCommerce UI/adapter/normalizers; nearest generic API is /onboarding/connect/api.

**Exact source roots:** `backend/src/market_scraper/connector_worker.py:80::run_connector_syncs_for_tenant | backend/src/ai/routers/onboarding.py:246::sync_source_now`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.tenant_storage_objects; public.tenant_users

**Missing/unequal edge:** Dedicated WOO flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
