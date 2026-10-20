> Phase 0R: read [SOURCE_TRACE_CORRECTIONS.md](../SOURCE_TRACE_CORRECTIONS.md) and [PHASE0R_README.md](../PHASE0R_README.md) before relying on original source-inference wording. Native/runtime gates remain pending.

# Feature architecture — imports

Status: PROPOSED for architecture review; capability families IMPORT CONNECT. Single Python authority is already approved by user; no conflicting policy is selected.


Python manual flow: ConnectDataPage/upload client → `/extraction/upload` multipart file → tenant context → size/extension/signature/template validation → geo/currency resolution → extraction KB reserve + ingestion job → ingestion_pipeline.process_records (batched staging commits) → promotion.promote_ingested_rows → response summary with promotion counters → refresh downstream forecasts/discovery when appropriate. Optional PDF-to-RAG registration is separate and may fail after business work commits; do not describe the whole upload as rolled back in that case.

Python promotion.py in THIS archive writes products, transactions AND invoices/invoice_items mirror in the same batch/savepoint, with row fallback. `_import_invoice_number` derives identity from content and occurrence; existing invoice numbers suppress duplicate rows; barcode matching/fill-only metadata protect curated values. Product capacity is consulted. Final database behavior needs native concurrency tests, particularly pre-insert duplicate checks and catalog last-slot writes. Never regress to copying sales without invoice mirrors (dashboard/assistant consume invoices/items, forecasting reads transactions).

Node adds structured invoice/inventory template/preview/review/confirm flows with persistent drafts; ID/SKU/name disagreement checks, active-product matching and tenant uniqueness; CSV identity/recovery and a dedicated ingestion worker with heartbeat/batches. Source functions: business-product-matching.ts, structured-business-import.ts, structured-business-import.repo.ts, import-product.ts, sale-identity.ts, staging-batches.ts, ingestion-worker.repo.ts. Port behavior only where stronger; retain Python batch performance and barcode semantics.

Target one canonical ingestion service with typed kinds sales/invoices/inventory/reviews, immutable preview revision and row decisions; source external identity preserved; import_staging_rows owns validation and committed links, ingestion_jobs owns progress. Add missing structured targets using shared product identity and canonical schema; no fabricated products or arbitrary UUID matching. Do not force inventory/manual invoices through a sales-only template.

Cross-source data ownership: manual sales content identity differs from stable store external order/item identity. Introduce explicit lineage/revision links so the same store export imported manually can be recognized or reviewed without suppressing legitimate equal-valued sales. Define invoice grouping/payment state and inventory source conflict in IMPORT-001; existing manual row-mirror behavior remains stable until approved adapter behavior exists. Preserve quick_sale.py, review imports and storage_ledger; RAG knowledge documents do not automatically become sales.

Generic connections: `/onboarding/connect/api` and `/connect/database` → onboarding router/market_scraper.data_access verifies target/credentials and encrypted vault → data_sources metadata/collector keys → connector_worker.run_once discovers tenants through list_tenants_with_active_connectors → DB/API sync → process_records staging and job completion. Both sync modules currently omit promote_ingested_rows. Add an explicit reviewed or automatic canonical promotion transition; a completed fetch is not proof dashboard-ready sales exist.

API generic field mapping, PostgreSQL read-only query guard, API page path, auth header/scheme, sync frequency, credential rotation and existing network_security must be retained. `onboarding` connect/source mutations require owner/admin checks; worker source discovery is narrowly scoped, not global table read from a customer token. Extend verification/status semantics and source-capacity race checks at reactivation/execution.

Job states need QUEUED→PROCESSING→REVIEW_REQUIRED/PARTIAL/COMPLETED/FAILED/CANCELLED as approved, with lease, heartbeat, retry cap and row error counters; extend existing schema constraints additively. Re-authorize at enqueue, execution and canonical commit, with outbox durability and crash fencing. Expired transactions must not hold thousands of remote calls/rows in one long transaction. Partial commits/refunds need ACCOUNTING-001. Large-file acceptance measures memory/time, commits, restart exact-once canonical outcomes and dashboard totals.


## Verification and migration gate

Use domain rows in CAPABILITY_TRACEABILITY.csv, exact symbols in evidence/FUNCTION_CALL_INDEX.csv, and ordered SQL_OBJECT_LINEAGE.csv. Phase-specific schema/file scopes and disable strategy are in IMPLEMENTATION_PHASES.md. All applicable AT IDs require native tenant/RLS, service, HTTP, worker and frontend proof; source-level parity is not a passing test. No destructive backfill or existing customer change is authorized by this note.
