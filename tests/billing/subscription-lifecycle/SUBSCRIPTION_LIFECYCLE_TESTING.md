# CEOPRO Subscription Lifecycle Automated Tests

This suite exercises the real CEOPRO subscription lifecycle against a disposable PostgreSQL database and Stripe **test mode**.

It intentionally uses the application services/webhook handlers directly. The backend server and Stripe CLI listener are **not required**. In fact, stop `stripe listen` and stop any backend process pointing at the same disposable DB before running, otherwise real Stripe test events can be processed twice while the test suite is also driving the webhook service directly.

## What it covers

The runner executes seven ordered groups:

```text
20 Status + access contract
21 Billing-cycle reset
22 Trial lifecycle
23 Cancellation lifecycle
24 Plan-change lifecycle
25 Webhook reliability
26 Payment recovery
```

The scenarios verify:

- Stripe → CEOPRO status mapping.
- Only `active` / `trialing` grant subscription access.
- `pending`, `past_due`, `payment_failed`, and `paused` remain recoverable lifecycle states but do not grant access.
- Billing-period usage resets exactly once on renewal.
- Lifetime usage does not reset on renewal.
- Duplicate renewal synchronization does not duplicate allocations.
- Trialing subscriptions grant access.
- Successful trial end becomes `active`.
- A direct trial with no payment method can become `paused`, and paused access is removed.
- Cancel-at-period-end remains active until Stripe confirms cancellation state.
- Undo-cancel restores the provider/local flag.
- Final cancellation becomes terminal and removes access.
- Entitlement upgrade applies immediately during a trial and preserves the original trial end.
- Entitlement downgrade is scheduled at period end and can be cancelled safely.
- Invoice webhook may arrive before `customer.subscription.created` and still converge to one local subscription.
- Failed webhook handlers remain unprocessed and can be retried using the **same Stripe event ID** after the dependency is fixed.
- Initial payment failure does not grant allocations.
- Recovery uses the existing subscription/invoice instead of creating a duplicate checkout.
- Failed renewal does not grant a fresh usage allocation.
- Successful payment recovery restores `active` access and creates the new period allocation exactly once.

## Safety requirements

Use only a disposable migrated database. The runner refuses a database URL that does not contain the word `test` and refuses any Stripe key that does not start with `sk_test_`.

You can reuse the custom-plan disposable database you already created:

```text
CEOPRO_CUSTOM_PLAN_TEST
```

Do **not** use `CEOPROTEST3` or production.

## PowerShell setup

If the same terminal still has the custom-plan test variables:

```powershell
$env:DATABASE_URL
$env:CUSTOM_PLAN_TEST_DATABASE_URL
$env:STRIPE_SECRET_KEY
```

`DATABASE_URL` / `CUSTOM_PLAN_TEST_DATABASE_URL` should end in:

```text
/CEOPRO_CUSTOM_PLAN_TEST
```

and the Stripe key must start with:

```text
sk_test_
```

You may explicitly set the lifecycle variable too:

```powershell
$env:SUBSCRIPTION_TEST_DATABASE_URL=$env:CUSTOM_PLAN_TEST_DATABASE_URL
```

## Before running

Stop these if they are running against the same test DB:

```text
npm run dev
stripe listen --forward-to localhost:5000/stripe/webhooks
```

The lifecycle suite creates its own Stripe TEST objects and directly invokes CEOPRO's webhook service, so external webhook forwarding is unnecessary and can introduce races.

Make sure migrations are current:

```powershell
$env:DATABASE_URL=$env:CUSTOM_PLAN_TEST_DATABASE_URL
npm run prisma:migrate:test
```

## Run the lifecycle suite

```powershell
npm run test:subscription:lifecycle
```

Expected final result:

```text
============================================================
 Subscription Lifecycle Summary
============================================================
Passed groups : 7/7
Failed groups : 0

Result: PASSED.
```

## Full billing release run

After the lifecycle suite is stable, this command runs the custom-plan release checks first and then the subscription lifecycle suite:

```powershell
npm run test:billing:release
```

That gives you one release path for:

```text
custom-plan core
→ custom-plan DB
→ custom-plan Stripe E2E
→ subscription lifecycle Stripe E2E
```

## Created resources and cleanup

The tests create temporary Stripe test-mode Products, Prices, Customers, Subscriptions, and Test Clocks, plus temporary CEOPRO tenant/plan/feature/subscription rows. Cleanup runs in `finally` blocks. Stripe objects that cannot be deleted are cancelled/deactivated.

If a test process is force-killed, some Stripe test objects may remain visible in the Stripe test dashboard. They are test-mode objects only and can be cleaned later.

## Reading failures

The first failed group is the best place to start. Example:

```text
[02/07] 21 - Billing-cycle reset
...
FAIL GROUP: 21 - Billing-cycle reset
```

Send the entire failing group output. Do not weaken a business assertion merely to make the test green; either fix the implementation or deliberately change the intended lifecycle contract.
