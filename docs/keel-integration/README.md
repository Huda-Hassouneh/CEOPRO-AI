> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

> **Phase 0V — BLOCKED:** exact supplied Task 6 content and 13 selected policies verified; clean reviewed commit/native PG17/full runtime regression gates remain open. Read [SOURCE_BASELINE_VERIFICATION.md](SOURCE_BASELINE_VERIFICATION.md), [PHASE0V_NATIVE_VERIFICATION.md](PHASE0V_NATIVE_VERIFICATION.md) and [NEXT_IMPLEMENTATION_HANDOFF.md](NEXT_IMPLEMENTATION_HANDOFF.md). No production implementation authorized.

> **Owner update — 2026-10-20:** 13/13 architecture policy directions are now SELECTED. Earlier statements below that all ADRs are pending are historical and superseded by [DECISION_REGISTER.md](DECISION_REGISTER.md) and [OWNER_RECONCILIATION_REPORT.md](OWNER_RECONCILIATION_REPORT.md). Explicit detailed values/legal/operational rules remain PENDING. Implementation remains NOT AUTHORIZED.

> Phase 0R: read [SOURCE_TRACE_CORRECTIONS.md](SOURCE_TRACE_CORRECTIONS.md) and [PHASE0R_README.md](PHASE0R_README.md) before relying on original source-inference wording. Native/runtime gates remain pending.

# KEEL Unified Python Integration — Phase 0 review pack

**Verdict: BLOCKED for implementation; architecture proposals ready for owner review.**
Date: 20 October 2026. No production code, historical migration, model, frontend source or Node reference was changed. No commit, push, merge, deployment or production database access was performed.

The scope is authentication/tenant authorization; complete billing, promos and custom plans/dashboards; 21 Node feature codes plus Python-only budgets; dedicated Shopify/WooCommerce; their manual/canonical import dependencies; pricing; BUSINESS/PRODUCT/COMPETITOR MPI. Other AI functions are preservation/dependency obligations, not a wholesale port.

## Read in this order

1. [SOURCE_BASELINES.md](SOURCE_BASELINES.md): supplied snapshot versus Git HEAD and Task 6 evidence.
2. [DECISION_REGISTER.md](DECISION_REGISTER.md): specific choices needing approval; no commercial default selected.
3. [architecture](architecture/FEATURE-auth.md): seven feature notes and per-conflict ADRs, linked in the register.
4. [CAPABILITY_TRACEABILITY.csv](CAPABILITY_TRACEABILITY.csv): 125 atomic business behaviors; [FEATURE_AND_ENTITLEMENT_CROSSWALK.csv](FEATURE_AND_ENTITLEMENT_CROSSWALK.csv): all 21 Node codes plus three Python-only codes.
5. [DEPENDENCY_AND_SCHEMA_MAP.md](DEPENDENCY_AND_SCHEMA_MAP.md), [ROUTE_MOUNT_MAP.md](ROUTE_MOUNT_MAP.md) and evidence indexes for source/function/SQL/UI dependencies.
6. [IMPLEMENTATION_PHASES.md](IMPLEMENTATION_PHASES.md): bounded tasks, exact proposed file scopes, migrations and acceptance gates.
7. [TEST_EVIDENCE.md](TEST_EVIDENCE.md), [OPEN_GAPS_AND_RELEASE_BLOCKERS.md](OPEN_GAPS_AND_RELEASE_BLOCKERS.md), [UNIFIED_FILE_CHANGE_LEDGER.md](UNIFIED_FILE_CHANGE_LEDGER.md).
8. [NEXT_TASK.md](NEXT_TASK.md): prerequisite verification task; implementation requires architecture approval first.

## Findings that change the migration

- Python main is already the billing, identity, entitlement, credit and model owner. Its internal plan keys remain `starter/growth/enterprise/custom`, displayed as Standard/Plus/Pro/Custom. Latest Pro migration makes products 500 and seats 50. Do not copy older plan values or assume names identify equivalent grants.
- Task 6 repairs are present in the supplied working files, but the archive's Git HEAD is `1de393c77dfc6db9d8722d8a611d2384d64d12c0` on `main`. Exactly five tracked production paths differ ignoring line-ending changes; the new report-identity migration and verification material are untracked. There is no verified post-Task-6 commit ID. Native multi-session proof and real Stripe TEST verification remain missing.
- Python has credit spending caps, verified provider schedules, conservative crash accounting, contract CLI and historical Stripe mappings that must survive. Python hosted Checkout allows provider promotion codes; it does **not** provide Node's managed promo lifecycle or quote configurator/operator dashboards.
- Dedicated Shopify/WooCommerce behavior exists in Node **and its read-only `ai/` subtree**. Python's generic connector worker stages records, but does not call canonical promotion. A generic REST form is not a dedicated store integration.
- In this supplied Python version, file promotion already mirrors transactions into invoices/items and supports barcode matching and batch savepoints. Preserve those writes; the older description of sales-only promotion is stale.
- `/pricing/recommend` and `/pricing/recommend-all` are mounted without a module dependency and have no feature-count reservation in their pipeline. Python MPI is module-gated by market_intelligence; it lacks Node's independent market_perception grant semantics.
- Python MPI already supports all three subjects and a stronger weighted calculation; Node adds stricter subject/review eligibility. Low-sample output and pricing fallback/freshness/FX rules conflict. These are explicit ADRs, not permission to alter model math.

## Evidence and completeness boundary

The code indexes cover both supplied trees, including entrypoints, frontend client calls, helper imports/function calls, schema changes, gate references and tests. Every capability has a verdict and a planned acceptance case. Source existence and syntactic dependency edges are not runtime certification. Static import resolution has limitations for dynamic imports, `from package import child`, TypeScript aliases and late database functions; unresolved edges remain visible, never labeled equivalent or complete. Some capability evidence is domain-level rather than a fully proven recursive branch; those are explicitly review obligations in [TRACE_BOUNDARIES.md](TRACE_BOUNDARIES.md). No claim is made that the contract's exhaustive runtime verification, native database baseline or clean post-Task-6 prerequisite has passed.

**Available baseline:** 56 backend checks passed, 94 skipped for disabled database suite; frontend 90/90 passed and build succeeded. Task 6's supplied 140/10 result is prior-run evidence only. Overall migration remains unimplemented. Phase 0 is a reviewable design deliverable with open verification gates, not DONE under the contract's full completion rules.
