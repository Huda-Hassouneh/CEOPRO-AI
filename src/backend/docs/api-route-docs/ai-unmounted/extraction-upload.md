# AI Document Extraction Upload (Currently Unmounted)

## 1. Endpoint Details

`POST /extraction/upload`

**Runtime status:** Defined but not mounted by `app.ts`.

## 2. Mental Model

Would accept a document, forward it to the extraction service, return extraction quality/job metadata, and increment the tenant's `document_extraction` usage.

## 3. Technical Decisions

Multer stores the upload in memory, then the controller rebuilds a multipart request with `FormData`/`Blob` for the AI service. This route uses `requireEntitlement("document_extraction")` and increments usage only after a successful provider response.

## 4. Inputs

- Multipart form field: required `file` (single uploaded file).
- Body: `multipart/form-data`, not JSON. No path/query parameters; no local auth header requirement while parent auth is commented out.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Document extraction successful", "data": { "job_id": "...", "template_mode": "...", "is_template_compliant": true, "rows_processed": 10, "rows_partial": 0, "rows_failed": 0, "data_loss_pct": 0, "header_coverage_ratio": 1, "row_outcomes": [], "promotion": {}, "currency_resolution": {} } }`.

### Errors

`400 INVALID_REQUEST` when no file is supplied; `502 EXTERNAL_SERVICE_ERROR` when extraction fails; `500 INTERNAL_SERVER_ERROR` for unexpected errors.
