# Change Subscription Plan

## 1. Endpoint Details

`PATCH /subscription/current/plan`

## 2. Mental Model

Changes the tenant's active Stripe subscription to another plan/billing option. Upgrades are applied immediately; downgrades are scheduled for the end of the current billing cycle.

## 3. Technical Decisions

The service compares tier and billing duration to classify upgrade vs. downgrade, retrieves the current Stripe subscription and item, updates the provider price, then persists pending downgrade fields in Prisma. It explicitly handles idempotent/repeated requests with `ALREADY_ACTIVE_PLAN` and `ALREADY_SCHEDULED_PLAN`, and prevents replacing a current plan while a downgrade remains scheduled.

## 4. Inputs

- Header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Permission: `manage_catalog` or `all`.
- JSON body: `{ "planId": "<uuid>", "billing_period": "monthly" }`.
- `planId: string<uuid>` and `billing_period: "monthly" | "three-months" | "six-months" | "yearly"` are required. No path/query parameters.

## 5. Outputs

### Success

`200 OK` upgrade:

```json
{
  "success": true,
  "message": "Subscription updated successfully.",
  "data": null
}
```

Downgrade success uses `Subscription updated successfully.` or `Downgrade scheduled for the end of the current billing cycle.` depending on service result.

### Errors

`400 VALIDATION_ERROR`: `planId and billing_period are required.`

`404 PLAN_NOT_FOUND` or `SUBSCRIPTION_NOT_FOUND`.

`400 INVALID_BILLING_PERIOD`: `Billing period '<period>' is not valid for this plan.`

`400 ALREADY_ACTIVE_PLAN`, `ALREADY_SCHEDULED_PLAN`, or `CANCEL_DOWNGRADE_REQUIRED` with the exact messages defined in `errors/error-defentions.ts`.

`502 PAYMENT_PROVIDER_ERROR` when Stripe update/retrieval fails. Auth/permission errors use the common envelopes.
