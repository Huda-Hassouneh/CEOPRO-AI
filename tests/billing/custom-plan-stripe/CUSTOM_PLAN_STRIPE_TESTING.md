# CEOPRO Custom Plan — Stripe Test-Mode E2E

This suite is the provider-connected layer that runs after the core custom-plan tests and the disposable PostgreSQL integration test.

## Safety

The runner refuses to start unless `STRIPE_SECRET_KEY` begins with `sk_test_`. It creates Stripe **test-mode** Products, Prices, Customers, Subscriptions, Coupons, Checkout Sessions and Test Clocks. No live Stripe objects or real charges are allowed.

Use only the disposable migrated database already used by `npm run test:custom-plan:db`.

## Test groups

1. `12` — creates a real Stripe test Checkout Session and verifies mode, tenant metadata, USD price and provider amount.
2. `13` — starts CEOPRO in-process, verifies the real raw-body webhook route rejects invalid signatures and deduplicates the same signed event.
3. `14` — creates a real paid Stripe test subscription, feeds the real Subscription object through CEOPRO's webhook service, and verifies local subscription + metered allocation.
4. `15` — creates an incomplete subscription with a declining Stripe test payment method, verifies no entitlement, records the failed invoice, then replaces the payment method and verifies recovery to active.
5. `16` — uses a Stripe Test Clock to cross a renewal boundary and verifies CEOPRO creates exactly one new billing-period usage allocation while preserving the previous period.
6. `17` — creates a real Stripe coupon plus local CEOPRO promo mapping and verifies the Checkout Session provider amount includes the discount.
7. `18` — automatic custom-plan golden path: configuration → automatic quote → accepted plan → Stripe Checkout → test subscription → webhook sync → entitlement allocation.
8. `19` — manual-review golden path: create → calculate → approve → send → accept → Stripe Checkout → test subscription → webhook sync → entitlement allocation.

The golden-path tests programmatically create the provider subscription after verifying CEOPRO's hosted Checkout Session. They do not automate Stripe's hosted payment webpage. That browser-only surface is intentionally kept separate because it is UI/selector-sensitive; the backend/provider/payment/webhook path is still exercised with real Stripe test objects.

## Environment

Keep your disposable DB variables from the previous step:

```powershell
$env:CUSTOM_PLAN_TEST_DATABASE_URL="postgresql://postgres:YOUR_REAL_PASSWORD@localhost:5433/CEOPRO_CUSTOM_PLAN_TEST"
$env:DATABASE_URL=$env:CUSTOM_PLAN_TEST_DATABASE_URL
```

Set your Stripe **test** secret key:

```powershell
$env:STRIPE_SECRET_KEY="sk_test_..."
```

The suite generates its own local webhook-signature secret for the in-process signature test, so your Dashboard webhook secret is not required for that test.

Optional overrides if your Stripe account uses different test PaymentMethod fixtures:

```powershell
$env:STRIPE_E2E_VALID_PAYMENT_METHOD="pm_card_visa"
$env:STRIPE_E2E_DECLINED_PAYMENT_METHOD="pm_card_chargeDeclined"
```

## Before running

The disposable database must already contain all migrations:

```powershell
$env:DATABASE_URL=$env:CUSTOM_PLAN_TEST_DATABASE_URL
npm run prisma:migrate:test
npm run prisma:generate
```

Do not point `CUSTOM_PLAN_TEST_DATABASE_URL` at CEOPROTEST3 or production.

## Run Stripe tests

```powershell
npm run test:custom-plan:stripe
```

Expected high-level output:

```text
============================================================
 CEOPRO Custom Plan Stripe TEST-Mode E2E Suite
============================================================
Safety: sk_test_ key required; live keys are refused
Groups: 8
...
PASS GROUP: 12 - Stripe checkout provider object
PASS GROUP: 13 - Webhook signature + idempotency
...
Passed groups : 8/8
Failed groups : 0
Result: PASSED.
```

## Full custom-plan release run

Once the Stripe suite passes:

```powershell
npm run test:custom-plan:release
```

That runs, in order:

```text
core custom-plan contracts/tests
→ disposable PostgreSQL integration
→ real Stripe test-mode E2E
```

## Important notes

- Stripe test objects are cleaned up where Stripe allows it. Created Prices are deactivated and test Products are archived because recurring Prices are normally immutable.
- Test Clock processing is asynchronous. Group 16 polls until Stripe reports the clock as ready and the subscription period actually advances.
- A failed group can leave test-mode Stripe objects behind if the remote provider fails during cleanup. They are tagged/named with `CEOPRO` / `ceoproTestRun` so they are recognizable in Stripe test mode.
- These tests intentionally use the CEOPRO webhook business service for subscription lifecycle assertions and separately test the HTTP signature/raw-body route in group 13.
- This suite never requires a production webhook endpoint or a publicly reachable local server.

## Recommended release order

```powershell
npm run prisma:validate
npm run build
npm run test:custom-plan
npm run test:custom-plan:db
npm run test:custom-plan:stripe
```

After these pass, only a small manual/browser smoke check of the hosted Stripe Checkout UI remains.
