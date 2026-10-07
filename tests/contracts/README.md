# Cross-Cutting Contract Verifiers

These `.mjs` scripts statically inspect backend source/schema/migrations to guard architecture and security contracts that span multiple modules. Run them from the backend repository root.

| File | What it verifies |
| --- | --- |
| `verify-custom-plan-contract.mjs` | Custom-plan schema, pricing formula/policy, server-authoritative recalculation, tenant privacy, quote→plan persistence, immutable accepted custom plans, promo ownership, entitlement-aware transitions, vendor/infrastructure pricing evidence, competitor cadence semantics. |
| `verify-feature-entitlements.mjs` | Production feature bootstrap, usage aggregation rules, capacity usage, validator enforcement, route entitlement guards, and canonical feature presence. |
| `verify-route-contract.mjs` | Expected application mounts and subscription/features/platform-admin/Stripe route surfaces remain present at their intended paths. |
| `verify-security-regressions.mjs` | Broad regression guard for checkout contract, Stripe bootstrap/customer isolation, usage/webhook idempotency, promo isolation, currency rules, centralized statuses, startup/CORS/error/JWT hardening, tenant FK, custom-plan privacy/pricing/immutability, platform membership/permissions/Admin Team owner protections, and precision rules. |

These scripts are intentionally source-sensitive. A failure means either the implementation regressed or the contract deliberately changed and the verifier must be updated with that decision.
