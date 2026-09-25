# Process Pending Extraction

> **Latest codebase sync (2026-09-24):** Verified against `CEOPRO_Entitlements_CustomPlan_UX_Fixed.zip` with the later `CEOPRO_CustomPlan_Card_Alignment_Icons_Fix.zip` frontend overlay. Where older historical notes conflict with a “current behavior” section, the latest-codebase section is authoritative.

## 1. Endpoint Details

`POST /features/extraction/process-pending`

**Runtime status:** Mounted by `modules/features/index.ts` under `/features`; authenticated tenant context is required.

## 2. Mental Model

Triggers the current pending-extraction stub for the tenant. It requires feature access but does not itself consume quota; the upload endpoint is the authoritative charging point in this archive.

## 3. Technical Decisions

The optional limit is validated at the router, but the current controller is a stub: it returns immediately and does not call an extraction worker or increment usage. The route is gated by `requireFeatureAccess("document_extraction")`; the current controller does not process or charge additional documents.

## 4. Inputs

- Query: optional `limit: positive integer`.
- Header: `Authorization: Bearer <JWT>` with tenant context.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Process pending successful",
  "data": { "message": "Pending extraction triggered" }
}
```

### Errors

The current controller defines no route-specific errors; query validation and entitlement middleware may reject requests. If future worker integration fails, the controller will need an explicit error contract.
