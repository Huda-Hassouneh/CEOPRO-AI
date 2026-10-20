# Source trace refinement — SHOP

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified SHOP lineage](../evidence/phase0r/SCHEMA_LINEAGE_SHOP.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: IMPORT-001; PRIVACY-001

## SHOP-001 — OAuth install callback state

Proposed behavior remains: Port begin/complete ticket design to Python issuer and existing frontend; HMAC state nonce expiry shop binding and one-use DB state.

Acceptance specification: `AT-SHOP-001` — Duplicate query keys; stale timestamp; wrong tenant/state/shop. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/store/shopify/authorize @ backend/src/modules/dataconnection/store/routes.ts:31 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30 | GET /integrations/shopify/callback @ backend/src/modules/dataconnection/store/shopify/public.routes.ts:8. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `backend/src/modules/dataconnection/store/shopify/oauth.ts:16:1::beginShopifyAuthorization | backend/src/modules/dataconnection/store/shopify/oauth.ts:29:1::completeShopifyAuthorization | backend/src/modules/dataconnection/store/shopify/oauth.ts:67:1::createShopifyCallbackTicket | backend/src/modules/dataconnection/store/shopify/oauth.ts:74:1::finishShopifyTicket | backend/src/modules/dataconnection/store/shopify/security.ts:4:1::validateShopifyCallback`.

**Schema/access:** public.audit_logs; public.companies; public.data_sources; public.ingestion_jobs; public.store_connections; public.store_oauth_states; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:133::onboarding_connect_api`.

**Schema/access:** public.billing_trials; public.data_sources; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SHOP-002 — Authorized scopes shop identity

Proposed behavior remains: Verify GraphQL shop/currentAppInstallation scopes and historyAccess; bind actual shop ID before canonical source activation.

Acceptance specification: `AT-SHOP-002` — Missing read scope; reused domain; recent vs all order history. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `ai/src/ai/connectors/shopify.py:118::Shopify.verify | backend/src/modules/dataconnection/store/shopify/oauth.ts:29:1::completeShopifyAuthorization`.

**Schema/access:** public.audit_logs; public.companies; public.data_sources; public.ingestion_jobs; public.store_connections; public.store_oauth_states; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:133::onboarding_connect_api`.

**Schema/access:** public.billing_trials; public.data_sources; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SHOP-003 — Encrypted access refresh token

Proposed behavior remains: Use Python vault for expiring token/refresh rotation and reconnect, preserving includeTestOrders flag.

Acceptance specification: `AT-SHOP-003` — Concurrent refresh; refresh expired; secret leak in logs. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30 | POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `backend/src/modules/dataconnection/store/shopify/token.ts:5:1::exchangeShopifyToken | backend/src/modules/dataconnection/store/sync.repo.ts:115:1::syncStorePage | backend/src/modules/dataconnection/store/vault.ts:10:1::sealCredentials`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97 | WORKER_OR_PRIVATE python -m scripts.vault_key @ backend/scripts/vault_key.py:90. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/market_scraper/credential_vault.py:192::encrypt_credentials | backend/src/market_scraper/credential_vault.py:276::rewrap_envelope`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SHOP-004 — GraphQL bounded pagination

Proposed behavior remains: Retain Node adapter variants/inventory levels/order lines GraphQL pagination and error sanitization; implement in Python existing worker framework.

Acceptance specification: `AT-SHOP-004` — GraphQL errors/throttle; nested pagination; repeated cursor. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `ai/src/ai/connectors/shopify.py:81::Shopify.call | ai/src/ai/connectors/shopify.py:131::Shopify.products | ai/src/ai/connectors/shopify.py:174::Shopify.orders`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/market_scraper/api_connector_sync.py:85::build_api_fetch_page`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SHOP-005 — Order tax shipping discounts refunds

Proposed behavior remains: Preserve normalized shopMoney and reconciliation; quarantine unsupported amount-only edits rather than invent line allocations.

Acceptance specification: `AT-SHOP-005` — Refund original-total mismatch; test order; cancellation. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE POST /provider private service @ ai/src/ai/connectors/app.py:64 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `ai/src/ai/connectors/shopify.py:197::normalize_order | backend/src/modules/dataconnection/store/invoices.repo.ts:9:1::validateStoreOrder`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/extraction/promotion.py:462::_insert_invoices_mirror_batch`.

**Schema/access:** public.invoice_items; public.invoices

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SHOP-006 — Signed webhook delivery replay

Proposed behavior remains: Add raw-body webhook verifier and unique provider event receipt; topic/shop binding; bounded payload; durable schedule signal.

Acceptance specification: `AT-SHOP-006` — Wrong HMAC; duplicate event; HTTP ack before durable commit. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /integrations/shopify/webhooks @ backend/src/modules/dataconnection/store/shopify/public.routes.ts:13. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `backend/src/modules/dataconnection/store/shopify/security.ts:15:1::verifyShopifyWebhook`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/routers/billing.py:349::stripe_webhook`.

**Schema/access:** public.billing_customers; public.billing_payments; public.billing_plan_prices; public.billing_subscriptions; public.billing_webhook_events; public.tenant_plan_assignments

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SHOP-007 — Uninstall product delete revocation

Proposed behavior remains: Fence leases and remove secrets on uninstall; preserve owned-product semantics and queued job state.

Acceptance specification: `AT-SHOP-007` — Uninstall while syncing; deleted variant with shared product. NOT RUN as an implementation test.

**NODE entry and UI boundary:** DELETE /data-connection/store/:sourceId @ backend/src/modules/dataconnection/store/routes.ts:37 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `backend/src/modules/dataconnection/store/connections.repo.ts:77:13::storeConnections.disconnect | backend/src/modules/dataconnection/store/sync.repo.ts:115:1::syncStorePage`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** DELETE /onboarding/sources/{source_id} @ backend/src/ai/routers/onboarding.py:256. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:256::disconnect_source`.

**Schema/access:** public.data_sources; public.tenant_users

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SHOP-008 — Privacy data request redact

Proposed behavior remains: Port explicit Node privacy event effects and report/exclusion state after retention approval; no blanket deletion of unrelated manual data.

Acceptance specification: `AT-SHOP-008` — Redact queued order; duplicate redact; legal invoice retention. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /integrations/shopify/webhooks @ backend/src/modules/dataconnection/store/shopify/public.routes.ts:13. UI: dataConnectionsApi.authorizeShopify/finishShopify/storePrivacyReports; ConnectDataPage.jsx OAuth fragment ticket.

**Exact source roots:** `backend/src/modules/dataconnection/store/shopify/security.ts:15:1::verifyShopifyWebhook`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** DELETE /settings/company @ backend/src/ai/routers/settings.py:336 | GET /settings/company/export @ backend/src/ai/routers/settings.py:313. UI: No Shopify UI, OAuth router, GraphQL adapter or topic consumer; nearest generic target is /onboarding/connect/api.

**Exact source roots:** `backend/src/ai/routers/settings.py:336::delete_company | backend/src/ai/routers/settings.py:313::export_company_data`.

**Schema/access:** public.billing_subscriptions; public.companies; public.global_competitors; public.rag_documents_metadata; public.tenant_users; public.users

**Missing/unequal edge:** Dedicated SHOP flow absent in current mounted Python/API/worker/frontend inventory. Cited generic/stock/vault/billing source is only an existing dependency, NOT an equivalent provider implementation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
