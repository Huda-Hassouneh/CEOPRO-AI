# Data Connection Domain

Data Connections accepts structured business files, validates them, stages extracted sales rows, and imports valid rows into the tenant's products and transactions. It also stores metadata for persistent external data sources.

## Start here

| If you need to…                                    | Read…                                    |
| -------------------------------------------------- | ---------------------------------------- |
| Trace a request through the code                   | Request flow                             |
| Upload a sales file                                | Scenario A: Import a business file       |
| Register an external source                        | Scenario B: Register a persistent source |
| Confirm validation against the published templates | Template validation                      |
| Prepare the live AI integration test               | End-to-end verification checklist        |

## Purpose and boundaries

This domain has two related but distinct flows:

1. **Business-file import:** an uploaded CSV, Excel, or PDF file is sent to the AI extraction service. CEOPRO validates the extraction, creates a local import job, stores staged rows, and a background worker writes valid sales into transactions and creates or reuses products.
2. **Persistent source registration:** the tenant stores a supported source's name, type, sync frequency, and non-secret metadata. Creating the record does not by itself test credentials, connect to the source, or run a sync.

Invoice and inventory imports are a third, deterministic Node flow. They do not call the AI service. Their routes are `POST /data-connection/imports/:kind/preview`, `POST /data-connection/imports/:kind/previews/:draftId/review`, and `POST /data-connection/imports/:kind/previews/:draftId/confirm`, where `kind` is `invoices` or `inventory`. The legacy immediate `POST /data-connection/imports/:kind` remains available for existing integrations. The sales upload routes are unchanged.

### Scenario: a customer has no products yet

1. Download the invoice or inventory CSV/XLSX template. Use `product_name`, with optional `sku`; internal product UUIDs are unnecessary. A catalog reference download lists names and SKUs without UUIDs.
2. Upload one file and inspect the preview. A preview saves an expiring draft only; it does not create business records or charge document extraction usage.
3. Choose an existing tenant product for missing or ambiguous rows, or explicitly create a new product with a price and supported currency when Product Management is included. Name matches are exact after Unicode/space/case normalization; SKU matches are case insensitive. A conflicting ID/name/SKU requires a corrected file. Existing UUID files remain valid.
4. Review the proposed invoice/item counts and stock balances, including which existing quantity will be replaced. Confirm only after the review. The backend locks the draft, rechecks catalog and stock, reserves the extraction quota, writes products/invoices/items or inventory and a completed job in one transaction, and clears the saved file bytes. Repeated confirmation returns the original result without another charge. A changed balance requires a fresh review.

Apply `prisma/migrations/20261012020000_reviewable_business_imports` and regenerate Prisma Client before starting the updated backend. Drafts expire after one hour. Expired drafts and old completed results are pruned when that user previews another file. No external connector or AI code is changed.

Run `node --import tsx tests/dashboard/dashboard-analytics-import.test.ts` and `node --import tsx tests/dashboard/business-product-matching.test.ts` for the parser and matching cases. For a real test tenant with the migration applied, frontend/API servers running, a valid token, document extraction allowance, and Product Management access, set `STRUCTURED_IMPORT_TEST=1`, `DASHBOARD_TEST_ACCESS_TOKEN`, `DASHBOARD_TEST_TENANT_ID`, `DASHBOARD_TEST_USER_ID`, and `DASHBOARD_TEST_DATABASE_URL`, then run `npm run test:dashboard:structured-import`. The opt-in test writes uniquely named test products, stock and invoices in that tenant, confirms twice, and reads the records back through RLS. It skips unless explicitly enabled. Sales still has its separate AI/worker E2E test.

Business-file uploads are separate from Knowledge Base/RAG document uploads. They use the extraction service to produce structured sales data.

## Request flow

HTTP → route → controller → service → repository or AI client
↓
ingestion worker → products + transactions

- index.ts exports the router and applies the module mount path /data-connection.
- route/dataconnection.route.ts applies authentication and tenant middleware, upload parsing, and feature-entitlement checks.
- controller/dataconnection.controller.ts reads authenticated tenant/user context and formats HTTP success or error responses.
- service/dataconnection.service.ts validates input, checks feature capacity/usage, calls extraction, validates the result, and coordinates persistence.
- client/ingestion.client.ts calls the AI extraction contract through the shared integration transport.
- repo/dataconnection.repo.ts reads overview data and writes local sources, jobs, and staged rows.
- repo/ingestion-worker.repo.ts claims queued import jobs and commits staged sales in database transactions.
- validators/ and types/ contain request, template, AI-response, and persisted-row validation.
- templates/ contains the published CSV and XLSX sales import templates.

The route file defines GET /, POST / for file upload, and POST /sources. The module router adds /data-connection; the final URL can also depend on the parent router mount. The integration notes describe the current upload URL as POST /data-connection.

## Scenario A: Tenant imports a business file

### 1. Upload and local preflight

**Request:** POST /data-connection with one multipart field named file.

The user must be authenticated, have tenant context, and have the document_extraction entitlement. Multer accepts one in-memory file. Allowed extensions are .csv, .xlsx, .xlsm, and .pdf; the default maximum is 10 MB, configurable with MAX_UPLOAD_BYTES.

The service checks the file buffer, extension, size, and template compatibility before calling AI. It also checks the tenant's remaining document_extraction usage and document_storage_mb capacity.

### 2. AI extraction and response validation

CEOPRO calls the analytics extract_file API with the sanitized filename, file bytes encoded as Base64, and country/currency defaults. The client validates the response shape. The service then requires template-compliant headers and rows, no partial or failed rows, and structured values for every required sales field.

If validation fails, no CEOPRO source, job, or staging rows are created, and document-extraction usage is not incremented.

### 3. Stage the import

After the AI response passes validation, CEOPRO creates its own job ID. AI-provided IDs and storage keys are not trusted. In one database transaction, CEOPRO creates:

- A data_sources row of type documents, marked inactive because a manual upload is not a persistent connector.
- An ingestion_jobs row with status QUEUED.
- import_staging_rows records with status PENDING.

Document-extraction usage is incremented after these records are persisted. The API responds with the CEOPRO job ID and extraction summary. The AI extraction request itself is synchronous; the subsequent database import is asynchronous.

### 4. Worker validates and imports

Run the worker separately with npm run worker:data-ingestion. It polls for work every 10 seconds, claims jobs using FOR UPDATE SKIP LOCKED, and processes the staged sales rows.

The worker validates required values again at the persistence boundary. It creates or reuses a tenant product, inserts a transaction, and marks the staging row COMMITTED with its transaction reference. Invalid rows are marked INVALID with a reason. Database failures roll back the job transaction and are retried with bounded exponential backoff; an expired processing lease can be recovered.

The worker uses INGESTION_WORKER_DATABASE_URL and the least-privilege ceopro_ingestion_worker database role. Provision its password outside migrations and keep it in deployment secrets.

## Scenario B: Tenant registers a persistent source

**Request:** POST /data-connection/sources.

The user must be authenticated, have tenant context, and have the data_integration entitlement. The service checks the tenant's connected_data_sources capacity.

Supported sourceType values are shopify, postgresql, mysql, sqlserver, ga4, and website. The default syncFrequencyMinutes is 1440. Metadata must be a JSON object and is rejected if secret-like keys appear, including passwords, tokens, API keys, and connection strings.

The source record is created active and consumes source capacity. This endpoint only registers configuration metadata: it does not prove that the external connection works or perform a sync.

## Scenario C: Frontend loads the connections overview

**Request:** GET /data-connection (subject to the outer router mount).

The response includes:

- connectedSources: persistent source records and their latest job-derived status/record count.
- recentImports: recent ingestion jobs and their mapped statuses.
- availableSourceTypes: the categories exposed by the current API.

The repository reads tenant-scoped rows from data_sources and ingestion_jobs. It does not report a manual uploaded file as a persistent connected source.

## Template validation

The published templates are:

- templates/ceopro_sales_transaction_import_v1.csv
- templates/ceopro_sales_transaction_import_v1.xlsx

The local validator reads the header row from both files, verifies that their normalized headers match, and checks that the required sales fields are present. The fields required by the current contract are product_name, quantity, unit_price, currency, and transaction_date. The template also includes optional fields: discount_pct, invoice_id, order_id, email, phone, competitor_name, and amount_raw.

For CSV and Excel uploads, the first row must match the canonical template fields after trimming and normalizing case, spaces, and underscores, and the file must contain at least one non-empty data row. Extra columns are tolerated. AI-recognized alias-only headers (for example, qty or price) do not satisfy the Data Connections template contract.

PDF preflight checks the PDF signature. After extraction, the returned headers and every extracted row are checked against the same required template contract before CEOPRO creates import records.

**Keep the templates available at runtime.** The validator loads files relative to its module first, then checks the conventional source and dist template paths. A production build/deployment must include dataconnection/templates/ in one of those locations. If the CSV and XLSX headers differ, or a required template header is removed, validation fails with a configuration error rather than silently using an older hard-coded header list.

When changing the template, update the AI team's matching extraction contract as well. The alias matcher and row parser also have their own field rules; keep these aligned with the shared AI contract.

## Data ownership and downstream use

### Records written by this domain

- data_sources: manual upload metadata and persistent source configuration.
- ingestion_jobs: CEOPRO-owned import and sync job state.
- import_staging_rows: extracted row payloads, validation state, and commit references.
- products: created or reused for imported product names.
- transactions: imported sales, marked with sale_source = IMPORT.

### Other systems and metrics

This domain's concrete business-data output is imported product and transaction data. Other application systems may consume those tables, but this folder does not calculate dashboard metrics or send events directly.

In particular, verify each dashboard metric's real source during integration testing. The dashboard implementation may read a different source table (for example, paid invoices rather than imported transactions), so a successful import does not by itself prove that a dashboard KPI changes.

## End-to-end verification checklist

Use this during the real end-to-end run with the AI team. All boxes are intentionally unchecked. Record a request/response sample, database query, job ID, or UI evidence after you verify an item.

### Template and upload checks

- [ ] Template/file case: ********\_\_\_\_******** Expected headers and row values: ********\_\_\_\_******** Result/evidence: ********\_\_\_\_********
- [ ] Template/file case: ********\_\_\_\_******** Expected headers and row values: ********\_\_\_\_******** Result/evidence: ********\_\_\_\_********
- [ ] Template/file case: ********\_\_\_\_******** Expected headers and row values: ********\_\_\_\_******** Result/evidence: ********\_\_\_\_********

### Metrics and imported records

- [ ] Metric/table: ********\_\_\_\_******** Expected source and calculation: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********
- [ ] Metric/table: ********\_\_\_\_******** Expected source and calculation: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********
- [ ] Metric/table: ********\_\_\_\_******** Expected source and calculation: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********

### AI-team handoff

- [ ] AI output/field: ********\_\_\_\_******** Expected typed value and mapping: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********
- [ ] AI output/field: ********\_\_\_\_******** Expected typed value and mapping: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********
- [ ] AI output/field: ********\_\_\_\_******** Expected typed value and mapping: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********

### Other systems or consumers

- [ ] Consumer/system: ********\_\_\_\_******** Data consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********
- [ ] Consumer/system: ********\_\_\_\_******** Data consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********
- [ ] Consumer/system: ********\_\_\_\_******** Data consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********

## Folder map

    dataconnection/
    ├── client/
    ├── controller/
    ├── repo/
    ├── route/
    ├── service/
    ├── templates/
    ├── types/
    ├── validators/
    ├── DATA_INGESTION_AI_INTEGRATION.md
    ├── index.ts
    └── README.md

## Related documentation

- AI integration contract: DATA_INGESTION_AI_INTEGRATION.md
- Shared integration configuration: ../../../INTEGRATIONS.md, section data-connection-ingestion
