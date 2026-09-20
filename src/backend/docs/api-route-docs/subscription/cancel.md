# Cancel Current Subscription

## 1. Endpoint Details

`PATCH /subscription/current/cancel`

## 2. Mental Model

Schedules the tenant's active subscription to end at the current billing period, preserving service during the paid term while preventing the next renewal.

## 3. Technical Decisions

The route uses tenant context from JWT, requires `manage_catalog`, checks local state before calling Stripe, and delegates cancellation to `stripeService.updateSubscriptionCancellation(..., true, false)`. Repeated cancellation is rejected rather than issuing another provider mutation.

## 4. Inputs

- Required header: `Authorization: Bearer <JWT>` with `tenant_id`.
- Required permission: `manage_catalog` or `all`.
- Path/query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Subscription cancellation scheduled successfully",
  "data": null
}
```

### Errors

`404 SUBSCRIPTION_NOT_FOUND`: `Subscription not found`.

`400 SUBSCRIPTION_ALREADY_CANCELED`: `Subscription is already scheduled for cancellation.`

`400 PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND`: `Payment provider subscription ID is missing.`

Authentication/authorization failures use `401 INVALID_AUTH_HEADER`/`INVALID_TOKEN`, `400 INVALID_REQUEST`, or `403 FORBIDDEN`.
