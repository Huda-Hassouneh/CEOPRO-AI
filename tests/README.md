# CEOPRO Backend Test Suite

This directory is organized by **product/domain responsibility**, so you can find a test by the CEOPRO feature it protects instead of searching a flat list.

## Folder map

```text
tests/
├── billing/
│   ├── core/                    # Small billing/subscription contract + pure logic tests
│   ├── custom-plan/             # Custom-plan validation/pricing/quote/security scenarios 01–11
│   ├── custom-plan-stripe/      # Real Stripe TEST-mode custom-plan scenarios 12–19
│   ├── subscription-lifecycle/  # Subscription lifecycle scenarios 20–26
│   └── production-plans/        # Production-plan/bootstrap scenarios 27–33
├── auth/                        # Registration, session, password, and membership selection
├── contracts/                   # Static cross-cutting source/schema/security contract verifiers
├── features/                    # Canonical feature catalog + entitlement/capacity policy
├── forecasting/                 # Demand forecasting calculations, service/controller contracts
├── notifications/
│   ├── platform/                # Platform-admin notification definition/storage/producer/worker contracts
│   └── tenant/                  # Tenant notification definition/storage/producer/worker contracts
├── rag/                         # RAG document-upload route/client contract checks
├── onboarding/                  # Tenant onboarding validation and RLS-scoped persistence
└── runners/                     # Ordered suite runners
```

Every folder contains its own `README.md` with the exact files, behaviors covered, dependencies, and safety notes.

## Test layers

- **Pure/unit tests:** deterministic calculation, validation, status, catalog, and policy behavior. These should not need a live DB or Stripe.
- **Source/migration contract tests:** read source or migration files and assert security/API/architecture invariants without starting external services.
- **Disposable DB tests:** require an explicitly configured test database and exercise Prisma-backed persistence/isolation behavior.
- **Stripe TEST-mode E2E:** require `sk_test_...` and a disposable migrated DB. They intentionally create remote Stripe test objects and refuse live keys.

## Numbered billing flow

The original scenario sequence is preserved:

```text
01–11  billing/custom-plan
12–19  billing/custom-plan-stripe
20–26  billing/subscription-lifecycle
27–33  billing/production-plans
```

That sequence makes failures easy to locate from configuration/pricing → Stripe → lifecycle → production bootstrap.

## Running an individual TypeScript test

From the backend repository root:

```bash
node --import tsx --test tests/<folder>/<file>.ts
```

Auth/onboarding checks can be run together with:

```bash
npm run test:auth-onboarding
node --import tsx --test tests/auth/*.test.ts tests/onboarding/*.test.ts
```

For the numbered suites, prefer the project npm scripts described in each suite README because their runners enforce test-DB / Stripe safety checks.

## Path migration map

Files were moved for navigation; test intent was not changed. If `package.json`, CI, or external scripts directly reference old paths, update them using this map:

| Old path | New path |
| --- | --- |
| `tests/*.test.ts` billing/subscription files | `tests/billing/core/*.test.ts` |
| `tests/custom-plan-pricing.test.ts` | `tests/billing/custom-plan/custom-plan-pricing.test.ts` |
| `tests/custom-plan/` | `tests/billing/custom-plan/` |
| `tests/custom-plan-stripe/` | `tests/billing/custom-plan-stripe/` |
| `tests/subscription-lifecycle/` | `tests/billing/subscription-lifecycle/` |
| `tests/production-plans/` | `tests/billing/production-plans/` |
| `tests/feature-catalog.test.ts` | `tests/features/feature-catalog.test.ts` |
| `tests/feature-entitlement-policy.test.ts` | `tests/features/feature-entitlement-policy.test.ts` |
| `tests/platform-notifications/` | `tests/notifications/platform/` |
| `tests/tenant-notifications/` | `tests/notifications/tenant/` |

`forecasting/`, `rag/`, `contracts/`, and `runners/` remain at the same top-level paths.

## Important execution rule

Run path-sensitive tests from the **backend repository root**. Several contract tests intentionally resolve `src/`, `prisma/`, or `package.json` from the repository root.
