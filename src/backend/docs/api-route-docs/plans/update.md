# Update Subscription Plan

## 1. Endpoint Details

`PATCH /subscription/plans/:id`

## 2. Mental Model

Updates an existing catalog plan for administrative pricing and availability management.

## 3. Technical Decisions

The route is tenant- and permission-protected, validates the UUID path parameter and a non-empty partial plan body, then delegates persistence to `updatePlansService` and the plans repository. Unlike plan creation, this handler returns the updated local record and does not itself describe Stripe price recreation in the controller contract.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `all`.
- Path: `id: string<uuid>`.
- JSON body: any non-empty subset of plan fields from create: `name`, `name_ar`, `tierLevel`, `description`, `description_ar`, `price`, `currency`, `billingIntervalValue`, `billingIntervalUnit`, `trialPeriodValue`, `trialPeriodUnit`, `isActive`, `billingOptions`.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Plan updated successfully",
  "data": { "id": "<uuid>", "name": "Pro" }
}
```

### Errors

`400 VALIDATION_ERROR` for invalid UUID/body; `404 PLAN_NOT_FOUND` when the service cannot find the plan; other service errors use their defined code/status and the common envelope. Security failures use `401 INVALID_AUTH_HEADER`/`INVALID_TOKEN`, `400 INVALID_REQUEST`, or `403 FORBIDDEN`.
