# Billing & Subscription Tests

This domain contains CEOPRO tests for plan pricing, checkout, custom plans, Stripe integration, subscription state transitions, and production-plan bootstrap safety.

## Subfolders

| Folder | Purpose | External dependencies |
| --- | --- | --- |
| `core/` | Fast billing/subscription validation and pure policy tests | None |
| `custom-plan/` | Scenarios 01–11: custom-plan validation, pricing, quote lifecycle, security, schema, optional DB smoke | Mostly none; scenario 11 needs disposable DB |
| `custom-plan-stripe/` | Scenarios 12–19: real Stripe TEST-mode custom-plan/provider flows | Disposable DB + Stripe test key |
| `subscription-lifecycle/` | Scenarios 20–26: status, renewals, trials, cancellation, plan changes, webhook reliability, payment recovery | Disposable DB + Stripe test key |
| `production-plans/` | Scenarios 27–33: standard plans and production bootstrap safety | Disposable DB + Stripe test key for provider scenarios |

The numeric scenario order is intentionally continuous from `01` through `33`.
