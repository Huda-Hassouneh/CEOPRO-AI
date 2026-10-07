# Data Connection Domain

## Purpose
Handles business-data file ingestion and persistent data-source management for a tenant.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`, with a Gradio extraction client and `types/` for contracts/validation.

## Request flow
`HTTP -> dataconnection.route -> dataconnection.controller -> dataconnection.service -> repo/client`

## Important decisions
- Business-data ingestion stays separate from the Knowledge Base/RAG user experience even when both use extraction infrastructure.
- Uploads require tenant authentication and the `document_extraction` entitlement.
- Allowed upload formats remain `.csv`, `.xlsx`, `.xlsm`, and `.pdf`; the upload-size limit defaults to 10 MB and can be set with `MAX_UPLOAD_BYTES`.
- Structured uploads must use the canonical required sales headers: `product_name`, `quantity`, `unit_price`, `currency`, and `transaction_date`. Alias-only headers may be recognized by the AI but are rejected for Data Connections. Unsupported headers are rejected before AI calls for CSV/Excel and before local persistence for PDFs.
- CEOPRO validates the AI's mode and every row's required typed fields before creating data sources, ingestion jobs, staging rows, or charging extraction usage.
- Persistent source metadata must not contain secrets such as passwords, API keys, tokens, or connection strings.
- External AI details are isolated in `client/ingestion.client.ts` and use the shared transport in `src/integrations/ai/`.
- Gradio returns extracted rows; CEOPRO creates local job/source/staging identifiers and does not trust provider-owned IDs or storage keys.

## Primary data
`data_sources`, `ingestion_jobs`, `import_staging_rows`, and related ingestion tables through the repository.

Rows in `import_staging_rows` are staged with `validation_status = PENDING` after successful extraction. The dedicated `src/workers/data-ingestion.worker.ts` polls every 10 seconds, revalidates pending sales rows, creates or reuses tenant products, inserts transactions, and marks each staging row `COMMITTED`. Invalid staged values are marked `INVALID` with a row-level reason. Jobs are claimed with `FOR UPDATE SKIP LOCKED`, retried with bounded exponential backoff, and recovered after an expired lease.

Run it as a separate process with `npm run worker:data-ingestion` and configure `INGESTION_WORKER_DATABASE_URL` for the `ceopro_ingestion_worker` role. The role is created by the ingestion-worker migration and has narrow grants plus RLS policies. The migration intentionally does not set a password; provision it through the deployment's secret-management process. The upload still waits for the current synchronous AI extraction call; the worker handles the database import after extraction.

For local setup, apply migrations with the normal privileged migration connection, set a password for `ceopro_ingestion_worker` using an administrative PostgreSQL session, then put that credential in `INGESTION_WORKER_DATABASE_URL`. Never put the password in a migration or commit it in `.env`.

## AI integration
See `DATA_INGESTION_AI_INTEGRATION.md`.
