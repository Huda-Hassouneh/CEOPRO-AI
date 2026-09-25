# CEO PRO API Route Documentation

> **Latest codebase sync (2026-09-24):** Verified against the latest full-stack code snapshot used for this task. This index corrects older permission docs and adds the previously missing Custom Plan and platform-admin routes.

Base URL: backend server origin. `src/app.ts` mounts `/platform-admin`, `/subscription`, `/features`/plan-feature routes, and `/stripe/webhooks`.

## Authentication and authorization model

### Tenant routes

Authenticated tenant routes require `Authorization: Bearer <JWT>`. The JWT must contain `user.id` and `tenant_id`, and `requireTenant` verifies an active `TenantUser` membership.

`requirePermission(action)` allows the action when the active role's permissions JSON has either `all: true` or the named action.

### Platform-owner routes

The latest code does **not** use a standalone `platform_role` JWT claim. Platform administration requires an active membership whose `roleKey` is exactly `owner`. `requirePlatformPermission(name)` then checks `permissions.all` or the named platform permission.

Because `platform-admin.routes.ts` uses `authenticateUser, requireTenant, requirePlatformRole`, current `/platform-admin/*` calls need a valid `tenant_id` and active owner membership.

Platform permissions used by billing routes:

- `billing.read`
- `billing.manage`
- `billing.pricing.manage`
- `subscriptions.read`

## Route groups

### Health / bootstrap / Stripe

- [Health check](health/health-check.md)
- [Stripe webhook](subscription/stripe-webhooks.md)
- [Stripe onboarding/bootstrap](subscription/stripe-onboarding.md)

### Tenant subscription

- [Current subscription](subscription/current.md)
- [Cancel subscription](subscription/cancel.md)
- [Undo cancellation](subscription/cancel-undo.md)
- [Checkout](subscription/checkout.md)
- [Change plan](subscription/change-plan.md)
- [Invoices](subscription/invoices.md)
- [Usage dashboard](usage/dashboard.md)

### Public / platform-managed catalog

- [List plans](plans/list.md)
- [Create plan](plans/create.md)
- [Update plan](plans/update.md)
- [List features](features/list.md)
- [Get feature](features/get.md)
- [Create feature](features/create.md)
- [Update feature](features/update.md)
- [List plan features](plan-features/list.md)
- [Link plan feature](plan-features/link.md)
- [Update plan feature limits](plan-features/update-limits.md)
- [List promo codes](promo-codes/list.md)
- [Create promo code](promo-codes/create.md)
- [Validate promo code](promo-codes/validate.md)
- [Update promo code](promo-codes/update.md)
- [Link promo code to plan](promo-codes/link-plan.md)

### Self-service and manual Custom Plans

- [Configurator](custom-plans/configurator.md)
- [Preview](custom-plans/preview.md)
- [Manual review request](custom-plans/manual-review.md)
- [Instant checkout / existing-subscription change](custom-plans/checkout.md)
- [Tenant Custom Plan list](custom-plans/list.md)
- [Customer-safe manual offer](custom-plans/offer.md)
- [Accept manual offer](custom-plans/accept.md)
- [Legacy/internal quote management](custom-plans/quotes.md)
- [Pricing policy](custom-plans/pricing-policy.md)
- [Vendor rates](custom-plans/vendor-rates.md)

### Platform owner

- [Platform principal](platform-admin/me.md)
- [Platform billing API](platform-admin/billing.md)

### AI feature-operation routes

The tenant feature-operation router is mounted under `/features`. Consuming operations use `requireEntitlement(featureCode)` while read-only summaries use `requireFeatureAccess(featureCode)`.

- [Pricing recommendation](ai-features/pricing-recommend.md)
- [Sentiment analyze pending](ai-features/sentiment-analyze-pending.md)
- [Sentiment summary](ai-features/sentiment-summary.md)
- [MPI summary](ai-features/mpi-summary.md)
- [RAG query](ai-features/rag-query.md)
- [Extraction upload](ai-features/extraction-upload.md)
- [Extraction process pending](ai-features/extraction-process-pending.md)

## Current plan-change rule

Plan changes compare actual `PlanFeature` entitlements first:

```text
gains only        -> upgrade   -> immediate timing may be used
losses only       -> downgrade -> period_end
gains + losses    -> mixed     -> period_end
no differences    -> equivalent
```

`limit_value=null` means unlimited/enabled. Moving limited -> unlimited is a gain; unlimited -> limited is a loss. Price/tier/billing-duration logic is retained only as a compatibility fallback when entitlement comparison does not provide a meaningful direction.

For a scheduled change, the current subscription remains on `planId`, the future target is stored in `scheduledPlanId`, and `currentPeriodEnd` is the scheduled effective date.
