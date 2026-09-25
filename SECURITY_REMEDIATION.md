# Security Remediation and Refactor Report

## Scope

This project was remediated against the 19-page `Subscription_Feature_Architecture.pdf` supplied with the source archive. Existing route paths and HTTP methods were preserved. The work focused on the documented subscription, authentication, authorization, Stripe, promo-code, usage/entitlement, error-handling, configuration, and persistence risks, plus directly related defects found while tracing those flows.

## Remediation checklist

| Finding | Status | Implementation |
|---|---|---|
| Checkout request/provider field mismatch | Addressed | Checkout now consumes the existing public `payment_method` field; unsupported providers return a controlled API error rather than silently routing to Stripe. |
| Missing usage-period allocation/reset | Addressed | Usage rows are allocated idempotently from subscription synchronization/webhooks; billing-period usage is upserted per period and lifetime usage remains persistent. |
| Unprotected Stripe onboarding route | Addressed | Existing `POST /subscription/` path is now protected by authentication, tenant membership, and permission middleware. |
| Cross-tenant Stripe customer reuse | Addressed | Stripe customer lookup is tenant-aware and will not fall back to a user-level match when tenant context exists. |
| Payment transaction idempotency | Addressed | Added canonical invoice idempotency keys, upsert-based persistence, schema uniqueness, and a forward migration with safe existing-row backfill. |
| Promo `maxUsesPerUser` not enforced | Addressed | Tenant/user-scope redemption limits are checked and consumed under a serializable transaction. |
| Fixed promo currency mismatch/default | Addressed | Fixed-amount coupons require configured currency and linking a fixed coupon to a plan verifies Stripe coupon currency matches the plan currency. |
| Entitlement status inconsistency | Addressed | Access-granting subscription states are centralized and consistently treat `active` and `trialing` as entitled. |
| No automated checks | Addressed in source | Added focused unit tests plus route-contract and security-regression verification scripts. |
| No migration history | Partially addressable | Added a forward security-hardening migration. Historical production migrations cannot be reconstructed reliably from the supplied archive alone. |
| Hard-coded localhost CORS | Addressed | CORS origins are environment-driven through `CORS_ORIGINS`. |
| Startup mock JWT logging | Addressed | Startup import was removed; token generation is an explicit developer-only script. |
| Mixed/unstructured error handling | Addressed | Added centralized JSON 404/error middleware and shared API error helpers; sensitive exception details are not returned by the remediated flows. |
| Stripe plan price precision loss | Addressed | Removed integer rounding and centralized Stripe minor-unit conversion. |
| Stripe currency-unit assumptions | Addressed conservatively | Payment amount conversion follows Stripe's documented zero-decimal exceptions and two-decimal default. Unsupported currencies are still subject to Stripe/account capabilities at runtime. |
| Provider-specific JSON plan lookup | Addressed | Price-ID lookup no longer depends on Prisma `array_contains`; legacy direct IDs are checked first, then billing options are searched in application logic. |
| Missing explicit subscription/company relation | Addressed | Prisma relation and forward foreign-key migration are included. |
| Notification placeholders | Not invented | The archive does not contain a complete notification provider/workflow to safely implement trial/action-required/finalization-failed delivery without adding unrelated product behavior. Webhook processing remains retry-safe/error-aware. |

## Closely related defects fixed

- Promo validation validated `planId` but the controller read `plan`; it now uses the validated `planId` contract.
- Fixed-amount Stripe coupons are converted from major units to Stripe minor units exactly once.
- Lifetime feature usage is included independently of the current billing period, preventing lifetime quotas from disappearing after the first period.
- JWT verification explicitly restricts the accepted algorithm and validates the expected payload fields.
- Refresh tokens require a distinct refresh secret instead of silently falling back to the access-token secret.
- Tenant-scoped authorization verifies current active tenant membership before permissions are evaluated.
- Stripe webhook signatures are validated from the raw request body before JSON parsing.
- Express fingerprinting is reduced (`x-powered-by` disabled) and baseline response security headers are applied.
- Request body/upload limits are configurable.
- Error-code definitions were normalized while retaining a compatibility re-export for the old misspelled module path.

## Architecture/refactor changes

- Shared request/service types replace cross-service type coupling.
- Shared subscription status constants remove duplicated lifecycle logic.
- Shared currency utilities centralize Stripe amount conversion.
- Shared error-response helpers and global middleware reduce controller duplication.
- Environment access is centralized and required secrets fail closed.
- Stripe test-clock helpers reuse the application Stripe client rather than creating an independent client configuration.
- Sensitive/debug logging in remediated payment/plan paths was removed.
- Route names, paths, and methods were preserved; the verification script checks the expected source contract.

## Validation performed

- PDF rendered and reviewed page-by-page: 19 pages.
- TypeScript parser/syntax validation: 86 `.ts` files, 0 syntax errors.
- Route-contract regression verification: 31 checks passed.
- Security-regression verification: 14 checks passed.
- Focused executable unit smoke tests for currency/status logic: 4 passed, 0 failed.
- Error-code/definition parity: 50 codes / 50 definitions, no missing definitions.
- `npm run build` was attempted but the sandbox could not complete dependency installation, leaving the project-local `prisma` binary unavailable.
- `npm test` was attempted but the same installation limitation left the project-local `tsx` binary unavailable. The source-level checks above were run independently despite that environment limitation.

## Deployment verification still required

Before production rollout, run `npm ci`, `npm run validate`, and the new Prisma migration in an environment with the project's dependencies, PostgreSQL, and Stripe test credentials. Exercise checkout, onboarding, promo redemption, invoice retry, renewal, trialing, cancellation, plan-change, and multi-tenant customer-isolation flows against Stripe test mode. The supplied archive did not provide a live database or Stripe account, so those external integrations could not be conclusively executed here.
