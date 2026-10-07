# Feature Catalog & Entitlement Tests

These tests define the commercial/runtime feature contract used across plans and usage enforcement.

| File | What it tests |
| --- | --- |
| `feature-catalog.test.ts` | Canonical feature catalog uniqueness/count, billing-period `SUM` usage features, lifetime `MAX` capacity features, and RAG's token billing unit contract. |
| `feature-entitlement-policy.test.ts` | Missing-feature blocking, quota exhaustion vs capacity reached, unlimited behavior, MAX-capacity remaining-slot logic, multi-unit additions, and capacity freed by deletion. |

These are fast deterministic tests and should not need external services.
