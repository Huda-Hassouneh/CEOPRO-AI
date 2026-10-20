# KEEL Phase 0: Independent review and next Work handoff

**Reviewed artifact:** `KEEL_Phase0_Architecture_Review.zip` (20 October 2026).  
**Review scope:** The contents and internal consistency of its documentation/evidence; selected ZIP source-hash comparisons against the Node/Python archives uploaded in the same conversation. This is **not** a live production-code execution audit and cannot certify runtime behavior.

## Verdict: ACCEPT AS A REVIEWABLE DRAFT; DO NOT AUTHORIZE PHASE 1

The pack is meaningful and unusually candid about blockers. Its own verdict is **BLOCKED**. It contains 66 documentation/evidence files, 125 business capability records plus 4 governance controls, 125 proposed acceptance cases, 21 mapped Node feature codes, 7 feature architecture notes, and 13 pending ADRs. The archive does **not** contain a working Python integration. There were no implemented migrations or production edits in Phase 0.

### What I independently checked

1. The 129 capability IDs and 125 acceptance-test IDs are unique. Every business capability references a present acceptance-test ID. The feature crosswalk contains the 21 named Node feature codes and three Python-only placeholders.
2. The report records 56 backend checks passed and 94 skipped; 90 frontend checks passed, and the frontend build passed. Task 6's 140 passed/10 skipped is **prior evidence**, not reproduced by this Phase 0 audit. Native PostgreSQL 17 multi-session tests, live Stripe, providers and browser end-to-end flows were not executed.
3. The Node ZIP currently attached to this conversation has the exact SHA-256 stated in `SOURCE_BASELINES.md` (`c8a3bf...`). The Python ZIP currently attached is **not** the same content snapshot used by Phase 0: the present ZIP has SHA-256 `b3571d...`, versus `873cc2...` for the audited ZIP. At per-file level, 1,244 of 1,249 present non-Git Python files match the Phase 0 manifest, five billing/usage sources differ (`billing/store.py`, `billing/webhooks.py`, `core/usage.py`, `routers/dashboard.py`, `routers/reports.py`), and 34 files are present in the Phase 0 manifest but absent from the older attached Python ZIP. These include Task 6's SQL migration and remediation tests/reports. Do not discard the Phase 0 Task 6 working snapshot when creating the canonical new commit.
4. 78/125 business capability records have a **domain-source fallback** on the Node side; 43/125 have such a fallback on the Python side. The matrix does not yet certify a precise function/caller/return/database chain for all capabilities. This is acknowledged by `TRACE_BOUNDARIES.md` but needs closure before related code edits.
5. The `db_objects` field is a lexical candidate index and contains non-schema tokens such as `fastapi`, `typing` and `src.ai`; do not treat it as an authoritative table/column/RLS/SQL dependency register. Validate real objects against executed SQL and native PostgreSQL catalogs before writing migrations.
6. All thirteen ADRs remain proposed and owner-unapproved. Existing customer plans, promo stacking, FX and quote economics, paid activation, importer stock ownership, privacy retention and MPI reliability cannot be silently selected by Work.
7. The package's unified ledger reports 66 added documentation paths. The generated verification JSON reports no modified Node or original Python source and exact documentation-ledger reconciliation. I checked the ZIP inventory and internal identifiers; source-integrity statements beyond the ZIP must still be rechecked in the actual checkout.

### Meaningful design findings in the supplied review

- The Python system remains the **sole identity, subscription, Stripe, entitlement, cost-credit, canonical business data and model authority**.
- Node-only/stronger workflows include managed promos; custom-plan builder, cost/FX calculations and quotes; entitlement-aware transitions; platform owner functions; dedicated Shopify/Woo store lifecycle, adapters and workers; stronger import identities; price safety/orchestration; MPI subject safety and better three-scope UI.
- Preserve Python's historical plans/prices, provider cost ledger, spend kill switches, trial protections, weighted MPI scoring and pricing estimation fallback.
- Python's `/pricing/recommend` and `/pricing/recommend-all` are recorded as missing the desired feature access/metering gate. Python's current MPI endpoint has three calculation subjects but the frontend does not demonstrate complete three-scope workflows. Generic connectors staging records are **not** proof of canonical promotion.

## Non-negotiable gates before Phase 1

**SOURCE-001** — Establish a reviewed, clean post-Task-6 Python commit containing the five changed source paths and intended migration/tests. Preserve the Node ZIP byte-for-byte; make a full diff and log. Never reset/rebase away uncommitted fixes to manufacture a clean baseline.

**TRACE-001** — For each in-scope implementation slice, replace generic source fallbacks with exact reachable handlers, helpers, DTOs, SQL writers, RLS grants, worker calls and frontend contracts, or explicitly state `UNRESOLVED` with the concrete missing edge. Convert lexical DB candidates to an independently verified schema-object mapping. An index is a discovery aid, not end-to-end flow evidence.

**DECISIONS** — Provide an owner-friendly decision sheet for the thirteen ADRs: (1) fact and difference, (2) options, (3) technically recommended behavior, (4) customer impact/migrations and backward compatibility, (5) actual decision sought (avoid asking owners to pick technical implementation details), and (6) blank owner approval. Technical choices can be recommended without inventing commercial values or privacy commitments. No blanket approval of thirteen vague ADRs.

**VERIFY-001** — Native isolated PostgreSQL 17 database tests for schema/RLS/role grants and multi-session concurrency; repeated migrations on empty and populated copy; Stripe TEST and approved Shopify/Woo tests before production release. Work must report exact pass/failed/skipped evidence and must not turn `SKIPPED` into `PASS`.

**PHASE ACCEPTANCE** — After owner approval, implement **one bounded slice** at a time, with native schema migration, negative authorization, concurrency, worker retry/idempotency, provider errors, genuine UI/API contracts, and file-change ledger reconciled to real Git diff.

## Recommended immediate sequence

1. Securely establish the **post-Task-6 Python baseline** and compare it with the newer snapshot Work audited. Do not start with the older `main-repo(1).zip` unless it is explicitly brought forward and replayed; otherwise Task 6 repairs can vanish.
2. Run a **documentation-only Phase 0R source-trace and owner-decision refinement**, starting with AUTH, ENT, SUB, PROMO and CUSTOM and then covering IMPORT/STORE/SHOP/WOO, PRICE and MPI. Avoid trying to implement all domains in one Work run.
3. Run **Phase 0V**, using a native isolated PG17 test environment, when that infrastructure is actually available; keep provider certification as a separate honestly tracked release gate.
4. Approve the relevant ADRs, then authorize **Phase 1A** under the master contract. Do not approve changes to actual prices, plans or privacy retention just because the architectural owner is Python.

## Ready-to-paste GPT Work prompt — Phase 0R (documents only)

> Review `docs/keel-integration/` from the supplied Phase 0 package against the existing Node read-only reference and the current reviewed Python post-Task-6 working snapshot. Your task is a **source-trace and architecture-decision refinement**, not implementation.
>
> Preserve the Phase 0 analysis, but close these specific deficiencies:
>
> 1. Confirm exact source commit/content manifest and identify any delta from the Phase 0 audited Python snapshot. Do not reset or change either source tree.
> 2. In `CAPABILITY_TRACEABILITY.csv`, **78 business rows contain a Node domain-source fallback and 43 a Python fallback**. For each relevant capability, trace active entrypoint to the exact called helpers, DTOs, dependent SQL/read/write, RLS policy/function, metering and any worker or provider path. Replace generic fallback evidence with exact references where verified. Mark unclosed edges `UNRESOLVED`, with reason and downstream risk. Do not mark a feature equivalent because filenames match or both have a route.
> 3. The existing `db_objects` values are lexical candidates, not validated schema objects. Add a separate verified schema-lineage table for each feature, documenting real table/column/constraint/index/RLS policy/function/trigger/migration and ownership evidence. Remove parser noise from authoritative mappings; retain the raw lexical index separately as nonauthoritative evidence.
> 4. Create an **owner decision worksheet** for the 13 ADRs: side-by-side current behavior, actual mutually exclusive options, technically recommended architecture, consequences for existing tenants, exact business question requiring owner approval, and immutable approval status `PENDING` until the owner responds. Do not invent rates, plan limits, currency conversion rules, renewal terms, usage-charge policy or retention obligations.
> 5. Verify that every requested domain is traced through real frontend→API→auth/entitlement→service→worker/provider→database→read model→dashboard flows, including error/retry/dedup paths. Record missing joins and exact next validation procedures. For pricing preserve both single and bulk routes; for MPI preserve BUSINESS/PRODUCT/COMPETITOR and eligible sample semantics; for stores preserve credential security/webhooks/orders/refunds/inventory and canonical promotion; for billing preserve plans, promocodes, custom quote/dashboard and payment activation semantics.
> 6. Update only `docs/keel-integration/**`, reconcile **every added/modified/deleted documentation file** against Git diff in `UNIFIED_FILE_CHANGE_LEDGER.md`, and give a concise status by domain: `TRACE READY FOR IMPLEMENTATION REVIEW` or `BLOCKED`, with exact unresolved ID, evidence, and pending owner decisions.
>
> **Prohibitions:** No Node modifications, Python production changes, new migrations, AI algorithm changes, frontend source changes, live provider calls, credential harvesting, destructive DB operations, commits, pushes or deployment. Do not claim native PostgreSQL tests or Stripe/Shopify/Woo E2E passed unless they were actually executed with logged evidence. If native testing is unavailable, preserve the blocker and continue independent source trace work.
>
> Stop after documents and report. Phase 1 remains unauthorized.

**Note:** Because the source-trace task is large, execute it as bounded batches if needed (first AUTH/ENT/SUB/PROMO/CUSTOM, then IMPORT/STORE/SHOP/WOO, then PRICE/MPI). Preserve the same capability IDs and one change ledger across batches; do not relabel incomplete entries as done.
