# Source trace refinement — CONNECT

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified CONNECT lineage](../evidence/phase0r/SCHEMA_LINEAGE_CONNECT.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: IMPORT-001

## CONNECT-001 — Generic API and database registration

Proposed behavior remains: Preserve Python onboarding API/DB credentials, field mappings, SSRF guard, vault and periodic sync.

Acceptance specification: `AT-CONNECT-001` — Bad target; invalid credentials; source limit. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/sources @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26. UI: dataConnectionsApi.list/setActive/disconnect; /data-connection/sources.

**Exact source roots:** `backend/src/modules/dataconnection/service/dataconnection.service.ts:675:21::dataConnectionService.createDataSource | backend/src/modules/dataconnection/repo/dataconnection.repo.ts:1221:27::dataManagementRepo.createPersistentSource`.

**Schema/access:** public.data_sources; public.subscriptions

**Missing/unequal edge:** Persistent generic source registration is not proof of Python generic DB/API credential verification and scheduled connector worker parity; dedicated store adapter verified separately.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97. UI: dataConnectionsApi.connectApi/connectDatabase/list/syncNow/disconnect; ConnectSystemForm.jsx.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:133::onboarding_connect_api | backend/src/ai/routers/onboarding.py:97::onboarding_connect_database | backend/src/market_scraper/data_access.py:482::register_self_service_data_source`.

**Schema/access:** public.billing_trials; public.data_sources; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CONNECT-002 — Vault encryption and rotation

Proposed behavior remains: Use Python credential vault as single secret owner; re-encrypt any imported Node envelope using authorized migration, never copy ciphertext formats blindly.

Acceptance specification: `AT-CONNECT-002` — Missing master key; rotated version; other tenant token. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30. UI: dataConnectionsApi.list/setActive/disconnect; /data-connection/sources.

**Exact source roots:** `backend/src/modules/dataconnection/store/vault.ts:10:1::sealCredentials | backend/src/modules/dataconnection/store/vault.ts:16:1::openCredentials`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97 | WORKER_OR_PRIVATE python -m scripts.vault_key @ backend/scripts/vault_key.py:90 | POST /competitors/sources/{source_id}/review @ backend/src/ai/routers/competitors.py:196 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: dataConnectionsApi.connectApi/connectDatabase/list/syncNow/disconnect; ConnectSystemForm.jsx.

**Exact source roots:** `backend/src/market_scraper/credential_vault.py:192::encrypt_credentials | backend/src/market_scraper/credential_vault.py:216::decrypt_credentials | backend/src/market_scraper/credential_vault.py:276::rewrap_envelope`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CONNECT-003 — Recurring sync and source isolation

Proposed behavior remains: Preserve connector_worker discovery and isolated connector type/source failures; add durable claim to prevent concurrent schedulers double work.

Acceptance specification: `AT-CONNECT-003` — DB sync fails API still runs; concurrent pollers. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/sources @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: dataConnectionsApi.list/setActive/disconnect; /data-connection/sources.

**Exact source roots:** `backend/src/modules/dataconnection/repo/dataconnection.repo.ts:1221:27::dataManagementRepo.createPersistentSource | backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:412:21::ingestionWorkerRepo.claimPendingJobs`.

**Schema/access:** public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.subscriptions

**Missing/unequal edge:** Node ingestion/store workers differ from Python generic DB/API periodic polling; no claim of identical generic sync worker.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: dataConnectionsApi.connectApi/connectDatabase/list/syncNow/disconnect; ConnectSystemForm.jsx.

**Exact source roots:** `backend/src/market_scraper/connector_worker.py:106::run_once | backend/src/market_scraper/connector_worker.py:80::run_connector_syncs_for_tenant`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.tenant_storage_objects

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CONNECT-004 — Generic staging to canonical promotion

Proposed behavior remains: Existing DB/API sync calls process_records but not promote_ingested_rows; add explicit approved review/auto-promotion transition, not claim existing parity.

Acceptance specification: `AT-CONNECT-004` — Staged rows not visible to dashboard; capacity after enqueue. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253 | PATCH /data-connection/jobs/:jobId/staging/:rowId @ backend/src/modules/dataconnection/route/dataconnection.route.ts:111. UI: dataConnectionsApi.list/setActive/disconnect; /data-connection/sources.

**Exact source roots:** `backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:139:1::processJobBatchTransaction | backend/src/modules/dataconnection/service/dataconnection.service.ts:304:30::dataConnectionService.updateIngestionStagingRow`.

**Schema/access:** public.import_sale_identities; public.import_staging_rows; public.ingestion_jobs; public.products; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: dataConnectionsApi.connectApi/connectDatabase/list/syncNow/disconnect; ConnectSystemForm.jsx.

**Exact source roots:** `backend/src/market_scraper/connector_sync.py:103::sync_db_connector_source | backend/src/market_scraper/api_connector_sync.py:176::sync_api_connector_source | backend/src/ai/extraction/ingestion_pipeline.py:431::process_records`.

**Schema/access:** public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.tenant_storage_objects

**Missing/unequal edge:** sync_db_connector_source and sync_api_connector_source call process_records and finish job, never promote_ingested_rows; staged completion is not canonical data promotion.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CONNECT-005 — Disconnect sync retry source state

Proposed behavior remains: Reuse onboarding source endpoints; make disconnect fence in-flight lease/credential writes; report verified status.

Acceptance specification: `AT-CONNECT-005` — Disconnect mid-fetch; reconnect changes credential version. NOT RUN as an implementation test.

**NODE entry and UI boundary:** PATCH /data-connection/sources/:sourceId @ backend/src/modules/dataconnection/route/dataconnection.route.ts:31 | DELETE /data-connection/sources/:sourceId/connection @ backend/src/modules/dataconnection/route/dataconnection.route.ts:36 | DELETE /data-connection/store/:sourceId @ backend/src/modules/dataconnection/store/routes.ts:37. UI: dataConnectionsApi.list/setActive/disconnect; /data-connection/sources.

**Exact source roots:** `backend/src/modules/dataconnection/service/dataconnection.service.ts:752:30::dataConnectionService.setPersistentSourceActive | backend/src/modules/dataconnection/service/dataconnection.service.ts:804:31::dataConnectionService.disconnectPersistentSource | backend/src/modules/dataconnection/store/connections.repo.ts:77:13::storeConnections.disconnect`.

**Schema/access:** public.companies; public.data_sources; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** DELETE /onboarding/sources/{source_id} @ backend/src/ai/routers/onboarding.py:256 | POST /onboarding/sources/{source_id}/sync @ backend/src/ai/routers/onboarding.py:246. UI: dataConnectionsApi.connectApi/connectDatabase/list/syncNow/disconnect; ConnectSystemForm.jsx.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:256::disconnect_source | backend/src/ai/routers/onboarding.py:246::sync_source_now | backend/src/ai/routers/onboarding.py:225::_update_source`.

**Schema/access:** public.data_sources; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CONNECT-006 — Secondary databases and provider registration

Proposed behavior remains: Node choices mysql/sqlserver/ga4/website are not proof complete adapters. Preserve proven Python DB/API and record any dependent unsupported source as blocked.

Acceptance specification: `AT-CONNECT-006` — Selected UI source lacks running backend; provider credentials missing. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/sources @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26. UI: dataConnectionsApi.list/setActive/disconnect; /data-connection/sources.

**Exact source roots:** `backend/src/modules/dataconnection/service/dataconnection.service.ts:675:21::dataConnectionService.createDataSource | backend/src/modules/dataconnection/types/dataconnection.validation.ts:197:1::validateCreateDataSource`.

**Schema/access:** public.data_sources; public.subscriptions

**Missing/unequal edge:** Registration source choices do not prove working mysql/sqlserver/ga4/website adapters; external runner/provider joins need individual evidence.

**PYTHON entry and UI boundary:** POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97 | POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: dataConnectionsApi.connectApi/connectDatabase/list/syncNow/disconnect; ConnectSystemForm.jsx.

**Exact source roots:** `backend/src/ai/routers/onboarding.py:97::onboarding_connect_database | backend/src/ai/routers/onboarding.py:133::onboarding_connect_api | backend/src/market_scraper/api_connector_sync.py:85::build_api_fetch_page`.

**Schema/access:** public.billing_trials; public.data_sources; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Generic PostgreSQL/API adapters do not prove every Node advertised provider type is supported; do not invent dedicated integrations.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
