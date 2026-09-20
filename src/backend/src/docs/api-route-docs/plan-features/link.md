# Link Feature To Plan

## 1. Endpoint Details

`POST /plans/:plan_id/features`

## 2. Mental Model

Adds an entitlement to a plan, optionally setting the numeric quota used by metered features.

## 3. Technical Decisions

The controller checks the feature type before writing: boolean features must use `limit_value: null`. It also verifies the plan, then the service checks duplicate associations and the repository creates the join record.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`; permission `manage_catalog`.
- Path: `plan_id: string<uuid>`.
- JSON body: `{ "feature_id": "<uuid>", "limit_value": 100 }`; `limit_value` is optional, integer >= 0, or `null` for unlimited/boolean access. Unknown fields are rejected.

## 5. Outputs

### Success

`201 Created`

```json
{
  "success": true,
  "message": "Feature linked to plan successfully",
  "data": { "plan_id": "<uuid>", "feature_id": "<uuid>", "limit_value": 100 }
}
```

### Errors

`400 INVALID_PARAMETER`: `A boolean feature cannot have a quota limit. Please set limit_value to null.`

`404 PLAN_NOT_FOUND`: `Plan not found`.

`409 RESOURCE_ALREADY_EXISTS`: `This feature is already linked to this plan.`

Other validation/security/database errors use common envelopes.
