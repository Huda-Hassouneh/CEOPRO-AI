# Document Extraction Testing

## Verified ownership map

| Stage | Current owner and behavior |
|---|---|
| Upload API | Node `POST /data-connection`, mounted from `src/modules/dataconnection`; authenticated user, tenant, and `document_extraction` entitlement are required. One multipart field named `file` is accepted. |
| Compatibility route | `POST /features/extraction/upload` delegates to Data Connections. The pending batch route returns `501 NOT_IMPLEMENTED`. |
| File validation | Node checks extension, actual size/buffer consistency, size ceiling, signatures, and CSV/XLSX template headers. Allowed suffixes: CSV, XLSX, XLSM, PDF. Default ceiling is 10 MiB via `MAX_UPLOAD_BYTES`. |
| Sales template | Canonical required fields: `product_name, quantity, unit_price, currency, transaction_date`. Optional canonical fields include `discount_pct, invoice_id, order_id, email, phone, competitor_name, amount_raw`. Alias-only headers do not satisfy this upload contract. |
| Extraction service | Node's `dataconnection/client/ingestion.client.ts` calls the analytics Gradio API method `extract_file` with `[safe_filename, base64_bytes, country_code, currency]`; defaults are `JO` and `JOD`. It validates the response schema and does not send this request to AI FastAPI `/extraction/upload`. |
| Staging | Node owns `data_sources`, `ingestion_jobs`, and `import_staging_rows`. A manual upload creates an inactive `documents` source, a CEOPRO UUID job in `QUEUED`, and pending staging rows in a tenant transaction. |
| Usage | Extraction usage is `max(1, ceil(bytes / 1024))` KB. It is incremented after staging persistence succeeds. Validation, AI, and persistence failure before that point should not be charged. The current quota read and later increment are not an atomic reservation. |
| Storage | Extraction usage and `document_storage_mb` are separate. Current storage capacity is resolved primarily from RAG document metadata, while uploaded sales-file size is stored with business-file source metadata. This is a retention/accounting contract gap to resolve before asserting a stored-byte charge. |
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

`test:document-extraction:contract` includes regression assertions that intentionally fail while verified application gaps remain. A nonzero exit is useful evidence; do not weaken those assertions to make the suite green. Playwright scenarios stay BLOCKED even if credentials are added until executable fixtures/assertions have been reviewed and implemented. Live Gradio extraction additionally requires `DOCUMENT_EXTRACTION_LIVE_AI=1` and a completed safe live-test harness.

## Verified policy and gaps

- Plans set monthly extraction allowances to Starter `51,200 KB`, Growth `512,000 KB`, and Enterprise `2,097,152 KB`; the usage meter follows its feature reset cycle. The current per-file byte charge is rounded up to KB, minimum one KB.
- Extraction usage is applied after successful staging persistence. There is no atomic quota reservation across simultaneous uploads, so two requests may both pass a stale remaining-quota check.
- Node's upload ceiling and Multer configuration agree on `MAX_UPLOAD_BYTES` (default 10 MiB). Frontend copy currently advertises 50 MB and unsupported Word, legacy XLS, TXT, and image formats.
- Backend templates are versioned as `ceopro_sales_transaction_import_v1.csv/.xlsx`; frontend downloads point to separate `ceopro-data-template.csv/.xlsx/.pdf` assets and its client labels the path as preview. Compatibility is not established by a successful download link.
- PDFs are signature-checked locally; their header/row contract can only be verified after extraction. XLSM is allow-listed and uses the XLSX parser; macros are not executed.
- Product reuse is implemented. The worker transaction insert has no invoice/order/source-row idempotency identity, so repeated imports can duplicate legitimate transactions. Do not infer transaction deduplication from product reuse.
- Extraction file bytes are not shown retained as a RAG document by the Node business upload path. Current storage-capacity accounting does not clearly account for those retained business bytes. No retention charge should be inferred from metadata alone.
- The frontend import list/staging review API functions are empty preview stubs. Its upload action calls the actual API, but there is not yet evidence for persisted job progress in that UI.
- RLS worker policy, job claim, retries and transactional promotion are covered as source/migration contracts. Database mutation, retry fault injection, tenant isolation, and downstream Dashboard/Forecasting comparisons remain blocked without a safe DB and fixtures.

## Coverage matrix from this workspace

| Test area | Local validator/contract | UI | Database / worker | Result |
|---|---|---|---|---|
| CSV and XLSX | Yes | Blocked | Blocked | Validator tests run; real lifecycle blocked |
| XLSM | Existing parser test and allow-list contract | Blocked | Blocked | Local coverage; worker persistence not run |
| PDF | Signature preflight contract | Blocked | Blocked | AI extraction not run |
| Invalid/missing/empty/mismatched files | Yes | Blocked | Blocked | Pure checks run; multipart route not run |
| File-size boundary | Below, exact, and above default | Blocked | N/A | Local checks run |
| Template download/upload | Regression assertion | Blocked | N/A | Known frontend/backend contract mismatch |
| Quota rounding and boundary | Source contract | Blocked | Blocked | Formula verified; no DB usage deltas |
| Concurrent quota requests | Regression assertion | Blocked | Blocked | Non-atomic check/increment found |
| Gradio request/response | Controlled client contract | N/A | N/A | Contract tests run; not live extraction |
| Staging and worker persistence | Existing source/row/migration contracts | Blocked | Blocked | No DB worker run |
| Import idempotency | Regression assertion | Blocked | Blocked | Product reused; transaction key missing |
| Storage accounting | Source audit | Blocked | Blocked | Retention/usage relationship unresolved |
| Entitlements and RLS | Route/migration contracts | Blocked | Blocked | No tenant API/SQL run |
| Localization and responsive UX | Copy/source regression | Blocked | N/A | English and Arabic format mismatch found |
| Downstream analytics | N/A | Blocked | Blocked | No imported fixture to compare |

## Reports and failure interpretation

Playwright uses the shared `playwright.config.ts`, including the configured HTML/JSON reporters, screenshots, and traces. The current deterministic E2E list records explicit skip annotations with category, tables, expected prerequisite, and investigation guidance. Contract failures identify source locations through assertion messages; they are not live execution diagnostics and cannot prove rows were or were not written in a real database.

Categories added/reused here include `EXTRACTION_QUOTA_RACE_CONDITION`, `FRONTEND_BACKEND_VALIDATION_MISMATCH`, `TEMPLATE_HEADER_MISMATCH`, `DUPLICATE_IMPORT`, `AI_EXTRACTION_UNAVAILABLE`, and `TEST_ENVIRONMENT_BLOCKED`.
