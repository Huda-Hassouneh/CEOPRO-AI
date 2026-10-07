# CEOPRO Production Standard-Plan Bootstrap

This bootstrap replaces manual Owner Portal entry for the first production catalog.
It is intentionally **not** `prisma/seed.ts` and does not create tenants, users, sales,
forecasts, reviews, or other synthetic fixtures.

## Authoritative catalog

The production manifest lives at:

```text
src/config/production-plans.ts
```

The initial production tiers are:

| Plan | Base price | Trial | Positioning |
|---|---:|---:|---|
| Starter | 55 USD/month | 14 days | Core analytics, basic ingestion, limited AI |
| Growth | 140 USD/month | 14 days | Forecasting, market/competitor intelligence, expanded AI |
| Enterprise | 350 USD/month | 7 days | Higher workload limits, advanced integrations, faster monitoring |

All tiers expose these billing options without changing entitlements:

- Monthly: 1 month, 0% discount
- Three months: 3 months, 10% discount
- Six months: 6 months, 20% discount

## Safe first deployment

Apply migrations first:

```bash
npx prisma migrate deploy --config prisma7.config.ts
```

Initialize the canonical feature catalog on a fresh database:

```bash
npm run bootstrap:features
```

Initialize the shared Stripe Product once:

```bash
npm run bootstrap:stripe
```

Preview the plan reconciliation:

```bash
npm run bootstrap:plans:dry-run
```

Apply the production plans:

```bash
npm run bootstrap:plans
```

Or on a clean environment run the canonical feature, Stripe Product, and plan bootstraps together:

```bash
npm run bootstrap:production:init
```

For later Stripe + plan reconciliation without rebuilding features:

```bash
npm run bootstrap:production
```

Then verify DB ↔ Stripe ↔ entitlement consistency:

```bash
npm run verify:plans:production
```

## Production safety gates

When `NODE_ENV=production`, the first-time `bootstrap:production:init` command also executes the guarded feature-catalog rebuild and therefore requires:

```text
ALLOW_PRODUCTION_FEATURE_BOOTSTRAP=true
CONFIRM_PRODUCTION_PLAN_BOOTSTRAP=YES
```

When `STRIPE_SECRET_KEY` is a live key, it also requires:

```text
CONFIRM_LIVE_STRIPE_PLAN_BOOTSTRAP=YES
```

The standalone `bootstrap:stripe` command has equivalent dedicated gates
(`CONFIRM_PRODUCTION_STRIPE_BOOTSTRAP=YES` and `CONFIRM_LIVE_STRIPE_BOOTSTRAP=YES`).
The combined plan confirmation variables are also accepted so the Stripe/plan stages of both `bootstrap:production` and `bootstrap:production:init` remain explicitly confirmed.

These are deliberately explicit so a copied command cannot silently create live Stripe Prices.

## Idempotency and update behavior

Re-running `bootstrap:plans` with the same manifest:

- reuses the existing CEOPRO Plan rows;
- reuses matching Stripe Prices;
- does not duplicate PlanFeature links;
- does not duplicate PlanPriceVersion mappings;
- keeps the same public Starter/Growth/Enterprise catalog;
- deactivates non-manifest standard plans instead of deleting them.

If a future manifest changes price/billing terms, Stripe gets a new immutable Price and the old
price remains recorded in `plan_price_versions`. Existing subscriptions can remain on their
historical provider price.

Feature entitlements are not versioned by the current schema. Therefore, if a production tier has
existing subscriptions and its feature/limit matrix differs from the manifest, bootstrap **fails safe**
instead of silently changing customer access. A deliberate emergency override exists:

```text
ALLOW_ACTIVE_STANDARD_PLAN_ENTITLEMENT_CHANGES=true
```

Do not set it for ordinary deployments. A new plan/catalog version is safer for commercial changes.

## RAG quota correction

The runtime charges `rag_assistant` by `totalTokens`; therefore the canonical feature definition now
uses `tokens` / `رمز`, not `queries` / `استفسار`. The production plan bootstrap can safely reconcile
that known metadata correction.

## What this bootstrap intentionally does not add yet

The manifest does not advertise feature codes that are not yet intended for the initial commercial
launch, including `market_perception`, `inventory_intelligence`, `system_alerts`, `ai_pricing`,
`report_generation`, `marketing_image_generation`, and `team_members`.

Those can be added later only after their production entitlement gates and customer UX are verified.

## Tests

After applying these files, the previously failing production-bootstrap checks should pass:

```bash
npm run test:plans:production
```

Expected:

```text
Passed groups : 7/7
Failed groups : 0
Result: PASSED.
```


The canonical operational guide for all bootstrap files is `prisma/bootstrap/README.md`.
