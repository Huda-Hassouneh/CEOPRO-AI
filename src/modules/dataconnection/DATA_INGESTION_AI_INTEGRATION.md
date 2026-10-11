# Data ingestion AI integration

This document describes how a file moves from the Data Connections API through AI extraction and into CEOPRO's sales data. The AI call is synchronous; database import runs afterward in a background worker.

## 1. API surface

The Data Connections router is mounted at `POST /data-connection` for file uploads. It also exposes `GET /data-connection` for the overview and `POST /data-connection/sources` to create a persistent source record.

All routes in this module require an authenticated user and tenant. Uploads require the `document_extraction` permission; creating a persistent source requires `data_integration`.

This module does not register the compatibility routes `POST /features/extraction/upload` or `POST /features/extraction/process-pending`. The controller contains a `processPending` handler that returns HTTP 501 if mounted elsewhere. Check the application-level router before documenting or relying on legacy route paths.

## 2. Extraction request contract

The upload accepts one CSV, XLSX, XLSM, or PDF file. The upload limit is configured by `MAX_UPLOAD_BYTES` and defaults to 10 MiB. CEOPRO checks the extension, content signature, and configured size before calling AI.

The shared AI transport calls the analytics Gradio API's `extract_file` method with positional inputs:

```text
[file_name, file_base64, country_code, currency]
```

The default country and currency are `JO` and `JOD`. The filename is sanitized before it is sent. The AI response is checked against the expected response schema before CEOPRO uses it.

## 3. Template validation

Data Connection uploads must match the canonical sales import template in `templates/ceopro_sales_transaction_import_v1.csv` and `templates/ceopro_sales_transaction_import_v1.xlsx`. At startup/use, the validator reads both template files, confirms their headers agree, and validates the upload header against those fields. The required headers are:

| Required field     | Meaning              |
| ------------------ | -------------------- |
| `product_name`     | Product name         |
| `quantity`         | Quantity sold        |
| `unit_price`       | Unit price           |
| `currency`         | Transaction currency |
| `transaction_date` | Date of sale         |

The templates also define optional canonical fields, including `discount_pct`, `invoice_id`, `order_id`, `email`, `phone`, `competitor_name`, and `amount_raw`. Additional columns are tolerated. Header matching trims whitespace, ignores case, and treats spaces and underscores equivalently. Alias-only headers such as `qty` or `price` do not satisfy the canonical template requirement.

CSV and Excel files are parsed locally before extraction. They must contain a header and at least one non-empty data row. PDFs are signature-checked locally; their extracted headers and rows are validated from the AI response.

## 4. What happens during an upload

### Before the AI call

1. CEOPRO validates the file type, size, signature, and template compatibility.
2. It checks the tenant's remaining `document_extraction` usage and document-storage capacity.
3. If any preflight check fails, extraction stops. No data source, ingestion job, staging row, or usage charge is created.

### While extracting

1. CEOPRO calls `extract_file` synchronously through `src/integrations/ai`.
2. CEOPRO validates the response shape, template mode, row outcomes, required typed fields, and that at least one row was processed.
3. Empty results, non-canonical headers, partial or failed rows, and rows missing required typed fields are rejected before persistence.

The AI response does not provide CEOPRO identifiers or a MinIO object key. Response data is not logged because extracted rows may contain customer contact information.

### After a valid extraction

CEOPRO creates an ingestion job and source record, then stores extracted rows in `import_staging_rows` with `validation_status = PENDING`. The upload response includes the CEOPRO job and source identifiers, an extraction summary, the staged row count, and `template_mode`. The response currently returns `null` for `is_template_compliant`, `data_loss_pct`, `promotion`, and `currency_resolution`; callers should not treat those fields as populated metrics.

Only after persistence succeeds does CEOPRO increment `document_extraction` usage. The upload request then returns; sales transactions are not written as part of the synchronous AI call.

## 5. Background import scenario

Run the Data Connections ingestion worker separately:

```bash
npm run worker:data-ingestion
```

The worker polls queued jobs every 10 seconds. Configure `INGESTION_WORKER_DATABASE_URL` with the least-privilege `ceopro_ingestion_worker` role. Migration `20261006120000_business_data_ingestion_worker` creates the role; provision its password outside migrations and store the connection URL in the worker's secret environment.

For each job, the worker revalidates staged sales fields, creates or reuses tenant products, inserts transactions, and marks successful rows `COMMITTED` with their transaction IDs. Invalid rows become `INVALID`. A database failure rolls back the job transaction and schedules a retry; jobs use a lease and bounded retries, and expired leases can be recovered.

Some rows can pass the extraction response checks and still fail the stricter persistence validation, such as quantity, price precision, currency, date, or discount checks. Such rows are marked invalid rather than imported.

## 6. Persistent sources and pending processing

`POST /data-connection/sources` creates source metadata; it does not validate external credentials or start a synchronization. Source creation consumes the applicable source capacity. The controller's pending-processing handler returns HTTP 501 because the current `extract_file` API processes each submitted file synchronously.

## 7. End-to-end verification checklist

Use this checklist when exercising the full flow with the AI team. Leave each item unchecked until it has been verified against a real run.

### Extraction and metrics

- [ ]
- [ ]
- [ ]

### Data delivered to other systems

- [ ]
- [ ]
- [ ]

## Related documentation

- [Data Connections module README](README.md)
- [Repository AI integration contract](../../../INTEGRATIONS.md#data-connection-ingestion)
