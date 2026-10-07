# CEOPRO Development/Test Seeding

This folder is the canonical home for **development and test fixture data**.

It is intentionally separate from:

- `prisma/migrations/` — database schema and DDL changes;
- `prisma/bootstrap/` — required production application configuration and catalog initialization;
- `scripts/` — verification runners, tests, maintenance/backfills, and developer utilities.

> **Never use this folder to initialize production.**
>
> Every seed entrypoint refuses to run when `NODE_ENV=production` or when the target database name does not contain `TEST` or `DEV`.

---

## Table of Contents

1. [Folder Structure](#folder-structure)
2. [Seed Entrypoints](#seed-entrypoints)
3. [Helpers](#helpers)
4. [Seeders](#seeders)
5. [Safety Model](#safety-model)
6. [Main Development Seed](#main-development-seed)
7. [Dashboard Metric Seed](#dashboard-metric-seed)
8. [Suggested Package Scripts](#suggested-package-scripts)
9. [How to Add New Seed Data](#how-to-add-new-seed-data)
10. [What Does Not Belong Here](#what-does-not-belong-here)
11. [Migration From the Old Files](#migration-from-the-old-files)

---

## Folder Structure

```text
prisma/
├── bootstrap/
│   └── ...                     # production initialization/reconciliation
│
├── seed/
│   ├── README.md
│   ├── main.ts                 # full deterministic DEV/TEST fixture seed
│   ├── dashboard-metrics.ts    # isolated dashboard KPI fixture entrypoint
│   │
│   ├── data/
│   │   └── catalog.ts          # static fixture definitions
│   │
│   ├── helpers/
│   │   ├── batch.ts
│   │   ├── environment.ts
│   │   ├── ids.ts
│   │   ├── logs.ts
│   │   └── time.ts
│   │
│   └── seeders/
│       ├── identity.seeder.ts
│       ├── billing.seeder.ts
│       ├── commerce.seeder.ts
│       ├── market-intelligence.seeder.ts
│       ├── forecasting.seeder.ts
│       ├── dashboard-metrics.seeder.ts
│       └── verification.seeder.ts
│
└── migrations/
```

The entrypoint files orchestrate the process. Domain seeders own actual fixture creation. Helpers contain reusable technical behavior only.

---

## Seed Entrypoints

### `main.ts`

Runs the complete deterministic CEOPRO development/test fixture set.

High-level order:

```text
environment safety checks
        ↓
identity + tenants
        ↓
billing/subscriptions
        ↓
products/inventory/documents/sales/reviews
        ↓
market intelligence
        ↓
forecasting/recommendations
        ↓
verification
```

### `dashboard-metrics.ts`

Creates a small isolated fixture set for testing:

- Dashboard Growth KPI;
- Review Sentiment KPI.

It operates on one existing tenant selected through `DASHBOARD_TEST_TENANT_ID`.

It also supports:

```bash
--clean
```

which removes only the dashboard fixture rows owned by that fixture namespace.

---

## Helpers

| Helper | Responsibility |
|---|---|
| `environment.ts` | DEV/TEST database guards, required environment validation, dashboard seed arguments. |
| `ids.ts` | Deterministic UUID generation and SHA-256 helpers. |
| `time.ts` | One stable seed clock shared across the run so fixture timestamps are internally consistent. |
| `batch.ts` | Batched inserts for larger fixture collections. |
| `logs.ts` | Consistent seed progress output. |

Helpers should not contain domain fixture definitions.

---

## Seeders

| Seeder | Responsibility |
|---|---|
| `identity.seeder.ts` | Companies/tenants, users, memberships, sessions, invitations, and required role checks. |
| `billing.seeder.ts` | Development showcase plan, subscriptions, and payment transactions. |
| `commerce.seeder.ts` | Products, inventory, RAG document metadata, transactions, and reviews. |
| `market-intelligence.seeder.ts` | Competitors, tenant competitors, product mappings, competitor prices, and score snapshots. |
| `forecasting.seeder.ts` | Historical/current demand forecasts, 7/30-day horizon fixtures, and recommendation outcomes. |
| `dashboard-metrics.seeder.ts` | Isolated dashboard revenue/sentiment fixtures and cleanup. |
| `verification.seeder.ts` | Confirms the expected fixture rows are visible after seeding. |

---

# Safety Model

The seed scripts are **development/test only**.

A seed run is refused when either condition is true:

```text
NODE_ENV=production
```

or the database name does not contain:

```text
TEST
or
DEV
```

For example:

```text
CEOPROTEST3    ✅
CEOPRO_DEV     ✅
ceopro-prod    ❌
production     ❌
```

This naming guard is an additional safety mechanism. It does not replace correct credentials, DB permissions, backups, or environment management.

---

# Main Development Seed

## Required Environment

```text
DATABASE_URL=postgresql://...
SEED_DEV_PASSWORD=<12+ character development password>
```

The database must already be migrated.

Run migrations first when required:

```bash
npx prisma migrate deploy --config prisma7.config.ts
```

Then run the seed:

```bash
npm run prisma:seed
```

or directly:

```bash
tsx prisma/seed/main.ts
```

### What It Creates

The main seed creates deterministic additive fixtures for:

- tenants/companies;
- users and tenant memberships;
- auth sessions;
- platform invitations;
- a development-only showcase plan;
- subscriptions and payment transactions;
- products and inventory;
- RAG document metadata;
- competitors and tenant-competitor relationships;
- competitor-product mappings and prices;
- sales transactions;
- product reviews;
- demand forecasts;
- inventory recommendations;
- competitor score snapshots.

The IDs are deterministic, and bulk inserts use `skipDuplicates` where appropriate. This makes repeated development runs converge on the same fixture identities rather than continuously creating random duplicates.

### Important

This seed is **not** the source of truth for:

- production plans;
- production feature catalog;
- platform owner/admin provisioning;
- live Stripe configuration.

Those belong to `prisma/bootstrap/`.

---

# Dashboard Metric Seed

## Required Environment

```text
DATABASE_URL=postgresql://...
DASHBOARD_TEST_TENANT_ID=<existing tenant UUID>
```

Optional:

```text
DASHBOARD_TEST_PERIOD_DAYS=30
```

Allowed periods:

```text
7
30
90
```

Run:

```bash
npm run seed:dashboard
```

or directly:

```bash
tsx prisma/seed/dashboard-metrics.ts
```

The fixture contributes:

```text
previous-period paid revenue: 100
current-period paid revenue:  150
two positive review sentiment rows
```

The reported totals can also contain pre-existing tenant data.

## Cleanup

Remove only the fixture-owned dashboard rows:

```bash
npm run seed:dashboard -- --clean
```

or:

```bash
tsx prisma/seed/dashboard-metrics.ts --clean
```

The cleanup verifies fixture ownership before deleting rows.

---

# Suggested Package Scripts

Update the existing seed paths so the folder becomes canonical:

```json
{
  "scripts": {
    "prisma:seed": "tsx prisma/seed/main.ts",
    "seed:dashboard": "tsx prisma/seed/dashboard-metrics.ts"
  }
}
```

If `prisma7.config.ts` or another Prisma configuration file still points to `prisma/seed.ts`, update that path to:

```text
prisma/seed/main.ts
```

Search before deleting the old entrypoints:

```bash
git grep "prisma/seed.ts"
git grep "seed-dashboard-metrics"
```

---

# How to Add New Seed Data

Use this rule:

```text
main.ts
    = orchestration only

data/
    = static fixture definitions

helpers/
    = reusable technical utilities

seeders/
    = domain-specific DB fixture creation
```

For example, if you add a new notifications fixture:

```text
prisma/seed/seeders/notifications.seeder.ts
```

Export a focused function:

```ts
export async function seedNotifications(context) {
  // create only notification-domain fixtures
}
```

Then call it from `main.ts` in the correct dependency order.

Avoid putting another 300-line domain block directly into `main.ts`.

---

# What Does Not Belong Here

Do not put these in `prisma/seed/`:

| Concern | Correct location |
|---|---|
| Database schema changes | `prisma/migrations/` |
| Required production catalog/configuration | `prisma/bootstrap/` |
| Production owner/admin initialization | `prisma/bootstrap/` |
| Live Stripe Product/Price setup | `prisma/bootstrap/` |
| One-off data repair | `scripts/` or dedicated maintenance folder |
| Historical backfill | `scripts/` |
| Automated verification runner | `scripts/` / tests |
| Mock token generation | developer scripts |

---

# Migration From the Old Files

After updating all references:

```text
OLD
prisma/seed.ts
prisma/seed-dashboard-metrics.ts

NEW
prisma/seed/main.ts
prisma/seed/dashboard-metrics.ts
```

Delete the old files only after package/config/test/documentation references point to the new paths.

Recommended checks:

```bash
git grep "prisma/seed.ts"
git grep "seed-dashboard-metrics"

npm run build
npm run prisma:seed
```

Use a disposable DEV/TEST database for the first verification run.

---

# Refactor Note

The original main seed inserted the same `demand_forecasts` collection twice using `skipDuplicates`.

The refactor keeps **one** insertion. This does not change the intended persisted fixture set; it only removes the redundant second no-op insert.

No production bootstrap behavior was moved into this folder.

---

## Final Rule

`prisma/seed/` exists for **safe, deterministic, navigable DEV/TEST fixture generation**.

If the data is required for a real production environment to function, it belongs in `prisma/bootstrap/`, not here.
