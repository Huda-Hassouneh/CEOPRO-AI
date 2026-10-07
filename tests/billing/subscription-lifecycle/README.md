# Subscription Lifecycle — Scenarios 20–26

End-to-end subscription-state tests against a disposable PostgreSQL database and Stripe TEST mode. They validate CEOPRO's provider-authoritative lifecycle and entitlement behavior.

`SUBSCRIPTION_LIFECYCLE_TESTING.md` contains the full environment and execution instructions.

| Scenario | What it tests |
| --- | --- |
| `20` | Stripe→CEOPRO status mapping, access-granting states, recoverable states, terminal states. |
| `21` | Billing-period renewal allocation reset: new period allocation is created once, previous/lifetime usage is preserved, duplicate processing is idempotent. |
| `22` | Trial access and trial→active transition; missing-payment-method pause behavior and access removal. |
| `23` | Cancel-at-period-end, undo cancellation, and final cancellation while keeping Stripe authoritative. |
| `24` | Immediate entitlement-only upgrades, scheduled entitlement-loss downgrades, trial preservation, cancellation of scheduled changes. |
| `25` | Out-of-order webhook convergence, duplicate events, failed-event retryability, and recovery after dependencies are repaired. |
| `26` | Initial-payment and renewal-payment recovery, duplicate checkout prevention, access blocking during failure, and allocation creation only after successful recovery. |
| `_subscription-lifecycle-helpers.ts` | Shared disposable DB / Stripe fixture, synchronization, polling, and cleanup helpers. |

## Safety

Requires a database URL containing `test` and a Stripe secret beginning with `sk_test_`. Do not run a separate Stripe listener against the same disposable DB while the suite drives webhook services directly.
