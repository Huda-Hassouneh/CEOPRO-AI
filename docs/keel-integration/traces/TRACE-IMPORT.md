# Source trace refinement — IMPORT

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified IMPORT lineage](../evidence/phase0r/SCHEMA_LINEAGE_IMPORT.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: ACCOUNTING-001; IMPORT-001

## IMPORT-001 — Canonical sales headers signatures size

Proposed behavior remains: Preserve Python CSV/XLSX/XLSM/PDF validation and template; add Node strict typed/schema checks where stronger.

Acceptance specification: `AT-IMPORT-001` — Bad PDF/ZIP; oversized upload; unsupported aliases. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/dataconnection.service.ts:370:21::dataConnectionService.uploadExtraction | backend/src/modules/dataconnection/types/dataconnection.validation.ts:41:1::validateExtractionUpload | backend/src/modules/dataconnection/validators/extraction-result.validation.ts:21:1::validateExtractionResultForDataConnection`.

**Schema/access:** public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.plan_features; public.products; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /reviews/import @ backend/src/ai/routers/reviews.py:48. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/routers/extraction.py:272::extraction_upload | backend/src/ai/routers/extraction.py:131::_read_upload_within_limit | backend/src/ai/routers/extraction.py:140::_validate_upload_content | backend/src/ai/extraction/file_dispatch.py:46::read_source_file`.

**Schema/access:** public.billing_trials; public.companies; public.data_sources; public.demand_forecasts; public.evidence_records; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.model_versions; public.products; public.rag_document_chunks; public.rag_documents_metadata; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_storage_objects; public.tenant_usage_counters; public.transactions; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-002 — RAG document separation

Proposed behavior remains: Preserve dedicated RAG upload and Python extraction PDF optional registration; business promotion requires validated canonical rows.

Acceptance specification: `AT-IMPORT-002` — Text PDF has no sale; optional registration fails after sale commits. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/rag/documents @ backend/src/modules/rag/route/rag.route.ts:42 | POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/rag/repo/rag.repo.ts:203:1::saveUploadedRagDocument | backend/src/modules/dataconnection/service/dataconnection.service.ts:370:21::dataConnectionService.uploadExtraction`.

**Schema/access:** public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.plan_features; public.products; public.rag_document_search; public.rag_document_search_passages; public.rag_documents_metadata; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/routers/extraction.py:146::_register_pdf_as_rag_document | backend/src/ai/routers/extraction.py:146::_register_pdf_as_rag_document`.

**Schema/access:** public.rag_document_chunks; public.rag_documents_metadata

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-003 — Product ID SKU name disagreement

Proposed behavior remains: Extend Python matching with tenant SKU uniqueness and explicit ID/name/SKU conflict review; retain barcode fill-only matching.

Acceptance specification: `AT-IMPORT-003` — Another tenant ID; same name multiple SKU; barcode conflict. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/imports/:kind/preview @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | POST /data-connection/imports/:kind @ backend/src/modules/dataconnection/route/dataconnection.route.ts:82 | POST /data-connection/imports/:kind/previews/:draftId/confirm @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | POST /data-connection/imports/:kind/previews/:draftId/review @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | GET /data-connection/imports/products @ backend/src/modules/dataconnection/route/dataconnection.route.ts:61 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/business-product-matching.ts:72:1::matchImportProducts | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:151:1::searchStructuredImportProducts | backend/src/modules/dataconnection/repo/import-product.ts:6:1::ensureImportedProduct`.

**Schema/access:** public.products

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/extraction/promotion.py:368::_alias_names_by_barcode | backend/src/ai/extraction/promotion.py:380::_apply_barcodes | backend/src/ai/extraction/promotion.py:281::_load_existing_products`.

**Schema/access:** public.products

**Missing/unequal edge:** Promotion matches normalized name/barcode; no equivalent complete typed ID/SKU/name disagreement review flow.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-004 — Preview review confirm immutable draft

Proposed behavior remains: Add typed persistent draft/revision preview APIs for invoice/inventory kinds using Python extraction conventions.

Acceptance specification: `AT-IMPORT-004` — Edited rows between preview/confirm; expired draft; duplicate confirm. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/imports/:kind/preview @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | POST /data-connection/imports/:kind/previews/:draftId/review @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | POST /data-connection/imports/:kind/previews/:draftId/confirm @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/dataconnection.service.ts:178:34::dataConnectionService.previewStructuredBusinessFile | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:164:1::createBusinessImportPreview | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:134:1::reviewBusinessImport | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:223:1::confirmBusinessImport`.

**Schema/access:** public.business_import_drafts; public.companies; public.data_sources; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.products; public.subscription_usage; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/routers/extraction.py:272::extraction_upload | backend/src/ai/extraction/promotion.py:671::promote_ingested_rows`.

**Schema/access:** public.billing_trials; public.companies; public.data_sources; public.demand_forecasts; public.evidence_records; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.model_versions; public.products; public.rag_document_chunks; public.rag_documents_metadata; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_storage_objects; public.tenant_usage_counters; public.transactions; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** extraction_upload immediately stages/promotes sales; no typed invoice/inventory immutable preview-review-confirm API.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-005 — Sales products transactions invoice mirror

Proposed behavior remains: Preserve actual Python promotion batch savepoints and transaction plus invoice/item mirrors; not the older sales-only description.

Acceptance specification: `AT-IMPORT-005` — Duplicate file; conflicting content-derived identity; 50k rows. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253 | POST /data-connection/imports/:kind @ backend/src/modules/dataconnection/route/dataconnection.route.ts:82 | POST /data-connection/imports/:kind/previews/:draftId/confirm @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/sales-csv-import.ts:46:1::extractCompleteSalesFile | backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:139:1::processJobBatchTransaction | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:262:1::persistStructuredBusinessImport`.

**Schema/access:** public.business_import_drafts; public.companies; public.data_sources; public.import_sale_identities; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.products; public.subscription_usage; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/extraction/promotion.py:561::_insert_transactions_batch | backend/src/ai/extraction/promotion.py:462::_insert_invoices_mirror_batch | backend/src/ai/extraction/promotion.py:671::promote_ingested_rows`.

**Schema/access:** public.billing_trials; public.import_staging_rows; public.invoice_items; public.invoices; public.products; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.transactions; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-006 — Inventory and warehouse imports

Proposed behavior remains: Add approved Node inventory semantics to Python canonical inventory/locations, avoiding sales-driven stock subtraction twice.

Acceptance specification: `AT-IMPORT-006` — Unknown warehouse; duplicate snapshot; negative stock. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/imports/:kind/preview @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | POST /data-connection/imports/:kind @ backend/src/modules/dataconnection/route/dataconnection.route.ts:82 | POST /data-connection/imports/:kind/previews/:draftId/review @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | POST /data-connection/imports/:kind/previews/:draftId/confirm @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/structured-business-import.ts:161:1::parseStructuredBusinessFile | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:262:1::persistStructuredBusinessImport`.

**Schema/access:** public.business_import_drafts; public.companies; public.data_sources; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.products; public.subscription_usage; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** PATCH /products/{product_id}/inventory @ backend/src/ai/routers/products.py:616. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/routers/products.py:438::upsert_inventory | backend/src/ai/routers/products.py:616::update_product_inventory_endpoint`.

**Schema/access:** public.inventory; public.products

**Missing/unequal edge:** Product inventory upsert is supported; no equivalent structured inventory-file preview/confirm flow or store-owned warehouse linkage.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-007 — Invoice item groups tax currency

Proposed behavior remains: Preserve Python quick_sale and sales import one-row mirror; add separate structured invoices with approved grouping and paid-state rules.

Acceptance specification: `AT-IMPORT-007` — Mixed currencies; line totals differ; existing invoice number. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/imports/:kind/preview @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | POST /data-connection/imports/:kind @ backend/src/modules/dataconnection/route/dataconnection.route.ts:82 | POST /data-connection/imports/:kind/previews/:draftId/review @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | POST /data-connection/imports/:kind/previews/:draftId/confirm @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/structured-business-import.ts:161:1::parseStructuredBusinessFile | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:262:1::persistStructuredBusinessImport`.

**Schema/access:** public.business_import_drafts; public.companies; public.data_sources; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.products; public.subscription_usage; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /sales/quick-sale @ backend/src/ai/routers/sales.py:27 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/sales/quick_sale.py:66::record_quick_sale | backend/src/ai/extraction/promotion.py:462::_insert_invoices_mirror_batch`.

**Schema/access:** public.inventory; public.invoice_items; public.invoices; public.products

**Missing/unequal edge:** Quick sale and per-sale invoice mirrors exist; no equivalent structured grouped invoice-file review path.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-008 — Review import provenance sentiment

Proposed behavior remains: Reuse reviews import and sentiment pipeline; carry source safety, subject ownership and dedup for MPI.

Acceptance specification: `AT-IMPORT-008` — Future/unsafe reviews; invalid competitor; duplicate import. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/mpi/summary @ backend/src/modules/mpi/route/mpi.route.ts:14 | GET /market-intelligence/ @ backend/src/modules/market-intelligence/route/market-int.route.ts:16 | POST /features/sentiment/analyze-pending @ backend/src/modules/sentiment/route/sentiment.route.ts:23. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/mpi/repo/mpi.repo.ts:13:1::getReviewsForMpi | backend/src/modules/sentiment/service/sentiment.service.ts:40:1::analyzePendingSentiment`.

**Schema/access:** public.companies; public.data_sources; public.plan_features; public.products; public.reviews; public.sentiment_results; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /reviews/import @ backend/src/ai/routers/reviews.py:48 | POST /sentiment/analyze-pending @ backend/src/ai/routers/sentiment.py:13. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/routers/reviews.py:48::import_reviews_endpoint | backend/src/ai/routers/reviews.py:29::_analyze_imported_reviews | backend/src/ai/sentiment/pipeline.py:34::classify_and_store_reviews`.

**Schema/access:** public.billing_trials; public.companies; public.data_sources; public.products; public.reviews; public.sentiment_results; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_usage_counters; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-009 — Staging validation quarantine promotion

Proposed behavior remains: Reuse import_staging_rows and ingestion_jobs; persist row-level rejection, review and committed links, not misleading complete status.

Acceptance specification: `AT-IMPORT-009` — Some rows invalid; promotion capacity exceeded; downstream failure. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /data-connection/jobs/:jobId/staging @ backend/src/modules/dataconnection/route/dataconnection.route.ts:107 | PATCH /data-connection/jobs/:jobId/staging/:rowId @ backend/src/modules/dataconnection/route/dataconnection.route.ts:111 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/dataconnection.service.ts:282:28::dataConnectionService.getIngestionStagingRows | backend/src/modules/dataconnection/service/dataconnection.service.ts:304:30::dataConnectionService.updateIngestionStagingRow | backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:139:1::processJobBatchTransaction`.

**Schema/access:** public.import_sale_identities; public.import_staging_rows; public.ingestion_jobs; public.products; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120 | POST /extraction/process-pending @ backend/src/ai/routers/extraction.py:101. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/extraction/ingestion_pipeline.py:431::process_records | backend/src/ai/extraction/promotion.py:671::promote_ingested_rows | backend/src/ai/routers/extraction.py:101::extraction_process_pending`.

**Schema/access:** public.billing_trials; public.companies; public.import_staging_rows; public.ingestion_jobs; public.invoice_items; public.invoices; public.news_record; public.products; public.social_mention; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_storage_objects; public.transactions; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-010 — Duplicate identity across sources

Proposed behavior remains: Add source/provider/external record/revision links in Python; retain content-derived manual-file identities without treating identical real sales as one.

Acceptance specification: `AT-IMPORT-010` — Manual store export overlaps connector; genuine repeated same-value sale. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253 | POST /data-connection/imports/:kind/previews/:draftId/confirm @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/sale-identity.ts:4:1::saleIdentity | backend/src/modules/dataconnection/service/dataconnection.service.ts:370:21::dataConnectionService.uploadExtraction | backend/src/modules/dataconnection/repo/structured-business-import.repo.ts:223:1::confirmBusinessImport`.

**Schema/access:** public.business_import_drafts; public.companies; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.plan_features; public.products; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/extraction/promotion.py:163::_import_invoice_number | backend/src/ai/extraction/promotion.py:659::_existing_invoice_numbers`.

**Schema/access:** public.invoices

**Missing/unequal edge:** Content/occurrence manual-sale identity exists; no complete shared manual/store stable external-lineage reconciliation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-011 — Batch checkpoint retry and refund

Proposed behavior remains: Move long work to durable bounded jobs; retain synchronous contract compatibility, leases, heartbeat and idempotent resume; account partial work.

Acceptance specification: `AT-IMPORT-011` — Crash after commit before checkpoint; 1000/50000-row files. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:412:21::ingestionWorkerRepo.claimPendingJobs | backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:458:22::ingestionWorkerRepo.processClaimedJob | backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:521:24::ingestionWorkerRepo.scheduleRetryOrFail`.

**Schema/access:** public.data_sources; public.import_sale_identities; public.import_staging_rows; public.ingestion_jobs; public.products; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/extraction/ingestion_pipeline.py:431::process_records | backend/src/ai/extraction/promotion.py:183::_run_in_savepoint | backend/src/ai/routers/extraction.py:272::extraction_upload`.

**Schema/access:** public.billing_trials; public.companies; public.data_sources; public.demand_forecasts; public.evidence_records; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.model_versions; public.products; public.rag_document_chunks; public.rag_documents_metadata; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_storage_objects; public.tenant_usage_counters; public.transactions; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## IMPORT-012 — Import status errors cleanup dashboard

Proposed behavior remains: Preserve Python recent-import mapper with explicit failed/partial/review states; add detail/retry/preview feedback and storage cleanup.

Acceptance specification: `AT-IMPORT-012` — Unknown status; cancelled job; import details cross tenant. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /data-connection/jobs/:jobId @ backend/src/modules/dataconnection/route/dataconnection.route.ts:116 | POST /data-connection/jobs/:jobId/retry @ backend/src/modules/dataconnection/route/dataconnection.route.ts:120 | GET /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:89. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; data-connections ConnectDataPage and APIs.

**Exact source roots:** `backend/src/modules/dataconnection/service/dataconnection.service.ts:272:20::dataConnectionService.getIngestionJob | backend/src/modules/dataconnection/service/dataconnection.service.ts:349:22::dataConnectionService.retryIngestionJob | backend/src/modules/dataconnection/service/dataconnection.service.ts:261:31::dataConnectionService.getDataConnectionsOverview`.

**Schema/access:** public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /extraction/imports @ backend/src/ai/routers/extraction.py:90. UI: frontend/src/features/data-ingestion/api/ingestionApi.js; dataConnectionsApi.list; CustomerReviewsSection.jsx.

**Exact source roots:** `backend/src/ai/extraction/job_management.py:53::list_recent_imports | backend/src/ai/routers/extraction.py:90::extraction_recent_imports | frontend/src/features/data-connections/api/dataConnectionsApi.js:19:1::mapRecentImports`.

**Schema/access:** public.data_sources; public.ingestion_jobs

**Missing/unequal edge:** Recent imports/listing exists; row review/retry/details joins required by Node workflow are missing/partial.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
