# Undo Subscription Cancellation

## 1. Endpoint Details

`PATCH /subscription/current/cancel/undo`

## 2. Mental Model

Removes a pending end-of-period cancellation so the tenant's active subscription renews normally.

## 3. Technical Decisions

The route requires tenant-scoped authorization and checks the local cancellation flag before contacting Stripe. It calls the provider with cancellation disabled and does not accept a tenant ID in the body, preventing cross-tenant mutation.

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
  "message": "Subscription uncanceled successfully",
  "data": null
}
```

### Errors

`404 SUBSCRIPTION_NOT_FOUND`: `Subscription not found`.

`400 SUBSCRIPTION_NOT_CANCELED`: `Subscription is already not scheduled for cancellation.`

`400 PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND`: `Payment provider subscription ID is missing.`

Authentication/authorization failures use the common `401`, `400 INVALID_REQUEST`, and `403 FORBIDDEN` envelopes.
