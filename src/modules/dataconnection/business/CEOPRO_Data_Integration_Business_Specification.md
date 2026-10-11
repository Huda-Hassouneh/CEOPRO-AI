# CEOPRO — Data Integration Business Specification

## 1. Executive business answer

Data Integration should let a tenant connect operational systems and safely bring sales, product, inventory, invoice and other relevant information into CEOPRO. The owner must be able to tell **which data source is configured, which is authenticated, which actually synchronized, how much was imported, when it was last refreshed, and whether anything failed**. A saved connector row is **not** a working connection.

**Example:** A store uploads its sales spreadsheet, configures its Shopify store, and connects its internal PostgreSQL reporting database. Business-file ingestion may populate products/transactions today, but registering Shopify/PostgreSQL from the current Node endpoint does not establish credentials or guarantee synchronization. Until actual integrations are wired, the interface must report _configured / not verified_, not _connected_.

## 2. Product scope and user journeys

1. **Manual business upload:** Download the canonical sales template → upload CSV/XLSX/XLSM/PDF → validate entitlement and file → call AI extraction → stage records → worker imports products/transactions → inspect final status and errors.
2. **Persistent source registration:** Choose supported source type → configure non-secret metadata and frequency → persist tenant-owned source → display _configured, not yet verified_. A separate secure credential/authorization process is needed before a source is considered connected.
3. **First and recurring synchronization (target):** Test credentials → map external records → run a sync job → promote validated business records → update `last_synced_at` only on genuine completion → resume based on an incremental watermark.
4. **Correction and failure recovery (target):** Inspect rejected rows and error causes, retry safely, revoke connection, and keep previously imported business history intact.

**No conflation:** Knowledge Base/RAG document uploads are a different flow and entitlement. A file imported as sales should not be counted as a persistent connected source.

## 3. Data source types and implementation status

| Type                     | Node source registration  | Active extraction/sync verified in Node | AI-team infrastructure                                                                                               | Current verdict                                          |
| ------------------------ | ------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Manual CSV/XLSX/XLSM/PDF | Separate file-upload flow | Yes: upload/staging/worker code exists  | Hosted Gradio `extract_file`; AI ZIP also has a distinct FastAPI pipeline                                            | Implemented flow; runtime requires verification          |
| `shopify`                | Yes                       | No                                      | Generic API/POS connector framework, but not a verified Shopify OAuth/customer sync                                  | Metadata only in current Node path                       |
| `postgresql`             | Yes                       | No                                      | PostgreSQL-compatible polling connector with read-only client connection                                             | Separate AI worker, not provisioned by Node registration |
| `mysql`                  | Yes                       | No                                      | Generic DB-connector scope explicitly does not implement multi-dialect drivers                                       | Metadata only                                            |
| `sqlserver`              | Yes                       | No                                      | Generic DB-connector scope explicitly does not implement multi-dialect drivers                                       | Metadata only                                            |
| `ga4`                    | Yes                       | No                                      | Generic API framework is not evidence of Google OAuth/GA4 implementation                                             | Metadata only                                            |
| `website`                | Yes                       | No                                      | Website scraping/source-policy infrastructure elsewhere in AI team, not equivalent to tenant business-website import | Metadata only                                            |

The Data Connections UI groups types as **Analytics**, **Website**, **Business System**, and **Documents**. Those are UI categories, not the six persistent `sourceType` values. Do not imply support for an actual Shopify/GA4/database connection merely because the category is visible.

## 4. Actual CEOPRO implementation and route ownership

| Function                       | Code path / endpoint                                                       | Actual state                                                                                                                                                                      |
| ------------------------------ | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Overview                       | `GET /data-connection` → `dataconnection.route.ts` → service → repository  | Tenant-scoped `connectedSources` and last five `recentImports`; authenticated + tenant required                                                                                   |
| Persistent source registration | `POST /data-connection/sources`                                            | Requires `data_integration`, checks `connected_data_sources`, inserts `data_sources`; **does not test connection or start sync**                                                  |
| Manual file upload             | `POST /data-connection`                                                    | Requires `document_extraction`; Multer → preflight validation → hosted Gradio → source/job/staging persisted                                                                      |
| Database promotion             | `src/workers/data-ingestion.worker.ts` and `repo/ingestion-worker.repo.ts` | Separate worker, uses restricted `INGESTION_WORKER_DATABASE_URL` role, processes batches (50 rows), creates/reuses products and inserts transactions                              |
| Sync/reconnect                 | Frontend `dataConnectionsApi.sync`, `.reconnect`; UI button actions        | Stub/preview, no corresponding Node sync/reconnect route in inspected module                                                                                                      |
| GA4 connection                 | Frontend `connectGoogleAnalytics`                                          | Calls a constructed `/data-connection/${sourceId}/sync` path; caller supplies an object instead of a source ID; errors are returned as `{ok:false}` rather than thrown; not OAuth |
| Website configuration          | Frontend `configureWebsite`                                                | Calls `/sources` but passes top-level `url` rather than `metadata`; current validator/repository only persist `metadata`, so the URL is not reliably saved                        |
| Database connection setup      | Frontend `prepareDatabase`                                                 | Returns a preview result, no connection established                                                                                                                               |
| Job and staging review         | `ingestionApi.listJobs`, `.reviewStagingRows`                              | Return preview/empty arrays, not a real job-detail API                                                                                                                            |

**Mounted-route caveat:** Endpoint strings reflect the Data Connections module's documented request paths; route mounts in different deployments should be confirmed against app registration.

## 5. File ingestion: exact backend stages

1. Validate one nonempty file with matching extension/signature. Supported `.csv`, `.xlsx`, `.xlsm`, `.pdf`; default `MAX_UPLOAD_BYTES` = **10 MiB**.
2. For CSV/Excel, require the canonical template (both shipped CSV and XLSX headers must agree), with at least the following required columns: `product_name`, `quantity`, `unit_price`, `currency`, `transaction_date`. Optional: `discount_pct`, `invoice_id`, `order_id`, `email`, `phone`, `competitor_name`, `amount_raw`. PDF headers are checked after extraction.
3. Calculate KB quota charge: `max(1, ceil(file_bytes / 1024))`. Check `document_extraction` remaining quota and `document_storage_mb` capacity.
4. Call shared `gradioClient` with `service='analytics'`, `apiName='extract_file'`, positional inputs `[sanitized_file_name, base64_file, country_code, currency]`, defaults `JO`/`JOD`. Validate response contract and typed row values.
5. Create CEOPRO-owned UUID job. Persist inactive `documents` source (for upload history), `ingestion_jobs` status `QUEUED`, and staged `import_staging_rows` records; then increment extraction usage.
6. The separate worker claims queued work, validates again, matches/creates `products`, inserts `transactions` with `sale_source='IMPORT'`, commits/invalidates staged rows, and moves job toward `COMPLETED`/`FAILED`. Recovery uses leases, batches and bounded retries.
7. Only a **terminal successful import with expected committed rows** proves the business data is available. HTTP upload success and the AI extraction summary are not proof of database promotion.

### Current data coverage

The existing canonical template feeds **sales transactions and products**. Its optional `invoice_id` does not prove an invoice was paid. It does **not** constitute a full **invoices/payments** or **inventory stock** import. The previously prepared invoice/inventory template files are separate proposed templates and need their own deterministic backend importer or supported processing path before CEOPRO can use them. They do not require another AI endpoint by default.

## 6. Persistent connectors and AI team's infrastructure

The AI repository includes:

- `src/market_scraper/connector_sync.py`: PostgreSQL-compatible database read-only polling, due calculation using `data_sources.last_synced_at` and `sync_frequency_minutes`; requires approved `collector_key='db_connector'`, source-specific host/query/mapping and vaulted credentials.
- `src/market_scraper/api_connector_sync.py`: generic paginated REST API polling, mapping and tenant source status; requires approved `collector_key='api_connector'` and configured API endpoint/mapping.
- `src/market_scraper/connector_worker.py`: polling loop (default 300 seconds), tenant discovery via a SQL function and per-tenant restricted/RLS connections.
- `src/ai/extraction/ingestion_pipeline.py`: `process_records` stages and validates rows. It does **not** itself call `promote_ingested_rows` from `src/ai/extraction/promotion.py`; connector jobs could be marked completed without establishing business-table promotion. **Test this before relying on connector data in downstream metrics.**

**Integration mismatch:** Node `POST /sources` writes `source_type` and metadata, but does not populate the AI worker's required `collector_key`, authorization status, vaulted credentials, or provider-specific field mapping. Hence creating a source in Node does not create an AI-runnable connector. The AI code is implemented but its live deployment/execution and end-to-end Node interoperability are **unverified**.

## 7. Database ownership and downstream impact

| Table                                                     | Source writer/reader                                                                      | Business meaning                                                            |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `data_sources`                                            | Node upload registration & persistent source registration; AI source management/connector | Which sources are configured, active, policy approved, last synced          |
| `ingestion_jobs`                                          | Node manual upload + ingestion worker; AI connector jobs                                  | Per-ingestion status, progress and failures                                 |
| `import_staging_rows`                                     | Node hosted AI result staging / AI `process_records`; worker promotion                    | Raw/validated business rows and per-row disposition                         |
| `products`                                                | Node import worker / AI FastAPI promotion when invoked                                    | Tenant product catalog                                                      |
| `transactions`                                            | Node import worker / AI promotion when invoked                                            | Historical sold units/transaction values                                    |
| `invoices`, `invoice_items`                               | Separate Quick Sale and future invoice ingestion                                          | Paid-invoice Dashboard metrics **not automatically fed by sales imports**   |
| `inventory`                                               | Dedicated stock ingestion/sync required                                                   | Stock counts and restock data **not fed by current canonical sales import** |
| `companies`, `subscriptions`, `features`, `plan_features` | Node subscription/tenant infrastructure                                                   | Country, currency, entitlements and capacity                                |

**Ownership recommendation:** Node owns tenant auth, source lifecycle, billing limits, safe credential onboarding, import/sync state contract and business-record promotion policy. The AI team owns supported connector adapters, parsing/normalization and source-specific collection. Explicitly assign a single writer or idempotent handoff at each boundary.

## 8. Calculation and status contracts

| Measure                       | Definition / verification                                                                                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Active connected-source usage | Count active **persistent** sources of permitted types for the tenant. Inactive manual-file sources must not consume this capacity                                       |
| Upload extraction usage       | `max(1, ceil(file_size_bytes/1024))` KB, charged according to the actual persisted-success policy                                                                        |
| Document storage consumption  | Sum eligible retained file sizes under the actual storage accounting rules; verify separately since data-source metadata does not guarantee that file bytes are retained |
| Valid row rate                | `committed_rows / total_staged_rows × 100`, for total greater than zero                                                                                                  |
| Invalid row rate              | `invalid_rows / total_staged_rows × 100`, distinguish extraction failures and worker validation errors                                                                   |
| Sync due                      | `last_synced_at IS NULL` or elapsed minutes `>= sync_frequency_minutes`; job scheduler poll interval is not each source's sync period                                    |
| Freshness                     | `now - actual successful last_synced_at`; should not be inferred from `created_at` or merely configured status                                                           |
| Actual imported records       | Use committed staging references and persisted business records; avoid assuming total `rows_processed` is a unique business-record count or summing repeated reimports   |

**UI status rule:** Distinguish _configured_, _credentials verified_, _sync running_, _completed_, _failed_, _blocked by policy_, _stale_. The repository currently exposes `dataStatus: 'verified'` as a hard-coded compatibility field, although no real connection health check occurs. This is potentially misleading and must be corrected.

## 9. Plan access and limits — production catalog source

The inspected `src/config/production-plans.ts` enables `data_integration` for **all three standard plans**:

| Plan       | Monthly base price | `data_integration` | `connected_data_sources` | `document_extraction` | `document_storage_mb` |
| ---------- | -----------------: | ------------------ | -----------------------: | --------------------: | --------------------: |
| Starter    |                $55 | Included           |                    **1** |         **51,200 KB** |          **1,024 MB** |
| Growth     |               $140 | Included           |                    **5** |        **512,000 KB** |         **10,240 MB** |
| Enterprise |               $350 | Included           |                   **20** |      **2,097,152 KB** |         **51,200 MB** |

- `data_integration`: boolean permission to register persistent sources.
- `connected_data_sources`: numeric cap on active persistent registrations.
- `document_extraction`: separate KB usage quota that gates file uploads.
- `document_storage_mb`: separate storage-capacity cap checked during upload.
- Subscription period/reset policy is defined elsewhere in the entitlement system; never infer the reset frequency from these static limits alone.
- Custom plans may override entitlements. Verify active effective entitlements, not just catalog names.

**Capacity correctness risk:** `assertFeatureCapacity(... additionalAmount:1)` followed by a separate create operation may allow two concurrent registration requests to exceed a limit if the check and insert are not serialized. Add race-condition E2E tests and enforce capacity atomically.

## 10. Known gaps and implementation priorities

**High — customer-visible correctness/security**

1. Connect actual frontend provider setup/auth flows to working APIs; stop treating preview results or metadata inserts as authenticated connections.
2. Implement secure provider-specific credentials/OAuth, source validation and credential rotation/revocation. Never store passwords, tokens, SQL connection strings or API secrets inside public `collector_config` metadata.
3. Bridge Node persistent-source registration with AI `collector_key`, approved source policies, vault and field-mapping configuration; verify the AI connector worker is deployed.
4. Establish actual sync-to-business-record **promotion** for AI connector results, with retry/idempotency and independent downstream record verification.
5. Expose real job detail, staged-row review, retry, pause/disconnect and first-sync status APIs with tenant-scoped authorization.
6. Fix false frontend success messages: `connectGoogleAnalytics`, `prepareDatabase`, `sync`, and `reconnect` currently return `{ok:false}`/preview results that the UI may still display as success; a top-level website `url` is not saved in `metadata`.
7. Remove the hardcoded `dataStatus: 'verified'` for unsynced sources; distinguish `is_active` configuration from connection health.
8. Enforce source caps race-safely and verify per-tenant RLS. Implement URL/host allowlists, SSRF prevention, read-only DB credentials, safe queries, bounded pagination and source-policy authorization before running external connectors.
9. Add reliable deduplication/change-data-capture policy so repeated file uploads or connector syncs do not multiply business transactions. Clarify handling for data correction and deletion.

**Medium — completeness and product value**

10. Deliver genuine invoice/payment and inventory-data imports before promising all Dashboard/Inventory metrics from Data Integration.
11. Resolve frontend template asset alignment with the actual backend canonical templates. A displayed/downloadable template must pass real backend validation.
12. Improve connection statuses, bilingual errors, timestamps, progress tracking, staging counts, and source-specific diagnostics. Source metadata may expose categories such as inventory even when current ingestion doesn't supply it; avoid implying unsupported coverage.
13. Monitor source age, sync failures, duplicate rows, data quality and provider rate limits, and alert customers when data becomes stale.

## 11. E2E and integration acceptance matrix

Use the established Playwright/TypeScript + test Postgres infrastructure. Separate deterministic tests (real frontend, Node, database) from opt-in live Gradio/AI/provider tests. Do not mock Node API results for genuine E2E tests.

- [ ] Starter/Growth/Enterprise can register respectively 1/5/20 active sources; custom-plan limit, concurrent requests and downgrade scenarios are correct.
- [ ] Source registration creates a tenant-owned **configured** record, not fake connected/verified status; unknown types and secret-like metadata keys are rejected.
- [ ] Website URL is persisted safely where intended; invalid URLs/SSRF destinations rejected; credentials absent from API and logs.
- [ ] GA4/Shopify/DB connectors either establish authenticated real connections or explicitly report `NOT_IMPLEMENTED` / unavailable without success toast.
- [ ] Manual upload accepts valid canonical CSV/XLSX/PDF, enforces size/signature/header/quota, and rejects incorrect files without charging usage.
- [ ] Real AI `extract_file` contract verified separately, including unexpected JSON/null, provider failures, partial/failed row behavior and long-running response.
- [ ] Job progresses `QUEUED → PROCESSING → COMPLETED` / failure; staging `PENDING → COMMITTED/INVALID`; worker retries/leases preserve consistency.
- [ ] Database `products`/`transactions` rows match deterministic expected values for a known import; no cross-tenant leakage; no duplicate rows on job retry or identical reimport, according to agreed idempotency policy.
- [ ] Frontend recent imports display actual job status; list/review rows and error messages are not preview stubs.
- [ ] Approved, vaulted and mapped AI DB/API connector executes a bounded due sync and updates `last_synced_at` **only after genuine successful completion**; blocked/restricted sources do not sync.
- [ ] Connector staging records are actually promoted to intended business tables; fake `COMPLETED` without downstream records fails the test.
- [ ] Freshness, row totals, source limits and status calculations are independently checked against PostgreSQL.
- [ ] File imports do not accidentally populate paid-invoice or inventory business metrics; invoice/inventory import is independently verified when added.
- [ ] Frontend EN/AR/RTL, error/loading/empty states, reconnect/pause and stale-source warnings reflect backend truth.
- [ ] SSRF, external connection secrets, RLS, tenant role, rate-limit and provider authorization tests pass.
- [ ] Regression: Dashboard, Product Management, Demand Prediction and Market Intelligence are unaffected by connector and ingestion changes.

**Test verdicts:** PASS / FAIL / BLOCKED / SKIP / ERROR, with real API request, tenant ID, job ID, source ID, DB query and worker evidence; no unverified success claims. Live AI/provider tests must be opt-in and safe, with bounded duration/cost.

## 12. Source-code evidence map and handoff

**Node backend:**

- `src/modules/dataconnection/route/dataconnection.route.ts`
- `src/modules/dataconnection/service/dataconnection.service.ts`
- `src/modules/dataconnection/repo/dataconnection.repo.ts`
- `src/modules/dataconnection/repo/ingestion-worker.repo.ts`
- `src/modules/dataconnection/client/ingestion.client.ts`
- `src/modules/dataconnection/validators/extraction-template.validation.ts`
- `src/workers/data-ingestion.worker.ts`
- `src/config/production-plans.ts`
- `src/modules/dataconnection/DATA_INGESTION_AI_INTEGRATION.md`

**Frontend:**

- `src/features/data-connections/pages/ConnectDataPage.jsx`
- `src/features/data-connections/api/dataConnectionsApi.js`
- `src/features/data-ingestion/api/ingestionApi.js`
- `src/features/data-ingestion/config/dataTemplateOptions.js`

**AI team:**

- `src/market_scraper/connector_sync.py`
- `src/market_scraper/api_connector_sync.py`
- `src/market_scraper/connector_worker.py`
- `src/ai/extraction/ingestion_pipeline.py`
- `src/ai/extraction/promotion.py`
- `src/market_scraper/data_access.py`

### Final acceptance criterion

**A customer can identify a source, authorize it, import or synchronize valid data, inspect actual committed results, recover from errors, and know exactly when the information was last refreshed—and cannot see a misleading success message when none of that occurred.**

**Current conclusion:** Manual business-file ingestion has genuine backend infrastructure. Persistent connectors have source registration plus substantial AI-team polling components, but the Node↔AI configuration, credentials, scheduling, persistence and UI lifecycle are not connected sufficiently to claim production-ready data integration.
