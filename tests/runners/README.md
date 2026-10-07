# Test Suite Runners

Ordered runners for the larger numbered billing suites. They spawn Node's test runner with `tsx` and stop with a non-zero exit code when any group fails.

| Runner | Runs | Safety behavior |
| --- | --- | --- |
| `run-custom-plan-tests.mjs` | Core custom-plan contract/scenario groups and optional DB smoke | Core mode is external-service free; DB mode requires configured disposable test DB. |
| `run-custom-plan-stripe-tests.mjs` | Billing scenarios 12–19 | Requires disposable test DB and `STRIPE_SECRET_KEY=sk_test_...`; refuses live keys. |
| `run-subscription-lifecycle-tests.mjs` | Billing scenarios 20–26 | Requires disposable test DB + Stripe test key; designed to drive webhook services directly. |
| `run-production-plan-tests.mjs` | Billing scenarios 27–33 | Requires disposable test DB + Stripe test key; verifies standard plans and bootstrap safety. |

All hard-coded test paths in these runners point to the reorganized `tests/billing/...` locations.
