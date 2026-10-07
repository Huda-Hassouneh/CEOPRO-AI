# Custom Plan Stripe E2E — Scenarios 12–19

Provider-connected custom-plan tests. These use **real Stripe TEST-mode objects** and a disposable migrated database. The runner refuses non-`sk_test_` Stripe keys.

`CUSTOM_PLAN_STRIPE_TESTING.md` contains full setup and cleanup guidance.

| Scenario | What it tests |
| --- | --- |
| `12` | Stripe Checkout session matches accepted custom-plan amount, tenant metadata, subscription mode, and server-owned Stripe Price. |
| `13` | Raw-body webhook signature verification and duplicate-event idempotency ledger behavior. |
| `14` | Successful Stripe subscription synchronizes local active access and exactly one metered usage allocation. |
| `15` | Declined initial payment stays non-entitled, records failure, then recovers to active after payment repair. |
| `16` | Stripe Test Clock renewal advances the billing period and creates one new period allocation without overwriting the old one. |
| `17` | CEOPRO promo mapping reaches Stripe and changes the provider checkout amount correctly. |
| `18` | Automatic custom-plan golden path: configuration → accepted quote/plan → Checkout → subscription → webhook → entitlement. |
| `19` | Manual-review golden path: calculate → approve → send → accept → Checkout → subscription → webhook → entitlement. |
| `_stripe-e2e-helpers.ts` | Shared Stripe/DB fixture creation, safety checks, synchronization, cleanup, and polling helpers. |

## Safety

Never run this suite with a live Stripe secret or a development/production database.
