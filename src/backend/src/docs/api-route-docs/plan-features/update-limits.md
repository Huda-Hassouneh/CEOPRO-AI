# Update Plan Feature Limits

## 1. Endpoint Details

`PATCH /plans/:plan_id/features/:feature_id`

## 2. Mental Model

Changes the quota associated with one feature-plan entitlement without replacing the association.

## 3. Technical Decisions

The controller re-checks boolean semantics before the service locates and updates the join record. `limit_value` is required in the body, and `null` is the explicit representation for unlimited access.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`; permission `manage_catalog`.
- Path: `plan_id: string<uuid>`, `feature_id: string<uuid>`.
- JSON body: `{ "limit_value": 100 }`; integer >= 0 or `null`; strict object.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Limits updated successfully",
  "data": { "plan_id": "<uuid>", "feature_id": "<uuid>", "limit_value": 100 }
}
```

### Errors

`400 INVALID_PARAMETER`: boolean feature must use `null`.

`404 RESOURCE_NOT_FOUND`: `Feature link not found for this plan.`

`400 VALIDATION_ERROR` or `500 INTERNAL_SERVER_ERROR`; common security errors also apply.
