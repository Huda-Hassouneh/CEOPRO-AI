# CEOPRO-AI — Document Extraction Business Specification

## 1. Business problem and outcome

Business owners already store transactions in Excel, CSV or PDF files and should not manually re-enter every sale into CEOPRO. The intended experience is: obtain the correct template, upload a file, validate its content, extract structured records, review a truthful processing status, and use successfully imported product and sales data in downstream modules.

**Example:** A Jordanian retailer uploads one correctly formatted spreadsheet containing 46 distinct products and sales lines. CEOPRO should stage the sales, create/reuse the tenant's products, insert valid transactions, retain evidence of errors, and correctly charge the extraction allowance. Re-uploading the document must not automatically double-count the same business transactions. **HTTP success at upload time does not prove canonical business data is persisted.**

## 2. Feature boundaries

| Feature                  | Controls                                                               | Scope and reset                                             |
| ------------------------ | ---------------------------------------------------------------------- | ----------------------------------------------------------- |
| `document_extraction`    | Cumulative size of successfully accepted business files for extraction | `limit` / `sum`, KB, billing period                         |
| `document_storage_mb`    | Tenant document storage capacity                                       | `limit` / `max`, MB, lifetime/current capacity              |
| `data_integration`       | Permission to register persistent external integrations                | Boolean; separate feature                                   |
| `connected_data_sources` | Active registered persistent sources                                   | Concurrent-capacity limit; manual file sources are inactive |
| `rag_assistant`          | RAG query/token processing                                             | Separate consumption and purpose                            |

**Data Connections business upload is not the Knowledge Base/RAG upload.** The routes and persistence paths differ. An inactive manual-file source should not occupy a persistent connection slot.

## 3. Plan allowances and mathematics

The saved production manifest (`src/config/production-plans.ts`) specifies:

| Plan                    | Extraction limit per billing period | Approximate MiB equivalent | Separate document-storage limit |
| ----------------------- | ----------------------------------: | -------------------------: | ------------------------------: |
| Starter ($55/month)     |                           51,200 KB |                     50 MiB |                        1,024 MB |
| Growth ($140/month)     |                          512,000 KB |                    500 MiB |                       10,240 MB |
| Enterprise ($350/month) |                        2,097,152 KB |          2,048 MiB (2 GiB) |                       51,200 MB |

Calculation used by the backend:

```
charge_kb = max(1, ceil(file_size_bytes / 1024))
remaining_kb = max(0, subscription_limit_kb - subscription_usage_kb)
storage_request_mb = file_size_bytes / (1024 * 1024)
```

**Example:** Files containing 1,536,000, 2,560,000, and 4,096,000 bytes charge 1,500 + 2,500 + 4,000 = 8,000 KB. A new billing period should use the new subscription-period usage allocation. A one-file limit is separate: `MAX_UPLOAD_BYTES` defaults to **10 MiB (10,485,760 bytes)**.

**Business upload storage policy:** Data Connections does not retain the original upload after extraction. Its persisted file size and hash are bookkeeping metadata, so this path does not consume `document_storage_mb`; that limit remains for retained Knowledge Base files.

## 4. Supported files and templates

**Backend upload accepts one multipart `file`:**

- `.csv`: valid CSV content, canonical headers and a non-empty data row.
- `.xlsx`: valid workbook, canonical headers and a non-empty data row.
- `.xlsm`: valid macro-enabled workbook, canonical headers and a non-empty data row.
- `.pdf`: valid PDF signature; AI must return matching structured sales rows.

The upload is constrained by extension, file signature/content shape, file size, and extraction-output checks.

**Required sales headers:**

`product_name, quantity, unit_price, currency, transaction_date`

**Optional columns in the supplied template:** `discount_pct`, `invoice_id`, `order_id`, `email`, `phone`, `competitor_name`, `amount_raw`.

Extra columns are tolerated. Header comparison trims and normalizes case/spaces/underscores, but alias-only columns such as `qty` are _not_ enough for a CEOPRO template-compliant import. The backend reads and checks its included CSV/XLSX template assets at runtime.

The Connect Data file picker now has a dedicated validator that matches the backend's four accepted types and the default **10 MiB** per-file limit. It downloads the backend's versioned sales CSV/XLSX templates. Chat attachments retain their separate validation rules.

The separately prepared **Invoice** and **Inventory** CSV/XLSX templates are planned domain imports. Their existence does not mean the current extraction endpoint supports those distinct schemas or persists `invoices` / `inventory`.

## 5. Actual request and processing lifecycle

1. **Authorize:** `POST /data-connection` requires an authenticated user, tenant membership, `data_integration`, and `document_extraction`.
2. **Validate file:** multer uses in-memory storage for one file, subject to `MAX_UPLOAD_BYTES`; local extension/content/header checks run before invoking AI.
3. **Check and reserve allowance:** check `document_extraction` remaining KB, then atomically reserve the rounded KB charge with an inactive source row and an `EXTRACTING` job. A tenant/feature advisory lock serializes the reservation with other metered usage updates. Exact file-hash retries reuse the active reservation.
4. **Call hosted AI:** backend `client/ingestion.client.ts` invokes analytics Gradio `extract_file` with `[sanitized_file_name, base64_file_bytes, country_code, currency]`; current defaults are `JO`, `JOD`.
5. **Validate AI output:** enforce response schema, canonical template mode, at least one processed row, and required typed fields before persistence.
6. **Stage:** in an RLS-scoped transaction, update the job to `QUEUED`, insert `import_staging_rows` with `PENDING` or review statuses, and mark the usage reservation committed.
7. **Release failures:** an AI, validation, or staging failure marks the extraction job failed and releases the reservation in a transaction. A stale in-progress retry reuses its active reservation, avoiding a second charge.
8. **Return upload result:** controller returns **HTTP 200** only after staging succeeds, with “Document extracted and queued for import” and the local job ID. This does not mean that downstream product/sales rows are committed.
9. **Process asynchronously:** `npm run worker:data-ingestion` polls, claims jobs with leases, validates staged sales, creates/reuses `products`, inserts `transactions`, commits/rejects rows, and updates job status.
10. **Consume downstream:** other features query their own authoritative tables. Dashboard revenue currently uses paid `invoices`, not these imported `transactions`; the two are not interchangeable.

**Current status fields:** `EXTRACTING`, `QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED` at the job level; finer staging validation and persistence states exist. The Connect Data page reads real job details and staging rows, supports correction and retry, and describes source registration as configured until a successful promoted sync is visible.

## 6. Database ownership and data producers

| Data/table                  | Owner/writer                                                                      | Meaning                                                              |
| --------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `data_sources`              | Node Data Connections repository                                                  | Inactive document metadata for manual file upload                    |
| `ingestion_jobs`            | Node upload path and ingestion worker                                             | Local queue and processing status                                    |
| `import_staging_rows`       | Node extraction mapping and ingestion worker                                      | Per-row extracted and validated content; source of job outcomes      |
| `products`                  | Node ingestion worker (also separate AI FastAPI extraction flow in AI repository) | Tenant product identity                                              |
| `transactions`              | Node ingestion worker (also separate AI FastAPI extraction flow)                  | Imported sales transactions                                          |
| `subscription_usage`        | Features/Entitlements module                                                      | Extraction amount consumed in billing period                         |
| `rag_documents_metadata`    | RAG/knowledge flow                                                                | Storage accounting currently used by `document_storage_mb`           |
| `invoices`, `invoice_items` | Separate invoice/Quick Sale integration                                           | Paid invoices are _not_ produced by the normal sales extraction path |
| `inventory`                 | Separate inventory ingestion needed                                               | Stock is _not_ produced by the current sales template                |

The AI-team archive includes its own FastAPI `/extraction/upload` logic and Python extraction, template detection, row parsing, promotion and persistence modules. **This is a separate pathway** from the hosted Gradio `extract_file` invocation in CEOPRO's Node client. The hosted Gradio implementation is not fully verifiable from the uploaded Python repository; do not assume these services share code or database-writing side effects. Node remains responsible for its own staging and worker promotion.

## 7. What is implemented vs. not verified

| Area                                              | Snapshot assessment                                                          |
| ------------------------------------------------- | ---------------------------------------------------------------------------- |
| Authentication and tenant context                 | Implemented in upload route                                                  |
| `document_extraction` entitlement                 | Enforced in upload route                                                     |
| Four file formats and template validation         | Implemented                                                                  |
| Gradio request/response adapter                   | Implemented; live availability not verified                                  |
| Tenant-scoped source/job/staging persistence      | Implemented                                                                  |
| Asynchronous ingestion worker with retry/progress | Implemented; runtime success depends on worker and database role             |
| Product/transaction promotion                     | Implemented for staged sales; real e2e must be verified                      |
| Subscription KB usage                             | Atomically reserved with source/job state; released on extraction/staging failure |
| Storage usage for manual business uploads         | Not charged because the original upload is transient                         |
| UI-supported file types and size                  | Matches backend formats and 10 MiB default                                   |
| Frontend downloadable sales CSV/XLSX              | Served from canonical backend templates                                      |
| Frontend real job/staging review                  | Uses tenant-scoped Node job and staging endpoints                            |
| Invoice and Inventory schema imports              | Not implemented through this endpoint                                        |
| Exact repeated-file uploads                        | Reuses the existing source/job by SHA-256; changed files with repeated sales may still duplicate transactions |

## 8. Key implementation gaps and decisions

1. **Define transaction-level duplicate identity** for changed files that contain previously imported sales; exact-file dedupe alone cannot identify semantically repeated transactions.
2. **Add Invoice and Inventory CSV/XLSX flows** with approved templates, validation rules, mapping rules, and safe promotion into `invoices`/`invoice_items` and `inventory`. The current sales contract is not a substitute.
3. **Verify the hosted AI contract and provider connectivity** against the deployed service, including malformed responses, timeouts, and row outcomes.
4. **Run UI/API/database/worker E2E tests** with an approved test database and fixtures; run real AI/provider tests separately and opt in explicitly.
5. **Keep tenant ownership and least-privilege RLS** enforced across upload, job, worker, and review paths.

## 9. Example customer scenarios

**A. Valid sales workbook.** Accepted under the current limit; Gradio returns canonical rows; the backend stages data and charges KB; the worker eventually commits correct product/sales records. The owner sees actual queue/processing/completion state.

**B. Wrong frontend template.** Customer downloads the present `Field,Value,Date,Notes` CSV and attempts upload. The backend rejects it. This is an application integration defect, not user error.

**C. Wrong file extension.** Customer selects a `.docx` file; frontend currently allows it, backend rejects it. Frontend and backend must agree.

**D. Concurrent quota boundary.** Tenant has 2,000 KB remaining and starts three 1,000 KB uploads simultaneously. Server-side allowance must not be overdrawn or double charged.

**E. AI succeeded, worker failed.** Upload succeeded and quota was charged, but product/transaction import later failed. Show accurate job status and agreed retry/refund policy; do not label the dataset “imported.”

**F. Repeated document.** Identical business records imported twice. Decide and test whether source IDs or stable transaction identifiers prevent unintended double counting.

**G. Invoice/stock document.** Not supported by current sales endpoint; link user to the correct new domain-specific workflow once implemented, not a false success.

## 10. E2E test design

Reuse the existing Playwright/TypeScript, PostgreSQL fixtures, diagnostic logger and reports from previous features. Structure three modes:

- **Deterministic E2E:** real frontend/Node backend/PostgreSQL and staged sales fixtures, independently verifying worker persistence. Controlled staged rows prove promotion, **not** live AI extraction.
- **AI contract tests:** controlled Gradio responses for transport/schema/timeout/error validation, explicitly identified as simulated upstream behavior.
- **Opt-in live AI E2E:** valid file → real hosted extraction call → source/job/staging → real worker → products/transactions → UI, with bounded timeouts, no production mutations, no fabricated passes.

### Acceptance checklist (unchecked until actually executed)

- [ ] Starter/Growth/Enterprise and custom-plan extraction limits match database entitlements.
- [ ] `ceil(bytes/1024)` calculation and billing-period reset are correct.
- [ ] Two+ simultaneous near-limit uploads cannot overdraw extraction allowance.
- [ ] An upload/retry cannot be charged twice or create an unmetered successful job.
- [ ] CSV, XLSX, XLSM and PDF valid-file cases work according to documented contract.
- [ ] Unsupported formats, invalid content, empty/oversize files and wrong template are rejected before AI.
- [ ] Frontend advertised extensions and max size match the backend.
- [ ] Frontend downloadable sales templates pass actual backend preflight.
- [ ] AI adapter sends correct positional input and validates every output field.
- [ ] AI timeout/null/malformed/partial-result cases preserve DB and metering consistency.
- [ ] CEOPRO-owned job ID, inactive file source and staging row counts are correct.
- [ ] Worker transitions through accurate processing status with bounded retry/recovery.
- [ ] Valid rows persist correct tenant-owned products/transactions; invalid rows do not.
- [ ] Repeated files and worker retries do not duplicate business facts.
- [ ] Storage capacity reflects truly retained business and RAG file bytes under agreed policy.
- [ ] Starter/other plan extraction access is server-side; disabled feature is denied.
- [ ] Tenant A cannot view, modify or process Tenant B's files, jobs, staging, or sales.
- [ ] Source/job state and quotas render correctly in English and Arabic/RTL.
- [ ] Invoice and Inventory imports are identified as separate blocked/implemented workflows, not implicitly supported.
- [ ] Live hosted Gradio extraction and least-privilege ingestion worker have been verified end-to-end.

## 11. Diagnostic expectations

For each test record mode, tenant/test identity, file type and size, expected KB charge, prior/post usage, job ID, staging row counts, commit/invalid counts, relevant HTTP status, error category, DB evidence and browser screenshot/trace when applicable. Report **PASS / FAIL / BLOCKED / SKIP / ERROR** separately. Never include file content, emails, passwords, JWTs, raw connection URLs or confidential row values in logs. Use only dedicated test tenants and databases, preserve RLS and avoid destructive operations against Render production.

Especially distinguish:

- `UPLOAD_VALIDATION_MISMATCH`
- `TEMPLATE_ASSET_MISMATCH`
- `EXTRACTION_QUOTA_RACE`
- `EXTRACTION_METERING_INCONSISTENCY`
- `DOCUMENT_STORAGE_ACCOUNTING_GAP`
- `AI_EXTRACTION_CONTRACT_ERROR`
- `STAGING_PERSISTENCE_ERROR`
- `INGESTION_PROMOTION_FAILURE`
- `DUPLICATE_SALES_IMPORT`
- `JOB_STATUS_INCORRECT`
- `TENANT_ISOLATION_FAILURE`

## 12. Source pointers, handoff, and release recommendation

**Backend:**

- `src/modules/dataconnection/route/dataconnection.route.ts`
- `src/modules/dataconnection/service/dataconnection.service.ts`
- `src/modules/dataconnection/client/ingestion.client.ts`
- `src/modules/dataconnection/validators/extraction-template.validation.ts`
- `src/modules/dataconnection/validators/extraction-result.validation.ts`
- `src/modules/dataconnection/repo/dataconnection.repo.ts`
- `src/modules/dataconnection/repo/ingestion-worker.repo.ts`
- `src/workers/data-ingestion.worker.ts`
- `src/modules/features/repo/usage.repo.ts`
- `src/modules/features/service/capacity.service.ts`
- `src/config/production-plans.ts`

**Frontend:**

- `src/features/data-ingestion/utils/fileValidation.js`
- `src/features/data-ingestion/config/dataTemplateOptions.js`
- `src/features/data-ingestion/api/ingestionApi.js`
- `src/features/data-ingestion/components/FileUploadDropzone.jsx`
- `public/assets/templates/ceopro-data-template.csv`

**AI codebase:**

- `src/ai/extraction/template_contract.py`
- `src/ai/extraction/template_detection.py`
- `src/ai/extraction/row_parsing.py`
- `src/ai/extraction/ingestion_pipeline.py`
- `src/ai/extraction/promotion.py`
- `src/ai/main.py` (FastAPI pathway; not the hosted Gradio implementation)

**Suggested implementation order:** align frontend formats/templates → atomic extraction quota and storage policy → truthful job/status views → duplicate control → full real AI/worker E2E testing. No new extraction framework or Kafka deployment is required solely for this feature; reuse the existing queue/worker architecture.

**Completion criterion:** A customer can upload a published template and get accurate, tenant-owned persisted business data, transparent job/error states, correct charges/storage accounting, and trustworthy downstream consumption—confirmed with real E2E evidence, not just HTTP 200.
