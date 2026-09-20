# Process Pending Extraction (Currently Unmounted)

## 1. Endpoint Details

`POST /extraction/process-pending`

**Runtime status:** Defined but not mounted by `app.ts`.

## 2. Mental Model

Would trigger processing of queued document-extraction work for the tenant and consume the `document_extraction` entitlement.

## 3. Technical Decisions

The optional limit is validated at the router, but the current controller is a stub: it returns immediately and does not call an extraction worker or increment usage. The route is still gated by `requireEntitlement("document_extraction")` in its source router.

## 4. Inputs

- Query: optional `limit: positive integer`.
- Body: none. No local header requirement while parent authentication is commented out.

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
