# List Features For Plan

## 1. Endpoint Details

`GET /plans/:plan_id/features`

## 2. Mental Model

Shows the entitlement grants and quota limits attached to a plan, supporting catalog administration and plan comparison.

## 3. Technical Decisions

The plan UUID is validated and tenant/permission checks run before the controller. The plan-feature service reads the association through its repository rather than embedding Prisma access in the controller.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_catalog`.
- Path: `plan_id: string<uuid>`.
- Query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Plan features retrieved successfully",
  "data": [
    {
      "plan_id": "<uuid>",
      "feature_id": "<uuid>",
      "limit_value": 100,
      "feature": { "feature_code": "ai_pricing", "type": "limit" }
    }
  ]
}
```

### Errors

`500 INTERNAL_SERVER_ERROR`: `An unexpected error occurred`; validation/security failures use `400`, `401`, or `403` common envelopes.
