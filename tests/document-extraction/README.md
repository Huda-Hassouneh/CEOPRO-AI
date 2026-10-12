# Document Extraction Testing

## Verified ownership map

| Stage | Current owner and behavior |
|---|---|
| Upload API | Node `POST /data-connection`, mounted from `src/modules/dataconnection`; authenticated user, tenant, `data_integration`, and `document_extraction` entitlements are required. One multipart field named `file` is accepted. |
| Compatibility route | `POST /features/extraction/upload` delegates to Data Connections. The pending batch route returns `501 NOT_IMPLEMENTED`. |
| File validation | Node checks extension, actual size/buffer consistency, size ceiling, signatures, and CSV/XLSX template headers. Allowed suffixes: CSV, XLSX, XLSM, PDF. Default ceiling is 10 MiB via `MAX_UPLOAD_BYTES`. |
| Sales template | Canonical required fields: `product_name, quantity, unit_price, currency, transaction_date`. Optional canonical fields include `discount_pct, invoice_id, order_id, email, phone, competitor_name, amount_raw`. Alias-only headers do not satisfy this upload contract. |
| Extraction service | Node's `dataconnection/client/ingestion.client.ts` calls the analytics Gradio API method `extract_file` with `[safe_filename, base64_bytes, country_code, currency]`; defaults are `JO` and `JOD`. It validates the response schema and does not send this request to AI FastAPI `/extraction/upload`. |
| Staging | Node owns `data_sources`, `ingestion_jobs`, and `import_staging_rows`. A manual upload first reserves an inactive `documents` source and a CEOPRO UUID job in `EXTRACTING`, then commits staging rows and marks the job `QUEUED` in a tenant transaction. |
| Usage | Extraction usage is `max(1, ceil(bytes / 1024))` KB. The upload reserves usage atomically with its source/job row under a tenant/feature lock; staging commits the reservation, and extraction/staging failures release it. A stale retry reuses its reservation. |
| Storage | Extraction usage and `document_storage_mb` are separate. Data Connections business uploads retain only metadata, not original file bytes, and therefore do not consume the retained-document storage allowance. Knowledge Base uploads use their own storage accounting. |
| Worker | Node's `data-ingestion.worker.ts` claims with `FOR UPDATE ... SKIP LOCKED`, leases/retries jobs, revalidates staging, and commits products/transactions. Products are matched by tenant plus normalized English name. Existing products are reused without a current-price update. |
| AI Python implementation | `ai/src/ai/main.py` also has `/extraction/upload`, a separate FastAPI implementation. Do not interpret its MinIO/object-storage or database effects as the Node Gradio upload's side effects. |
| RAG | Knowledge Base uploads use the RAG module, `rag_documents_metadata`, and RAG storage behavior. Business sales uploads use Data Connections and staging. They are distinct flows. |

## Tests and commands

Run from `backend/`:

```powershell
npm run test:document-extraction:contract
npm run test:document-extraction:files
npm run test:document-extraction:quota
npm run test:document-extraction:ai-contract
npm run test:document-extraction:worker
npm run test:document-extraction:e2e
npm run test:document-extraction
npm run test:document-extraction:headed
npm run test:document-extraction:single -- --grep "CSV upload"
npm run test:document-extraction:report
npm run test:all-features
```

For live Gradio only, explicitly opt in from PowerShell:

```powershell
$env:DOCUMENT_EXTRACTION_LIVE_AI = "1"
npm run test:document-extraction:live-ai
Remove-Item Env:DOCUMENT_EXTRACTION_LIVE_AI
```

The Playwright scenarios are diagnostic registrations only and are unconditionally skipped: fixture-specific API/database assertions have not been implemented, and this workspace has no approved test infrastructure. The proposed environment contract is `DOCUMENT_EXTRACTION_TEST_DATABASE_URL`, `DOCUMENT_EXTRACTION_TEST_API_URL`, and `DOCUMENT_EXTRACTION_TEST_FIXTURES`. Before activating any scenario, implement its actual request, independent database assertions, and cleanup; verify the database name includes `test`, `testing`, `qa`, or `e2e`; reject production mode; and use an application role without superuser or `BYPASSRLS`. Do not point these variables at Render production.

Contract tests verify source-level behavior; passing them does not prove live database concurrency or worker outcomes. Playwright scenarios stay BLOCKED until executable fixtures/assertions and an approved test environment are available. Live Gradio extraction additionally requires `DOCUMENT_EXTRACTION_LIVE_AI=1` and a completed safe live-test harness.

## Verified policy and gaps

- Plans set monthly extraction allowances to Starter `51,200 KB`, Growth `512,000 KB`, and Enterprise `2,097,152 KB`; the usage meter follows its feature reset cycle. The current per-file byte charge is rounded up to KB, minimum one KB.
- Extraction usage is reserved under a tenant/feature advisory lock in the same transaction that creates the source/job reservation. The reservation is committed with staging or released on extraction/staging failure; stale retries reuse it.
- Node and the Connect Data picker agree on `MAX_UPLOAD_BYTES` (default 10 MiB) and the CSV, XLSX, XLSM, and PDF formats. Knowledge Base chat attachments have a separate file-validation contract.
- Backend templates are versioned as `ceopro_sales_transaction_import_v1.csv/.xlsx`; the frontend downloads those templates from the authenticated Node endpoint.
- PDFs are signature-checked locally; their header/row contract can only be verified after extraction. XLSM is allow-listed and uses the XLSX parser; macros are not executed.
- Product reuse is implemented. The worker transaction insert has no invoice/order/source-row idempotency identity, so repeated imports can duplicate legitimate transactions. Do not infer transaction deduplication from product reuse.
- Extraction file bytes are not shown retained as a RAG document by the Node business upload path. Current storage-capacity accounting does not clearly account for those retained business bytes. No retention charge should be inferred from metadata alone.
- The Connect Data import list and staging review use persisted job/staging endpoints, with retry and correction actions. UI/database E2E behavior remains unverified without an approved test environment.
- RLS worker policy, job claim, retries and transactional promotion are covered as source/migration contracts. Database mutation, retry fault injection, tenant isolation, and downstream Dashboard/Forecasting comparisons remain blocked without a safe DB and fixtures.

## Coverage matrix from this workspace

| Test area | Local validator/contract | UI | Database / worker | Result |
|---|---|---|---|---|
| CSV and XLSX | Yes | Blocked | Blocked | Validator tests run; real lifecycle blocked |
| XLSM | Existing parser test and allow-list contract | Blocked | Blocked | Local coverage; worker persistence not run |
| PDF | Signature preflight contract | Blocked | Blocked | AI extraction not run |
| Invalid/missing/empty/mismatched files | Yes | Blocked | Blocked | Pure checks run; multipart route not run |
| File-size boundary | Below, exact, and above default | Blocked | N/A | Local checks run |
| Template download/upload | Source contract | Blocked | N/A | Canonical backend CSV/XLSX templates are now served to Connect Data |
| Quota rounding and boundary | Source contract | Blocked | Blocked | Formula and atomic reservation path checked; no DB usage deltas |
| Concurrent quota requests | Source contract | Blocked | Blocked | Advisory-lock reservation checked; no live concurrency test |
| Gradio request/response | Controlled client contract | N/A | N/A | Contract tests run; not live extraction |
| Staging and worker persistence | Existing source/row/migration contracts | Blocked | Blocked | No DB worker run |
| Import idempotency | Source contract | Blocked | Blocked | Exact file-hash retries are deduplicated; changed files can repeat sales rows |
| Storage accounting | Source audit | Blocked | Blocked | Business upload bytes are transient and excluded from retained storage usage |
| Entitlements and RLS | Route/migration contracts | Blocked | Blocked | No tenant API/SQL run |
| Localization and responsive UX | Copy/source regression | Blocked | N/A | English and Arabic upload format/size copy aligned |
| Downstream analytics | N/A | Blocked | Blocked | No imported fixture to compare |

## Reports and failure interpretation

Playwright uses the shared `playwright.config.ts`, including the configured HTML/JSON reporters, screenshots, and traces. The current deterministic E2E list records explicit skip annotations with category, tables, expected prerequisite, and investigation guidance. Contract failures identify source locations through assertion messages; they are not live execution diagnostics and cannot prove rows were or were not written in a real database.

Categories added/reused here include `EXTRACTION_QUOTA_RACE_CONDITION`, `FRONTEND_BACKEND_VALIDATION_MISMATCH`, `TEMPLATE_HEADER_MISMATCH`, `DUPLICATE_IMPORT`, `AI_EXTRACTION_UNAVAILABLE`, and `TEST_ENVIRONMENT_BLOCKED`.
