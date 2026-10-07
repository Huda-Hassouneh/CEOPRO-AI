# CEOPRO Custom Plan Automated Tests

This suite is designed around the current CEOPRO custom-plan implementation and is intentionally ordered so a failure is easy to locate.

It covers input validation, pricing formulas, competitor monitoring, infrastructure costs, FX/payment conversion, automatic/manual quote contracts, tenant privacy, checkout safety, promo/discount behavior, entitlement persistence, idempotency/concurrency, migrations, and an optional disposable-database integration test.

## Files

```text
tests/billing/custom-plan/
├── README.md
├── CUSTOM_PLAN_TESTING.md
├── _helpers.ts
├── custom-plan-pricing.test.ts
├── 01-input-validation.scenario.ts
├── 02-pricing-core.scenario.ts
├── 03-competitor-pricing.scenario.ts
├── 04-infrastructure-pricing.scenario.ts
├── 05-rate-and-payment-currency.scenario.ts
├── 06-quote-lifecycle-contract.scenario.ts
├── 07-security-checkout-contract.scenario.ts
├── 08-promo-entitlements-contract.scenario.ts
├── 09-idempotency-concurrency-contract.scenario.ts
├── 10-schema-migration-contract.scenario.ts
└── 11-live-db-smoke.scenario.ts

tests/runners/
└── run-custom-plan-tests.mjs
```

The existing `tests/contracts/verify-custom-plan-contract.mjs` remains in use as group 00.

## 1. Install dependencies

From the backend root:

```bash
npm ci
```

If you normally use `npm install`, that is also fine, but CI/release verification should prefer `npm ci`.

## 2. Generate Prisma client

```bash
npm run prisma:generate
```

## 3. Run the safe core suite

```bash
npm run test:custom-plan
```

This does **not** call Stripe and does **not** write to your database.

The runner executes each group in numeric order and prints a PASS/FAIL summary.

## 4. Run the disposable database integration test

Do not point this at production or your main development database.

Create/use a disposable PostgreSQL + pgvector database, apply migrations, then set:

### PowerShell

```powershell
$env:CUSTOM_PLAN_TEST_DATABASE_URL="postgresql://USER:PASSWORD@localhost:5433/CEOPRO_CUSTOM_PLAN_TEST"
$env:DATABASE_URL=$env:CUSTOM_PLAN_TEST_DATABASE_URL
npm run prisma:migrate:test
npm run test:custom-plan:db
```

### bash / zsh

```bash
export CUSTOM_PLAN_TEST_DATABASE_URL="postgresql://USER:PASSWORD@localhost:5433/CEOPRO_CUSTOM_PLAN_TEST"
export DATABASE_URL="$CUSTOM_PLAN_TEST_DATABASE_URL"
npm run prisma:migrate:test
npm run test:custom-plan:db
```

The live DB test verifies:

- Tenant A can read its quote and Tenant B cannot.
- Concurrent quote conversion has exactly one winner.
- Accepted plan is `planType=custom` and belongs to the correct tenant.
- `limit_value` is preserved.
- Feature `metadata` / operational configuration is preserved.
- Wrong-tenant quote conversion fails.
- Tenant-private custom plan does not appear in the public standard-plan list.
- Temporary test rows are deleted after the run.

## 5. Run the full suite

After setting `CUSTOM_PLAN_TEST_DATABASE_URL`:

```bash
npm run test:custom-plan:full
```

That runs groups 00 → 11 in order.

## What this suite intentionally does not do

The safe suite does not create Stripe Customers, Prices, Checkout Sessions, or advance Stripe Test Clocks. The provider boundary is checked through deterministic contracts and pure currency tests.

A true Stripe E2E suite should be a separate test stage because it creates remote Stripe test resources and depends on asynchronous webhook delivery. Do not mix that into fast local regression tests.

## Expected release workflow

```text
1. npm run prisma:validate
2. npm run build
3. npm run test:custom-plan
4. npm run test:custom-plan:db
5. existing security/feature tests
6. Stripe test-mode E2E / webhook verification
7. small final UI smoke test
```

## Reading failures

Examples:

```text
[03/11] 02 - Core pricing
...
FAIL GROUP: 02 - Core pricing
```

Start with the first failed group. The scenario name identifies the exact invariant, for example:

```text
02.06 vendor-backed feature with positive usage cannot silently price at zero
```

Do not weaken an assertion just to make a release green. If a test reflects the intended CEOPRO contract, fix the implementation or deliberately change the contract and update the test together.
