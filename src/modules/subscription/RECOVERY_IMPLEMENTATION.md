# CEOPRO Subscription Payment Recovery

## Purpose

Recover an existing subscription in `pending`, `past_due`, `payment_failed`, or `paused` without creating a duplicate Stripe subscription.

## Endpoint

```http
POST /subscription/current/recovery
```

Access requirements:

- authenticated user;
- active tenant membership;
- `manage_billing` permission.

No request body is required. The backend derives the tenant, current subscription, Stripe customer, and Stripe subscription from server-side state.

## Recovery behavior

- `pending` + open hosted invoice -> `complete_payment`
- `past_due` / `payment_failed` + open hosted invoice -> `resolve_payment`
- `paused` -> `manage_billing` through Stripe Customer Portal
- missing/unusable hosted invoice -> Stripe Customer Portal fallback
- `active`, `trialing`, terminal statuses -> recovery rejected with `INVALID_SUBSCRIPTION_STATUS`

Example success:

```json
{
  "success": true,
  "message": "Subscription recovery session created successfully",
  "data": {
    "type": "resolve_payment",
    "url": "https://invoice.stripe.com/..."
  }
}
```

Possible `type` values:

```text
complete_payment
resolve_payment
manage_billing
```

## Architecture

```text
POST /subscription/current/recovery
            |
            v
subscriptions.route.ts
            |
            v
subscription.controller.ts
            |
            v
subscription.service.ts
       /             \
      v               v
existing          Stripe client
subscription      (provider transport)
repo
```

No new repository is created. `getCurrentSubscriptionByTenant()` is reused.

No Prisma schema change or migration is required.

## Stripe authority

The recovery endpoint never marks the local subscription `active`. After the customer resolves payment, Stripe webhooks remain responsible for synchronizing the final subscription state and restoring access.

## Tenant safety

The service:

- never accepts Stripe customer/subscription IDs from the browser;
- obtains them from the tenant-scoped local subscription;
- rejects conflicting Stripe `tenantId` metadata;
- rejects a mismatch between the stored Stripe customer and the customer attached to the Stripe subscription.

## Return URL

Optional environment variable:

```env
SUBSCRIPTION_RECOVERY_RETURN_URL=https://your-app.example.com/billing
```

If it is not configured, the service derives `/billing` from the origin of `SUCCESS_SUBSCRIPTION_URL`. Local fallback is `http://localhost:5173/billing`.

## Changed files

```text
src/modules/subscription/route/subscriptions.route.ts
src/modules/subscription/controller/subscription.controller.ts
src/modules/subscription/service/subscription.service.ts
src/modules/subscription/client/payment-providers/stripe/stripe.client.ts
src/modules/subscription/types/stripe-provider.types.ts
src/modules/subscription/types/subscription-recovery.types.ts   (new)
scripts/verify-route-contract.mjs
tests/subscription-recovery-policy.test.ts                       (new)
```

## Intentionally unchanged

```text
src/modules/subscription/repo/subscription.repo.ts
prisma/schema.prisma
prisma/migrations/*
legacy duplicate subscription folders/files
```

This follows the refactored feature-domain architecture: Route -> Controller -> Service -> existing Repo / Stripe Client.
