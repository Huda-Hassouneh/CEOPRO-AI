# CEOPRO Production Bootstrap

This folder is the canonical home for **production bootstrap logic**: application-level data and configuration that a freshly migrated CEOPRO database needs before the platform is used.

> **Bootstrap is not migration and it is not seeding.**
>
> - `prisma/migrations/` changes the database schema.
> - `prisma/bootstrap/` creates or reconciles required production application data.
> - `prisma/seed.ts` and other seed files create development/demo/test data.
> - `scripts/` contains tests, verification tools, maintenance/backfill scripts, and developer utilities.

**Never run `prisma:seed` as part of a production bootstrap.**

---

## Table of Contents

1. [Folder Structure](#folder-structure)
2. [What Each Bootstrap File Does](#what-each-bootstrap-file-does)
3. [Helper Modules](#helper-modules)
4. [Command Quick Reference](#command-quick-reference)
5. [First Production Deployment](#first-production-deployment)
6. [Normal Later Deployments](#normal-later-deployments)
7. [Production Safety Gates](#production-safety-gates)
8. [Bootstrap Details](#bootstrap-details)
9. [Verification](#verification)
10. [What Does Not Belong in Bootstrap](#what-does-not-belong-in-bootstrap)
11. [Failure and Recovery Rules](#failure-and-recovery-rules)
12. [Clean Production Checklist](#clean-production-checklist)

---

## Folder Structure

```text
prisma/
├── bootstrap/
│   ├── README.md
│   ├── owner.ts
│   ├── admin.ts
│   ├── features.ts
│   ├── stripe.ts
│   ├── plans-production.ts
│   │
│   └── helpers/
│       ├── logs.ts
│       ├── hash.ts
│       ├── environment.ts
│       ├── manifest.ts
│       └── stripe.ts
│
├── migrations/
├── seed.ts
└── ...
```

The authoritative standard-plan manifest remains here:

```text
src/config/production-plans.ts
```

That file is **configuration consumed by the bootstrap**, not an executable bootstrap script.

---

## What Each Bootstrap File Does

| File                  | Responsibility                                                                                                        | Production behavior                                                                                                                 |
| --------------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `features.ts`         | Rebuilds the canonical CEOPRO feature catalog and restores supported feature references.                              | **Destructive catalog rebuild.** Guarded in production. Intended for first clean initialization or an intentional reviewed rebuild. |
| `stripe.ts`           | Ensures the shared CEOPRO Stripe Product exists and stores its ID in `AppConfig`.                                     | Idempotent when already initialized. Live Stripe requires explicit confirmation.                                                    |
| `plans-production.ts` | Reconciles Starter/Growth/Enterprise, Stripe Prices, billing options, plan-feature links, and price-version mappings. | Repeatable reconciliation. Supports dry-run and verify-only modes. Unknown standard plans are deactivated, not deleted.             |
| `owner.ts`            | Creates or reuses the platform owner user, platform tenant, and owner membership.                                     | Explicit privileged provisioning step. Runs atomically so partial owner provisioning is rolled back on failure.                     |
| `admin.ts`            | Creates or reuses an optional platform admin user and membership.                                                     | Explicit optional provisioning step. Must not demote or replace the platform owner.                                                 |

---

## Helper Modules

`helpers/` contains reusable support logic for `plans-production.ts`.

| Helper           | Responsibility                                                                                                  |
| ---------------- | --------------------------------------------------------------------------------------------------------------- |
| `logs.ts`        | Consistent bootstrap logging such as section lines, steps, success messages, info, and warnings.                |
| `hash.ts`        | Stable serialization and hashing used to compare manifests and generate deterministic fingerprints.             |
| `environment.ts` | Environment validation, production safety checks, and readable DB target display.                               |
| `manifest.ts`    | Production-plan manifest validation and canonical feature reconciliation.                                       |
| `stripe.ts`      | Shared Stripe Product checks, Stripe Price reconciliation, idempotency keys, and retirement of replaced Prices. |

The main `plans-production.ts` file should stay focused on **orchestration and database plan persistence**, while helper files own the supporting concerns.

---

## Command Quick Reference

```bash
npm run bootstrap:features
npm run bootstrap:stripe
npm run bootstrap:plans
npm run bootstrap:plans:dry-run

npm run bootstrap:production
npm run bootstrap:production:init
npm run bootstrap:production:verify

npm run bootstrap:owner
npm run bootstrap:admin

npm run verify:plans:production
```

### Recommended meaning of each command

| Command                       | Use it when                                                                                               |
| ----------------------------- | --------------------------------------------------------------------------------------------------------- |
| `bootstrap:features`          | You intentionally need to rebuild the canonical feature catalog.                                          |
| `bootstrap:stripe`            | You need to initialize or verify the shared Stripe Product.                                               |
| `bootstrap:plans`             | You need to reconcile production standard plans and Stripe Prices.                                        |
| `bootstrap:plans:dry-run`     | You want to preview plan reconciliation without mutating DB plan rows or creating/changing Stripe Prices. |
| `bootstrap:production`        | Repeatable Stripe + production-plan reconciliation. **Does not rebuild features.**                        |
| `bootstrap:production:init`   | First clean production initialization: features → Stripe → plans.                                         |
| `bootstrap:production:verify` | Verify the final production plan/Stripe/catalog state.                                                    |
| `bootstrap:owner`             | Provision the real platform owner.                                                                        |
| `bootstrap:admin`             | Optionally provision an initial platform admin.                                                           |

---

# First Production Deployment

Use this sequence for a **new production database**.

## 1. Configure Production Environment Variables

At minimum, configure the normal production environment including:

```text
NODE_ENV=production
DATABASE_URL=...
STRIPE_SECRET_KEY=...
```

For the initial feature bootstrap:

```text
ALLOW_PRODUCTION_FEATURE_BOOTSTRAP=true
```

For production plan/Stripe catalog writes:

```text
CONFIRM_PRODUCTION_PLAN_BOOTSTRAP=YES
```

When using a live Stripe key (`sk_live_...`):

```text
CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP=YES
```

These flags are intentionally explicit. They prevent accidental production catalog mutation and accidental live Stripe writes.

---

## 2. Confirm PostgreSQL + pgvector Are Ready

CEOPRO requires PostgreSQL with the `vector` extension available.

Before migrations, verify that production PostgreSQL supports pgvector and enable it if required:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name = 'vector';

CREATE EXTENSION IF NOT EXISTS vector;

SELECT extname, extversion
FROM pg_extension
WHERE extname = 'vector';
```

Do not continue if the production database cannot provide the extension required by the migration chain.

---

## 3. Apply Migrations

```bash
npx prisma migrate deploy --config prisma7.config.ts
```

Expected result:

- all schema migrations are applied;
- Prisma migration history is up to date;
- required tables, constraints, indexes, and extensions exist.

Migrations must complete successfully **before any bootstrap script runs**.

---

## 4. Optional: Preview Plan Reconciliation

If the canonical feature catalog already exists, preview the plan reconciliation with:

```bash
npm run bootstrap:plans:dry-run
```

For a completely fresh database, go directly to the full initialization step because production plans depend on canonical feature rows.

---

## 5. Run the Initial Production Bootstrap

```bash
npm run bootstrap:production:init
```

Dependency order:

```text
bootstrap:features
        ↓
bootstrap:stripe
        ↓
bootstrap:plans
```

Expected result:

1. the canonical feature catalog exists;
2. the shared CEOPRO Stripe Product exists;
3. its Stripe Product ID is stored in `AppConfig`;
4. Starter, Growth, and Enterprise are reconciled;
5. approved billing options are present;
6. plan-feature mappings are present;
7. Stripe Price mappings are stored in `plan_price_versions`;
8. non-manifest active **standard** plans are deactivated, never deleted.

### Important

`bootstrap:production:init` is an **initialization command**, not a normal startup command.

Do **not** add it to:

```text
API startup
application restart
worker startup
every ordinary deployment
```

Use it only for:

- the first clean production initialization; or
- an intentional feature-catalog rebuild after review and backup.

---

## 6. Create the Platform Owner

Set at least:

```text
OWNER_EMAIL=owner@example.com
OWNER_PASSWORD=<strong secret>
```

Optional values:

```text
OWNER_FULL_NAME=Platform Owner
OWNER_COMPANY_NAME=CEO PRO Platform
OWNER_COUNTRY_CODE=JO
OWNER_PRIMARY_CURRENCY=JOD
OWNER_TIMEZONE=Asia/Amman
OWNER_LANGUAGE=en
```

Run:

```bash
npm run bootstrap:owner
```

Expected result:

```text
platform owner user
        +
platform company/tenant
        +
active owner membership
```

The provisioning is transactional: either the required owner state is completed successfully, or changes from that attempt are rolled back.

If the script prints an access token, treat it as a secret. Do not paste production bootstrap output into public logs, tickets, screenshots, or issues.

---

## 7. Optional: Create an Initial Platform Admin

The main production bootstrap does **not** automatically create an admin.

Required values:

```text
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=<strong secret>
ADMIN_TENANT_ID=<platform tenant UUID>
```

If the tenant does not already exist, `ADMIN_TENANT_NAME` must also be provided.

Run:

```bash
npm run bootstrap:admin
```

Expected result: the admin user/membership is created or reused without replacing or demoting the owner.

---

## 8. Verify the Production Catalog

```bash
npm run bootstrap:production:verify
```

Equivalent:

```bash
npm run verify:plans:production
```

Expected result: the command exits successfully only when the DB + Stripe + entitlement configuration matches the approved production manifest.

---

# Normal Later Deployments

After the first clean initialization, **do not automatically rebuild features**.

Use:

```bash
npm run bootstrap:production
```

for normal repeatable catalog reconciliation.

Conceptually:

```text
bootstrap:stripe
        ↓
bootstrap:plans
```

This command does **not** call `bootstrap:features`.

If only the standard plan catalog changed, you can run:

```bash
npm run bootstrap:plans
```

and then:

```bash
npm run bootstrap:production:verify
```

---

# Production Safety Gates

## Feature Catalog Rebuild

`features.ts` refuses a production rebuild unless:

```text
ALLOW_PRODUCTION_FEATURE_BOOTSTRAP=true
```

That guard exists because the script temporarily unlinks dependent records, recreates the canonical feature catalog, and restores supported mappings.

The entire rebuild runs atomically: **all steps succeed, or all changes are rolled back**.

---

## Production Plan Writes

Production plan/catalog mutation requires:

```text
CONFIRM_PRODUCTION_PLAN_BOOTSTRAP=YES
```

---

## Live Stripe Writes

When `STRIPE_SECRET_KEY` is a live key:

```text
CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP=YES
```

must be explicitly set before plan bootstrap can create/reconcile live Stripe Prices.

Do not bypass these gates merely to make a command pass.

---

# Bootstrap Details

## `bootstrap:features`

This is the most sensitive bootstrap command.

It:

1. reads the existing features;
2. snapshots supported relationships;
3. temporarily disconnects dependent references where needed;
4. deletes the old feature catalog;
5. recreates canonical features;
6. maps old feature codes to new feature IDs;
7. restores plan-feature mappings;
8. restores metered usage rows;
9. restores custom-plan quote feature mappings;
10. restores vendor-rate feature references;
11. verifies the final canonical feature set.

Because the database passes through temporary intermediate states, the operation runs inside a transaction.

### Before running it on an existing production database

1. take a database backup;
2. verify migrations are current;
3. ensure no unsupported external process depends on feature row IDs;
4. stop or control concurrent writes if necessary;
5. run feature verification afterward;
6. run production-plan verification afterward.

Do **not** treat this command as a harmless routine rerun.

---

## `bootstrap:stripe`

Purpose:

```text
Create or reuse the shared CEOPRO Stripe Product
        ↓
Persist its ID in AppConfig
```

If the Stripe Product ID is already configured, the command reports that Stripe is already initialized and does not create another shared product.

The shared Stripe Product is production infrastructure/bootstrap state. It should be initialized through the bootstrap flow rather than through a public runtime initialization endpoint.

---

## `bootstrap:plans`

`plans-production.ts` reconciles the approved production standard-plan catalog.

It validates:

- exactly the intended production tiers;
- tier ordering;
- plan pricing;
- currency;
- billing options;
- feature codes;
- numeric limits;
- boolean entitlement rules;
- competitor-management configuration;
- connected-data-source requirements.

It then reconciles:

```text
Production manifest
        ↓
canonical feature definitions
        ↓
shared Stripe Product
        ↓
Starter
Growth
Enterprise
        ↓
Stripe Prices
        ↓
DB plan rows
        ↓
plan features
        ↓
plan_price_versions
        ↓
final verification
```

### Stripe Price behavior

Stripe Prices are treated as immutable commercial records.

If an existing Stripe Price exactly matches the desired:

- product;
- currency;
- amount;
- interval;
- interval count;

the bootstrap reuses it.

If the desired terms changed, the bootstrap creates a new Stripe Price and retains historical mappings for existing subscriptions.

Replaced Stripe Prices are retired/deactivated rather than treated as if they never existed.

### Idempotency

Stripe Price creation uses a deterministic idempotency key derived from catalog/plan/pricing inputs.

This makes retries safer and helps prevent accidental duplicate provider operations.

The bootstrap also checks existing state before creating new resources, so repeated runs with the same manifest should converge on the same catalog state.

### Existing customer protection

If a standard plan already has current subscriptions and the desired entitlement set changed, the bootstrap fails safe by default.

A deliberate override exists:

```text
ALLOW_ACTIVE_STANDARD_PLAN_ENTITLEMENT_CHANGES=true
```

Do not enable it for ordinary deployments.

For commercial entitlement changes affecting active customers, creating a new catalog/version is usually safer than silently mutating what customers already bought.

---

## `bootstrap:owner`

`owner.ts` provisions one logical unit:

```text
owner user
    +
platform tenant
    +
owner membership
```

The operation runs inside a transaction so partial provisioning cannot be left behind if a later step fails.

It is designed to create/reuse existing valid state rather than blindly duplicate records.

---

## `bootstrap:admin`

`admin.ts` provisions an optional initial platform admin.

It is not part of the automatic core production bootstrap because privileged identities require explicit production credentials and deliberate provisioning.

---

# Verification

## Production Catalog Verification

```bash
npm run bootstrap:production:verify
```

or:

```bash
npm run verify:plans:production
```

The verification checks the approved production catalog against persisted state, including:

- active standard plans;
- entitlements;
- billing options;
- Stripe Product;
- relevant Stripe Price mappings.

The command exits non-zero if the production catalog does not match expectations.

---

## Development / CI Contract Tests

Use the existing verification suites where appropriate:

```bash
npm run test:features
npm run test:plans:production
```

The production-plan integration suite must use:

```text
a disposable test database
+
an sk_test_... Stripe key
```

Never point production integration tests at a live production database.

---

# What Does Not Belong in Bootstrap

The following intentionally remain outside `prisma/bootstrap/`.

| Script / area                              | Why                                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `scripts/reconcile-plan-price-versions.ts` | Historical/backfill maintenance for existing installations.                                      |
| `scripts/verify-*.mjs`                     | Verification/test runners, not initialization.                                                   |
| `scripts/run-*.mjs`                        | Test orchestration, not initialization.                                                          |
| `scripts/generate-mock-token.ts`           | Development helper.                                                                              |
| `prisma/seed.ts`                           | Development/test synthetic data.                                                                 |
| `prisma/seed-dashboard-metrics.ts`         | Test/demo metric data.                                                                           |
| one-off repair scripts                     | Maintenance operations should remain explicit and separate from repeatable production bootstrap. |

---

# Failure and Recovery Rules

If any bootstrap command fails:

1. **stop the deployment/bootstrap sequence;**
2. read the reported error;
3. correct the actual cause;
4. verify database/provider state;
5. rerun the intended bootstrap command.

Do not:

```text
replace bootstrap with prisma:seed
use prisma db push to bypass migrations
remove production safety checks
manually insert random replacement rows
ignore a failed Stripe/DB reconciliation
```

### Transactional operations

For transactional bootstrap operations, a thrown error causes the DB changes in that transaction to roll back.

Examples:

```text
features.ts
→ destructive catalog rebuild is atomic

owner.ts
→ owner provisioning is atomic
```

Stripe is an external provider and cannot participate in a PostgreSQL transaction. The plan bootstrap therefore uses reconciliation, idempotency, historical mappings, and verification to safely converge DB + Stripe state.

---

# Clean Production Checklist

```text
[ ] Production environment variables configured
[ ] Production PostgreSQL available
[ ] pgvector extension available/enabled
[ ] prisma migrate deploy completed successfully

[ ] Production bootstrap safety flags reviewed
[ ] npm run bootstrap:production:init completed successfully

[ ] npm run bootstrap:owner completed successfully
[ ] npm run bootstrap:admin completed only if an initial admin is desired

[ ] npm run bootstrap:production:verify passed

[ ] Dangerous one-time feature-bootstrap flag removed/reviewed after initialization
[ ] API build completed
[ ] API started
[ ] background workers started as separate supervised processes
[ ] Stripe webhook configured with the live production endpoint
[ ] production smoke test completed
```

---

# Recommended Production Sequence

For a brand-new production environment:

```bash
npm ci

npm run prisma:validate
npm run prisma:generate

npx prisma migrate deploy --config prisma7.config.ts

npm run bootstrap:production:init

npm run bootstrap:owner

# Optional
npm run bootstrap:admin

npm run bootstrap:production:verify

npm run build
npm start
```

Background workers should then be started separately using their own supervised process/container commands.

---

## Final Rule

The bootstrap folder should contain only **production-safe initialization and reconciliation logic required to prepare application state after migrations**.

If a script is:

- synthetic data,
- a test,
- a verification runner,
- a historical backfill,
- a one-off repair,
- or a developer helper,

it does **not** belong in `prisma/bootstrap/`.
