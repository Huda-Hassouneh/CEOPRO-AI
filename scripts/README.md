# CEOPRO Scripts

This folder contains **explicit developer and maintenance utilities** that do not belong to Prisma migrations, production bootstrap, seed fixtures, or the automated test tree.

The goal is to keep `scripts/` small and intentional.

## Directory responsibilities

```text
scripts/
├── README.md
├── dev/
│   └── generate-mock-token.ts
└── maintenance/
    └── reconcile-plan-price-versions.ts
```

Related responsibilities live elsewhere:

```text
prisma/migrations/     database schema evolution
prisma/bootstrap/      production initialization/reconciliation
prisma/seed/           DEV/TEST synthetic fixtures
tests/runners/         grouped test-suite runners
tests/contracts/       source/architecture/security contract checks
tests/<feature>/       executable scenario tests
```

---

## `dev/`

Developer-only helpers that must not be part of runtime startup or production initialization.

### `generate-mock-token.ts`

Generates a development access token using the configured development identity.

Run through the package command, for example:

```bash
npm run dev:token
```

Recommended package path:

```json
"dev:token": "tsx scripts/dev/generate-mock-token.ts"
```

This utility is **not authentication bootstrap** and must never be imported by `src/app.ts` or another runtime module.

---

## `maintenance/`

Explicit operational/backfill utilities for an already-existing installation.

### `reconcile-plan-price-versions.ts`

Reads incomplete local `plan_price_versions` rows, retrieves the corresponding historical Stripe Price, and fills missing interval/amount/currency information locally.

It does **not** belong in `prisma/bootstrap/` because a clean database should not require this historical backfill.

Run intentionally:

```bash
npm run maintenance:reconcile-plan-price-versions
```

Recommended package path:

```json
"maintenance:reconcile-plan-price-versions": "tsx scripts/maintenance/reconcile-plan-price-versions.ts"
```

Before running it against a real environment, confirm that `DATABASE_URL` and `STRIPE_SECRET_KEY` belong to the **same environment**.

---

## What was moved out of `scripts/`

### Production bootstrap

These old files are now redundant and should be deleted:

```text
scripts/bootstrap-stripe.ts
scripts/bootstrap-production-plans.ts
```

Their canonical implementations are:

```text
prisma/bootstrap/stripe.ts
prisma/bootstrap/plans-production.ts
```

There must be only one authoritative implementation of production bootstrap behavior.

### Test runners

Moved to:

```text
tests/runners/
├── run-custom-plan-tests.mjs
├── run-custom-plan-stripe-tests.mjs
├── run-production-plan-tests.mjs
└── run-subscription-lifecycle-tests.mjs
```

### Contract/security checks

Moved to:

```text
tests/contracts/
├── verify-custom-plan-contract.mjs
├── verify-feature-entitlements.mjs
├── verify-route-contract.mjs
└── verify-security-regressions.mjs
```

These are tests, not operational scripts.

---

## Stripe bootstrap route cleanup

Shared CEOPRO Stripe Product initialization now belongs to:

```text
prisma/bootstrap/stripe.ts
```

It should not remain exposed as the old runtime subscription onboarding route.

The moved contract checks were updated accordingly:

- `verify-route-contract.mjs` rejects `onBoardingHandler` in the runtime subscription router.
- `verify-security-regressions.mjs` verifies that Stripe initialization is bootstrap-only and that `package.json` references `prisma/bootstrap/stripe.ts`.

---

## Package.json updates

After applying this refactor, update commands that still point at the old `scripts/` locations.

Example shape:

```json
{
  "scripts": {
    "dev:token": "tsx scripts/dev/generate-mock-token.ts",
    "maintenance:reconcile-plan-price-versions": "tsx scripts/maintenance/reconcile-plan-price-versions.ts",

    "test:custom-plan": "node tests/runners/run-custom-plan-tests.mjs",
    "test:custom-plan:stripe": "node tests/runners/run-custom-plan-stripe-tests.mjs",
    "test:plans:production": "node tests/runners/run-production-plan-tests.mjs",
    "test:subscription:lifecycle": "node tests/runners/run-subscription-lifecycle-tests.mjs",

    "verify:custom-plan": "node tests/contracts/verify-custom-plan-contract.mjs",
    "verify:features": "node tests/contracts/verify-feature-entitlements.mjs",
    "verify:routes": "node tests/contracts/verify-route-contract.mjs",
    "verify:security": "node tests/contracts/verify-security-regressions.mjs"
  }
}
```

Keep your existing script names if other tooling relies on them; only the **file paths** need to change.

---

## Refactor checklist

```text
[ ] delete scripts/bootstrap-stripe.ts
[ ] delete scripts/bootstrap-production-plans.ts
[ ] move developer helper to scripts/dev/
[ ] move maintenance utility to scripts/maintenance/
[ ] move run-*.mjs files to tests/runners/
[ ] move verify-*.mjs files to tests/contracts/
[ ] update package.json paths
[ ] remove the old runtime Stripe onboarding route
[ ] run route/security contract checks
[ ] run the affected test suites
```

## Rule of thumb

If a file **initializes production application state**, it belongs in `prisma/bootstrap/`.

If it **creates synthetic DEV/TEST data**, it belongs in `prisma/seed/`.

If it **tests or verifies code**, it belongs in `tests/`.

If it is an **explicit developer utility or maintenance/backfill operation**, it belongs in `scripts/`.
