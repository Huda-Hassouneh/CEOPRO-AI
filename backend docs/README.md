# CEO PRO API Route Documentation

> **Latest codebase sync (2026-09-24):** Verified against the latest full-stack code snapshot used for this task. This index corrects older permission docs and adds the previously missing Custom Plan and platform-admin routes.

**Base URL:** backend server origin. `src/app.ts` mounts `/platform-admin`, `/subscription`, `/features`/plan-feature routes, and `/stripe/webhooks`.

## Authentication and Authorization Model

### Tenant Routes

Authenticated tenant routes require `Authorization: Bearer <JWT>`. The JWT must contain `user.id` and `tenant_id`, and `requireTenant` verifies an active `TenantUser` membership.

`requirePermission(action)` allows the action when the active role's permissions JSON has either `all: true` or the named action.

### Platform-owner Routes

The latest code does **not** use a standalone `platform_role` JWT claim. Platform administration requires an active membership whose `roleKey` is exactly `owner`. `requirePlatformPermission(name)` then checks `permissions.all` or the named platform permission.

Because `platform-admin.routes.ts` uses `authenticateUser`, `requireTenant`, and `requirePlatformRole`, current `/platform-admin/*` calls need a valid `tenant_id` and active owner membership.

Platform permissions used by billing routes:

- `billing.read`
- `billing.manage`
- `billing.pricing.manage`
- `subscriptions.read`

## Feature Module Architecture (Strict Layering)

All AI and Feature modules (`rag`, `sentiment`, `extraction`, `pricing`) follow a strict **Route → Controller → Service → Repository** architecture to ensure scalability, separation of concerns, and testability.

### Route Layer (`features.route.ts`)

Responsible strictly for HTTP and middleware concerns:

- Defines Express routes and HTTP methods.
- Configures `multer` middleware for `FormData` and file uploads.
- Applies authentication through `authenticateUser`.
- Applies subscription entitlement gating through `requireEntitlement`.
- Must not contain business logic.

### Controller Layer (`*.controller.ts`)

Controllers are intentionally lightweight and responsible only for translating HTTP requests into service calls and formatting responses.

Responsibilities:

- Extract `req.params`.
- Extract `req.query`.
- Extract `req.body`.
- Invoke the appropriate service method.
- Format `successResponse` or `errorResponse`.
- Must contain **zero business logic**.

### Service Layer (`*.service.ts`)

The service layer is the core business engine of each feature module.

Responsibilities include:

- Calculating and enforcing usage quotas.
- Calling external AI/Python APIs.
- Implementing fallback logic.
- Executing business rules and feature-specific workflows.
- Throwing structured error codes for the controller to translate into HTTP responses.

Services must remain independent of Express-specific request/response handling.

### Repository Layer (`*.repo.ts`)

The repository layer exclusively handles database access through Prisma.

Examples include:

- `usage.repo.ts` for usage and quota tracking.
- `rag.repo.ts` for RAG document and chunk lookups.

Repositories:

- Must contain only persistence/data-access logic.
- Must not contain HTTP logic.
- Must not import or depend on Express request/response types.
- Must not format HTTP responses or determine HTTP status codes.

## Route Groups

### Health / Bootstrap / Stripe

- [Health check](health/health-check.md)
- [Stripe webhook](subscription/stripe-webhooks.md)
- [Stripe onboarding/bootstrap](subscription/stripe-onboarding.md)

### Tenant Subscription

- [Current subscription](subscription/current.md)
- [Cancel subscription](subscription/cancel.md)
- [Undo cancellation](subscription/cancel-undo.md)
- [Checkout](subscription/checkout.md)
- [Change plan](subscription/change-plan.md)
- [Invoices](subscription/invoices.md)
- [Usage dashboard](usage/dashboard.md)

### Public / Platform-managed Catalog

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

### Self-service and Manual Custom Plans

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

### Platform Owner

- [Platform principal](platform-admin/me.md)
- [Platform billing API](platform-admin/billing.md)

### AI Feature-operation Routes

The tenant feature-operation router is mounted under `/features`. Consuming operations use `requireEntitlement(featureCode)` while read-only summaries use `requireFeatureAccess(featureCode)`.

- [Pricing recommendation](ai-features/pricing-recommend.md)
- [Sentiment analyze pending](ai-features/sentiment-analyze-pending.md)
- [Sentiment summary](ai-features/sentiment-summary.md)
- [MPI summary](ai-features/mpi-summary.md)
- [RAG query](ai-features/rag-query.md)
- [Extraction upload](ai-features/extraction-upload.md)
- [Extraction process pending](ai-features/extraction-process-pending.md)

## Current Plan-change Rule

Plan changes compare actual `PlanFeature` entitlements first:

```text
gains only       -> upgrade   -> immediate timing may be used
losses only      -> downgrade -> period_end
gains + losses   -> mixed     -> period_end
no differences  -> equivalent
```

`limit_value=null` means unlimited/enabled.

- Moving from **limited → unlimited** is a gain.
- Moving from **unlimited → limited** is a loss.
- Price, tier, and billing-duration logic is retained only as a compatibility fallback when entitlement comparison does not provide a meaningful direction.

For a scheduled change, the current subscription remains on `planId`, the future target is stored in `scheduledPlanId`, and `currentPeriodEnd` is the scheduled effective date.
