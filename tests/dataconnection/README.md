# Data Integration Testing

## Run from `backend/`

```powershell
npm run test:data-integration:contract
npm run test:data-integration:worker
npm run test:data-integration:ai-contract
npm run test:data-integration:e2e
npm run test:data-integration:headed
npm run test:data-integration:live-ai
npm run test:data-integration:live-connectors
npm run test:data-integration:single -- tests/e2e/data-integration/data-integration.spec.ts -g "46-product"
npm run test:e2e:report
```

The contract command reuses the upload validator, extraction response, sales-row parser, worker migration and route tests, the shared Gradio client contract, and the new source/ownership contract. The `integration` script is its alias; no live database integration is enabled by default. Live selectors are still blocked without explicit service, database, tenant and connector configuration.

## Verified ownership map

| Workflow | Owner and current behavior |
| --- | --- |
| Manual file upload | Frontend `ConnectDataPage` → authenticated `POST /data-connection` → multer/validator → `dataConnectionService.uploadExtraction` → shared Gradio `analytics/extract_file` call `[safe filename, base64 bytes, country, currency]` → tenant transaction writes inactive `documents` source, `QUEUED` job and `import_staging_rows` → extraction usage increment after persistence → API returns CEOPRO job ID. Accepted file means extraction/staging succeeded; it does not mean sales were promoted. |
| Business row persistence | `worker:data-ingestion` claims due jobs with `FOR UPDATE SKIP LOCKED`, lease and retry metadata. It handles `PENDING` rows in batches of 50 inside DB transactions, resolves/reuses products by tenant + normalized English product name using advisory lock, inserts transactions, and commits staging references. Invalid rows are marked invalid; partial rows remain. Job completion is written after all rows are handled. |
| Persistent source registration | `POST /data-connection/sources` requires `data_integration` and checks `connected_data_sources` capacity. Node validates a supported enum and secret-free metadata, creates an active source row with no credential-vault value, and returns configuration. It does not authenticate or synchronize the provider. |
| AI database/API connectors | Separate AI FastAPI onboarding routes register PostgreSQL or generic REST connectors with vault credentials and collector keys. Scheduled workers poll only active, `ALLOWED`, due sources, read rows/pages, create a job, and call `process_records`. These connector sync modules do not call `promotion.promote_ingested_rows`; the current contract is staging/processing, not proven Node products/transactions promotion. Shopify, MySQL and SQL Server do not have provider/dialect adapters in the inspected code. |
| Frontend source/actions | Website uses real Node source registration. Database setup is preview-only. Analytics and sync/reconnect wrappers call absent Node sync routes or return `{ok:false}`; the page currently displays a success notice without checking that result. Overview API returns `dataStatus: "verified"` for active sources independent of verified connection evidence. Job listing, staging review and template download APIs have preview stubs. |

## Templates, quotas and known behavior

Supported uploads are `.csv`, `.xlsx`, `.xlsm`, `.pdf`, default maximum 10 MiB. CSV/XLSX/XLSM require the published canonical sales template; required columns are `product_name`, `quantity`, `unit_price`, `currency`, `transaction_date`. PDFs are signature-checked before AI and validated against extracted headers/typed fields after AI. The UI advertises generic download assets; its CSV starts with `Field,Value,Date,Notes`, which the backend rejects because it does not match the sales schema. Invoice and inventory import writers are not implemented by this route; keep those assertions separate from sales import.

Starter/Growth/Enterprise catalog limits are respectively 1/5/20 persistent sources and 51,200/512,000/2,097,152 KB of extraction. Upload accounting uses `max(1, ceil(fileBytes / 1024))`. The service checks quota then calls AI, stages the result, and increments usage after persistence; concurrent uploads do not reserve quota atomically. Persistent-source capacity is checked before record creation, so race-safe enforcement still needs DB-backed concurrency evidence. Manual file sources are inactive and excluded from active source count.

The `document_storage_mb` resolver reads `rag_documents_metadata`; Data Connections stores manual upload size in inactive source metadata and does not write those bytes to that table. Repeated manual uploads therefore do not contribute to this storage counter. Resolve the intended storage ownership/accounting contract before treating the limit as proven.

Upload preflight also does not inspect multipart MIME and currently accepts duplicate canonical headings; the staging parser validates ISO dates but has no rule rejecting future transaction dates. The website form sends `url` as a top-level source payload field. The Node source validator does not map that field into metadata, and the source repository stores only validated metadata, so the URL is dropped. The Node source registration response means a row was created, but the overview API also attaches `dataStatus: "verified"` without external credential evidence. The UI's Google Analytics and sync paths call routes absent from the Node router; `sync()` returns `{ok:false}` and its caller ignores that flag while showing a success notice.

Product rows are deduplicated by tenant and normalized English name; transaction insert has no source-record/business-id idempotency key. Re-uploading the same sales file may reuse product rows while inserting duplicate transactions. AI scheduled connector sync likewise lacks demonstrated canonical promotion. These are regression findings, not behavior the tests should hide.

## Test modes and coverage

| Test area | UI | API | DB/schema | AI/worker | Result |
| --- | --- | --- | --- | --- | --- |
| CSV/XLSX/XLSM/PDF validation and template | Existing upload UI | Validator contracts | No fixture writes | AI response separately contracted | Contract tests executable; browser flow blocked |
| Job/staging/promotion | Upload and recent imports | Upload response includes local job ID and staged count | RLS transaction and worker migration asserted | Worker implementation contract asserted | Real lifecycle blocked |
| Duplicate protection | Upload interaction | No business transaction key in insert | No DB idempotency run | Retries need controlled worker | E2E blocked; contract documents gap |
| Source registration/status | Source selector/card | Metadata-only Node endpoint | Source table ownership defined | Registration differs from AI connector route | Contract finding; E2E blocked |
| Connector sync | Preview/missing UI controls | No Node sync route | No live source fixture | AI DB/API sync stages via `process_records`, no promotion call | Connector E2E blocked |
| Quota/capacity | FeatureGate wrappers | Usage/capacity checked in service | Concurrency and storage accounting unverified | No vendor requests | Contracts pass; DB tests blocked |
| RLS/secrets | No real session configured | Tenant context and credential field reviewed | Forced RLS and worker role migration checked | AI vault exists | Runtime security test blocked |
| Invoice/inventory import | Generic template downloads shown | No corresponding import contract | No writer asserted | N/A | Unsupported; explicitly not a passing import scenario |
| Downloaded template compatibility | Generic frontend CSV/XLSX/PDF assets | Canonical sales template validator | Backend template differs from UI CSV header | N/A | Contract finding; E2E blocked |
| Dashboard/Forecasting inputs | Downstream views | Consumer source varies | Independent aggregation not seeded | Import writer outputs transactions | E2E blocked |

The Playwright suite attaches test mode, tenant/job placeholders, tables, expected and actual behavior, dependency and recommended investigation to every blocked case. It performs no mocked successful API interaction and no external calls. Shared HTML/JSON/diagnostic reports remain under `tests/reports/e2e/`; blocked cases do not produce failure screenshots/traces.

## Safe DB/live prerequisites

Before enabling DB-mutating tests, configure a specifically named disposable migrated database; verify its identity; provide two ordinary non-superuser tenant memberships, owned fixture IDs and cleanup; and provision the separate least-privilege `INGESTION_WORKER_DATABASE_URL`. For live AI, add a bounded Gradio test endpoint. For live connectors, use explicitly authorized fixture sources only. Never reuse Render production credentials or store secrets in report annotations.

## Failure categories

The diagnostics reporter recognizes `UPLOAD_VALIDATION_ERROR`, `DOCUMENT_QUOTA_EXCEEDED`, `SOURCE_LIMIT_BYPASS`, connector registration/auth/sync failures, stuck jobs, staging/promotion failures, duplicates, invalid AI responses, false success UI, credential exposure, tenant isolation and test-environment blockers. Categories identify the investigation area; they do not prove a root cause unless a test has evidence.

## Execution record

- `npm run test:data-integration:contract` — 18 new source/schema/behavior assertions passed, plus all 6 existing upload, extraction, worker-migration, route and Gradio test files passed.
- `npm run test:data-integration:e2e` — 26 BLOCKED, 0 pass/fail. No database, AI provider, external connector, or worker was called.
- `npx tsc --noEmit` — passed.
- `python -m pytest --version` — unavailable because pytest is not installed; AI Python connector tests were not run.
- Combined `npm run test:all-features`: Dashboard, Demand Prediction, Product Management, Competitor Management, and Data Integration contracts passed. Existing Market Intelligence contract returned 2 pass / 4 fail for missing `market_intelligence`, `ai_pricing`, and `market_perception` entitlement checks. Shared feature E2E reported 66 BLOCKED, 0 pass/fail.
- Shared diagnostics from the combined run: `tests/reports/e2e/diagnostics.json` — PASS 0, FAIL 0, SKIP 0, BLOCKED 66, ERROR 0; 26 rows are Data Integration scenarios. The HTML report and Playwright JSON report are adjacent under `tests/reports/e2e/`.
