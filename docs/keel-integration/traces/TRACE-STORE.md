# Source trace refinement — STORE

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified STORE lineage](../evidence/phase0r/SCHEMA_LINEAGE_STORE.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: ENT-001; IMPORT-001

## STORE-001 — Dedicated provider dispatch ownership

Proposed behavior remains: Implement dedicated adapters inside Python destination; read-only Node ai connectors supply behavior, never run Node provider service as authority.

Acceptance specification: `AT-STORE-001` — Wrong provider contract version; no credentials; bounded response. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/store/detect @ backend/src/modules/dataconnection/store/routes.ts:32 | POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30 | WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/provider.client.ts:4:1::storeProvider | ai/src/ai/connectors/app.py:38::execute | backend/src/modules/dataconnection/store/provider-contract.ts:3:1::validateProviderPage`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:133::onboarding_connect_api | backend/src/market_scraper/api_connector_sync.py:176::sync_api_connector_source`.

**Schema/access:** public.billing_trials; public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_storage_objects; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## STORE-002 — Connection verification source capacity

Proposed behavior remains: Add provider persistent connection under Python data_sources; scope same tenant, active owner/admin, subscription and source count.

Acceptance specification: `AT-STORE-002` — Verified shop identity changed; source already occupied. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33 | POST /data-connection/store/shopify/authorize @ backend/src/modules/dataconnection/store/routes.ts:31 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30 | PATCH /data-connection/sources/:sourceId @ backend/src/modules/dataconnection/route/dataconnection.route.ts:31 | DELETE /data-connection/sources/:sourceId/connection @ backend/src/modules/dataconnection/route/dataconnection.route.ts:36 | GET /data-connection/store/:sourceId/privacy-reports @ backend/src/modules/dataconnection/store/routes.ts:34 | POST /data-connection/store/detect @ backend/src/modules/dataconnection/store/routes.ts:32. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/connections.repo.ts:31:10::storeConnections.connect | backend/src/modules/dataconnection/store/connections.repo.ts:15:1::sourceSlot | backend/src/modules/dataconnection/store/context.ts:6:1::storeContext`.

**Schema/access:** public.audit_logs; public.companies; public.data_sources; public.ingestion_jobs; public.store_connections; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97 | POST /onboarding/sources/{source_id}/sync @ backend/src/ai/routers/onboarding.py:246 | DELETE /onboarding/sources/{source_id} @ backend/src/ai/routers/onboarding.py:256. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:183::_require_admin | backend/src/ai/routers/onboarding.py:133::onboarding_connect_api`.

**Schema/access:** public.billing_trials; public.data_sources; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## STORE-003 — Claim fetch commit fencing

Proposed behavior remains: Port Node 120s lease/version token: claim transaction then HTTP outside DB transaction then reauthorize commit and checkpoint atomically.

Acceptance specification: `AT-STORE-003` — Late fetch after disconnect; expired lease stolen; duplicate page. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/sync.repo.ts:91:1::claimStorePage | backend/src/modules/dataconnection/store/sync.repo.ts:115:1::syncStorePage`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/market_scraper/connector_worker.py:80::run_connector_syncs_for_tenant | backend/src/market_scraper/api_connector_sync.py:176::sync_api_connector_source`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.tenant_storage_objects

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## STORE-004 — Scheduler incremental watermarks retry

Proposed behavior remains: Add provider collector keys to Python worker; checkpoint products/orders page, fixed until, overlap window, capped retry and dead state.

Acceptance specification: `AT-STORE-004` — Same page hash; nonprogress cursor; retry after crash. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/sync.repo.ts:115:1::syncStorePage`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/market_scraper/connector_sync.py:60::is_due_for_sync | backend/src/market_scraper/connector_worker.py:120::run_forever`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.tenant_storage_objects

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## STORE-005 — External product SKU variant ownership

Proposed behavior remains: Add tenant/source/external variant mapping; do not overwrite manually curated product/price ownership.

Acceptance specification: `AT-STORE-005` — Same SKU two stores; parent variation; inactive product. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/sync.repo.ts:26:1::linkProduct | backend/src/modules/dataconnection/repo/import-product.ts:6:1::ensureImportedProduct`.

**Schema/access:** public.product_price_history; public.products; public.store_product_links

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/ai/extraction/promotion.py:368::_alias_names_by_barcode | backend/src/ai/extraction/promotion.py:417::_create_missing_products`.

**Schema/access:** public.billing_trials; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## STORE-006 — Inventory location canonical sync

Proposed behavior remains: Port store_inventory_locations and source ownership to Python inventory schema with additive migration.

Acceptance specification: `AT-STORE-006` — Removed location; missing stock; nonwhole quantity. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/inventory.repo.ts:5:1::commitStoreInventory | backend/src/modules/dataconnection/store/inventory.repo.ts:34:1::commitStoreLocations`.

**Schema/access:** public.inventory; public.store_inventory_links; public.store_inventory_locations

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** PATCH /products/{product_id}/inventory @ backend/src/ai/routers/products.py:616. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/ai/routers/products.py:438::upsert_inventory`.

**Schema/access:** public.inventory; public.products

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## STORE-007 — Order sale invoice reconciliation

Proposed behavior remains: Use provider external order/item identity, transaction plus invoice/item canonical writes; update/refund corrections atomically.

Acceptance specification: `AT-STORE-007` — Duplicate order; out-of-order modification; amount-only refund. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/sync.repo.ts:52:1::commitOrder | backend/src/modules/dataconnection/store/invoices.repo.ts:29:1::commitStoreInvoice`.

**Schema/access:** public.import_staging_rows; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /sales/quick-sale @ backend/src/ai/routers/sales.py:27. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/ai/extraction/promotion.py:462::_insert_invoices_mirror_batch | backend/src/ai/sales/quick_sale.py:66::record_quick_sale`.

**Schema/access:** public.inventory; public.invoice_items; public.invoices; public.products

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## STORE-008 — Persistent status and UI observability

Proposed behavior remains: Add store connection OAuth/verification/progress/errors privacy-report UI under existing ConnectDataPage; no fake successful connection.

Acceptance specification: `AT-STORE-008` — Missing scopes; expired credentials; partial job state. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /data-connection/store/:sourceId @ backend/src/modules/dataconnection/store/routes.ts:35 | POST /data-connection/store/:sourceId/sync @ backend/src/modules/dataconnection/store/routes.ts:36 | DELETE /data-connection/store/:sourceId @ backend/src/modules/dataconnection/store/routes.ts:37. UI: dataConnectionsApi.detectStore/connectStore/syncStore/disconnectStore/storePrivacyReports; ConnectDataPage.jsx.

**Exact source roots:** `backend/src/modules/dataconnection/store/connections.repo.ts:64:9::storeConnections.status | backend/src/modules/dataconnection/store/connections.repo.ts:69:7::storeConnections.sync | backend/src/modules/dataconnection/store/connections.repo.ts:77:13::storeConnections.disconnect`.

**Schema/access:** public.companies; public.store_connections; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /onboarding/sources @ backend/src/ai/routers/onboarding.py:193. UI: ConnectSystemForm generic API/DB only; no dedicated store client/API/worker.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:193::list_connected_sources | frontend/src/features/data-connections/api/dataConnectionsApi.js:36:9::dataConnectionsApi.list`.

**Schema/access:** public.data_sources; public.ingestion_jobs

**Missing/unequal edge:** Dedicated STORE flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
