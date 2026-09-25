# AI Document Extraction Upload

> **Latest codebase sync (2026-09-24):** Verified against `CEOPRO_Entitlements_CustomPlan_UX_Fixed.zip` with the later `CEOPRO_CustomPlan_Card_Alignment_Icons_Fix.zip` frontend overlay. Where older historical notes conflict with a “current behavior” section, the latest-codebase section is authoritative.

## 1. Endpoint Details

`POST /features/extraction/upload`

**Runtime status:** Mounted by `modules/features/index.ts` under `/features`; authenticated tenant context is required.

## 2. Mental Model

Accepts a document, forward it to the extraction service, return extraction quality/job metadata, and increment the tenant's `document_extraction` usage.

## 3. Technical Decisions

Multer stores the upload in memory, then the controller rebuilds a multipart request with `FormData`/`Blob` for the AI service. This route uses `requireEntitlement("document_extraction")` and increments usage only after a successful provider response.

## 4. Inputs

- Multipart form field: required `file` (single uploaded file).
- Header: `Authorization: Bearer <JWT>` with tenant context.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Document extraction successful", "data": { "job_id": "...", "template_mode": "...", "is_template_compliant": true, "rows_processed": 10, "rows_partial": 0, "rows_failed": 0, "data_loss_pct": 0, "header_coverage_ratio": 1, "row_outcomes": [], "promotion": {}, "currency_resolution": {} } }`.

### Errors

`400 INVALID_REQUEST` when no file is supplied; `502 EXTERNAL_SERVICE_ERROR` when extraction fails; `500 INTERNAL_SERVER_ERROR` for unexpected errors.
