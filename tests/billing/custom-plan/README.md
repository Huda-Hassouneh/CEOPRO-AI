# Custom Plan Tests — Scenarios 01–11

This is the main custom-plan correctness suite. It starts with validation/pure pricing rules, moves through quote/security/schema contracts, and finishes with an optional disposable-database smoke test.

`CUSTOM_PLAN_TESTING.md` contains the detailed environment and release workflow.

| File | What it tests |
| --- | --- |
| `custom-plan-pricing.test.ts` | Focused regression tests for gross-margin vs vendor-cost floors, fixed platform fee, vendor-backed vs platform-only features, FX conversion, profitability, invalid ratios, competitor monitoring units/cadence. |
| `01-input-validation.scenario.ts` | Preview/checkout/manual-review DTO validation, IDs, monitoring cadence, payment method, vendor/infrastructure rate update rules. |
| `02-pricing-core.scenario.ts` | Core pricing formula, cost floors, fixed fee, round-up, missing vendor rates, policy bounds, operational multiplier/reserve, deprecated/unverified rates, profitability. |
| `03-competitor-pricing.scenario.ts` | Competitor count × monitoring cadence × rate-specific units, explicit checks/month, validation, and legacy cadence behavior. |
| `04-infrastructure-pricing.scenario.ts` | Storage MB→GB-month conversion, configured/estimated/enabled usage bases, version dedupe, deprecated rates, limit requirements, quote-time FX, conversion/multiplier validation. |
| `05-rate-and-payment-currency.scenario.ts` | Vendor-rate FX and custom-plan payment currency conversion, including missing/invalid FX protection. |
| `06-quote-lifecycle-contract.scenario.ts` | Automatic quote idempotency, pricing fingerprints, manual-review triggers, authoritative recalculation, acceptance/expiry, atomic quote→plan conversion, feature metadata persistence, accepted-plan immutability. |
| `07-security-checkout-contract.scenario.ts` | Tenant isolation, private custom plans, promo ownership, auth/tenant boundaries, platform pricing permissions, unsupported payment providers. |
| `08-promo-entitlements-contract.scenario.ts` | Billing discount vs promo behavior, promo validity/applicability, accepted feature limits/configuration, usage allocation, server-owned entitlement resolution. |
| `09-idempotency-concurrency-contract.scenario.ts` | Request-id semantics, configuration/rate fingerprint conflicts, single-winner DB claim, Stripe price idempotency, provider event dedupe. |
| `10-schema-migration-contract.scenario.ts` | Prisma/schema and migration invariants for custom plans, quotes, unique features, infrastructure rates, accepted-plan link, metadata, quote states, webhook event uniqueness. |
| `11-live-db-smoke.scenario.ts` | Optional disposable-DB verification of tenant isolation, atomic quote conversion, custom-plan ownership, feature limit/metadata persistence, wrong-tenant rejection, and public-catalog exclusion. |
| `_helpers.ts` | Shared file/source assertion helpers used by scenarios. |

## Safety

Scenarios `01–10` are the safe core layer. Scenario `11` only runs when `CUSTOM_PLAN_TEST_DATABASE_URL` is set and must point to a disposable migrated database.
