# CEO PRO API Route Documentation

Base URL: the backend server origin. Routes below are mounted directly by `src/app.ts`.

All authenticated routes use `Authorization: Bearer <JWT>`. The JWT must include `tenant_id`; permission-protected routes also require the named permission or the `all` override. Errors use `{ "success": false, "error": { "code", "message", "statusCode" } }` unless noted.

## Registered route files

### Health

- [Health check](health/health-check.md)

### Subscription

- [Stripe webhook](subscription/stripe-webhooks.md)
- [Stripe onboarding](subscription/stripe-onboarding.md)
- [Current subscription](subscription/current.md)
- [Cancel subscription](subscription/cancel.md)
- [Undo cancellation](subscription/cancel-undo.md)
- [Checkout](subscription/checkout.md)
- [Change plan](subscription/change-plan.md)
- [Invoices](subscription/invoices.md)

### Plans

- [List plans](plans/list.md)
- [Create plan](plans/create.md)
- [Update plan](plans/update.md)

### Promo codes

- [List promo codes](promo-codes/list.md)
- [Create promo code](promo-codes/create.md)
- [Validate promo code](promo-codes/validate.md)
- [Update promo code](promo-codes/update.md)
- [Link promo code to plan](promo-codes/link-plan.md)

### Features

- [List features](features/list.md)
- [Get feature](features/get.md)
- [Create feature](features/create.md)
- [Update feature](features/update.md)

### Plan features and usage

- [List plan features](plan-features/list.md)
- [Link plan feature](plan-features/link.md)
- [Update plan feature limits](plan-features/update-limits.md)
- [Usage dashboard](usage/dashboard.md)

## Source routes currently not mounted

`modules/features/routes/features.route.ts` defines AI routes, but `modules/features/index.ts` does not import or mount that router. They are documented separately in [unmounted AI routes](ai-unmounted/); requests to them currently fall through to the app's 404 handling rather than reaching these controllers.
