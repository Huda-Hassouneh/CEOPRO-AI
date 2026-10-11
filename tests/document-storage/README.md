# Document Storage diagnostics

This suite audits CEOPRO's retained customer knowledge files, business-upload accounting, PostgreSQL storage, and AI MinIO outputs. It reuses the shared Playwright config and reporter.

## Verified implementation map

| Path | Current behavior |
| --- | --- |
| `backend/src/modules/rag` | Customer RAG uploads are capped at 2 MiB and persist original file bytes in `rag_documents_metadata.source_file_content` (PostgreSQL BYTEA). The stored path is a `ceopro-db://` marker; this upload path does not write the original to MinIO. |
| `backend/src/modules/features/service/capacity.service.ts` | `document_storage_mb` usage is the sum of RAG metadata `file_size_bytes` divided by 1,048,576. It includes every metadata row, regardless of content or processing status. |
| `backend/src/modules/dataconnection` | Business uploads call the document storage capacity check, but do not retain original bytes; the file is sent through the separate Gradio ingestion path. They therefore can be rejected by storage limits without being counted as retained storage. |
| `ai/src/ai/extraction/minio_persistence.py` | MinIO stores derived JSON extraction outputs in `ceopro-extraction-results` under tenant/job paths. This is distinct from source upload storage. |
| `ai/src/ai/rag/structured_summaries.py` | Generated summary objects use `_generated/{slot}.txt`; the key does not include the tenant ID although the metadata row is tenant-scoped. |

## Findings from source contracts

- Frontend RAG file validation allows up to 50 MiB while the API accepts 2 MiB. It permits CSV and image types the API rejects, omits Markdown that the API accepts, and the API client checks a different 10 MiB threshold.
- The frontend maps listed RAG documents to `active` instead of preserving `processed_status`.
- Capacity is checked before the database insert with no atomic reservation. Concurrent uploads can race past the tenant limit.
- There is no RAG document delete route or UI action, so retained capacity has no customer reclamation path.
- The capacity is calculated in binary MiB but labeled MB in the catalog and billing display.
- Business extraction charges against `document_storage_mb` using transient file size, but actual capacity totals only `rag_documents_metadata`.
- Structured summary MinIO object keys are not tenant-qualified, which creates a potential collision between tenants using the same summary slot. This is a source-level risk finding, not a demonstrated live cross-tenant read.
- The AI MinIO client requires root credentials. No restricted service identity is configured in the checked source.

## Coverage and execution

- Source/migration contracts run with `npm run test:document-storage:contract` and require no services.
- Playwright scenarios are registered as **BLOCKED** until real assertions can use an explicitly disposable DB, API, tenant fixtures, cleanup, and (for MinIO cases) a disposable endpoint/bucket. They do not simulate persistence or claim live coverage.
- `npm run test:document-storage:live-minio` is separately opt-in and refuses to be represented as covered without fixture-specific implementation.
- Python AI MinIO tests are not part of the passing contract command; this environment has no pytest runtime or safe MinIO credentials.

## Commands (PowerShell, from `backend/`)

```powershell
npm run test:document-storage
npm run test:document-storage:contract
npm run test:document-storage:quota
npm run test:document-storage:concurrency
npm run test:document-storage:postgres
npm run test:document-storage:rag
npm run test:document-storage:minio-contract
npm run test:document-storage:e2e
npm run test:document-storage:headed
npm run test:document-storage:single
$env:DOCUMENT_STORAGE_LIVE_MINIO = "1"
npm run test:document-storage:live-minio
npm run test:document-storage:report
```

The contract tests intentionally contain regression assertions for confirmed source gaps. A failing regression records a defect; it is not evidence that live storage was tested. The E2E suite uses the shared output at `tests/reports/e2e/`.

## Required safe E2E setup

Set `DOCUMENT_STORAGE_TEST_DATABASE_URL` to a disposable migrated DB whose database name includes `test`, `testing`, `qa`, or `e2e`; set `DOCUMENT_STORAGE_TEST_API_URL`, `DOCUMENT_STORAGE_TEST_FIXTURES`, and, only for object tests, `DOCUMENT_STORAGE_MINIO_ENDPOINT`. Configure an authenticated tenant and cleanup owner before adding live assertions. Never point these variables at production data.
