# Get Feature

## 1. Endpoint Details

`GET /features/:id`

## 2. Mental Model

Retrieves one entitlement definition for catalog administration or plan-association workflows.

## 3. Technical Decisions

UUID validation happens before the controller. The service performs a repository lookup and converts absence into `RESOURCE_NOT_FOUND`; the controller maps that domain condition to a stable 404 response.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_catalog`.
- Path: `id: string<uuid>`.
- Query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Feature retrieved successfully",
  "data": { "id": "<uuid>", "feature_code": "ai_pricing", "type": "limit" }
}
```

### Errors

`404 RESOURCE_NOT_FOUND`: `Resource not found` with detail `The requested feature could not be found.`

Invalid UUID, auth, tenant, permission, and unexpected failures use `400`, `401`, `403`, or `500` common envelopes.
