# Business data extraction

The CEOPRO routes remain `POST /data-connection` and the compatibility route `POST /features/extraction/upload`. Both use the analytics Gradio API `extract_file` through the shared `src/integrations/ai` transport.

The positional input is `[file_name, file_base64, country_code, currency]`. CEOPRO validates the extension, content signature, configured upload-size limit (10 MB by default), and required sales headers. Data Connections accept only the canonical template headers: `product_name`, `quantity`, `unit_price`, `currency`, and `transaction_date` (additional canonical optional columns are allowed). The AI may recognize alias-based inputs, but those are not accepted for Data Connections because its recognized mode does not guarantee the required currency and transaction date fields.

After extraction, CEOPRO rejects non-canonical headers, empty files, failed/partial rows, or rows missing any required typed field before creating any CEOPRO data source, ingestion job, staging rows, or charging usage. PDFs are signature-checked locally and their extracted headers and rows are validated from the AI response before persistence.

Accepted extracted rows are recorded in `import_staging_rows` with `validation_status = PENDING`. The dedicated Data Connections worker polls queued jobs every 10 seconds, revalidates the staged sales fields, creates/reuses the tenant product, inserts the transaction, and records `COMMITTED` plus the transaction ID on the staging row. Invalid staged rows become `INVALID`; a database failure rolls back the job transaction and schedules a retry. The current AI extraction request remains synchronous; only the post-extraction database import runs in the worker.

Run the worker separately with `npm run worker:data-ingestion`. It uses `INGESTION_WORKER_DATABASE_URL` and the least-privilege `ceopro_ingestion_worker` role created by migration `20261006120000_business_data_ingestion_worker`. Set a password outside migrations and keep the connection URL in the worker's secret environment.

The model response does not supply CEOPRO identifiers or a MinIO key. AI response values are not logged because rows may contain customer contact information.

The compatibility route `POST /features/extraction/process-pending` remains mounted and returns HTTP 501. The current `extract_file` API handles each submitted file synchronously.

See [`../../../INTEGRATIONS.md`](../../../INTEGRATIONS.md#data-connection-ingestion) for the full contract and environment configuration.
