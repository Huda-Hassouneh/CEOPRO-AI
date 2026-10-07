# Production Plan & Bootstrap Tests — Scenarios 27–33

Tests the boundary between development/test fixtures and the real standard-plan production bootstrap path.

`PRODUCTION_PLAN_TESTING.md` explains the verification suite. `PRODUCTION_PLAN_BOOTSTRAP.md` documents the intended production bootstrap process.

| Scenario | What it tests |
| --- | --- |
| `27` | Public catalog exposes only active, tenant-neutral standard plans. |
| `28` | Shared Stripe Product bootstrap is fail-fast/idempotent and persists one provider product mapping. |
| `29` | Standard plans create stable database↔Stripe price mappings for monthly/yearly billing. |
| `30` | Public catalog visibility vs platform-managed catalog visibility for inactive standard plans. |
| `31` | Standard-plan checkout uses server-owned Stripe Price and tenant metadata. |
| `32` | Successful standard-plan subscription synchronizes the correct plan and feature allocation. |
| `33` | Production bootstrap safety: no dev seed, explicit production manifest, supported tier names/currency, dry-run/verification/live-write gates, no tenant/user creation, live Stripe protections. |
| `_production-plan-helpers.ts` | Shared Stripe/DB production-shaped fixtures, safety checks, bootstrap helpers, synchronization, cleanup. |

## Safety

Provider scenarios require a disposable TEST database and `sk_test_` Stripe key. Group `33` is intentionally strict because failures can identify real release-readiness gaps rather than test defects.
