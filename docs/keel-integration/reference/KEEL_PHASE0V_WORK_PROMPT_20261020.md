# KEEL — Phase 0V: Approved ADR Reconciliation and Native Foundation Verification

## Goal
Finalize the Phase 0R architecture handoff against the owner's **13 explicitly selected policies**, establish an unambiguous reviewed post-Task-6 Python source baseline, and independently verify the existing Python billing/auth/usage foundation on disposable **native PostgreSQL 17**. **This task does not authorize feature implementation, production code changes, migration application to shared databases, deployment, commits, or pushes.**

## Inputs (must be available)
1. `KEEL_Phase0R_Architecture_Review.zip` (complete `docs/keel-integration/` package, including `NEXT_TASK.md`, `IMPLEMENTATION_PHASES.md`, all ADRs, evidence indexes, capability/acceptance matrices and `UNIFIED_FILE_CHANGE_LEDGER.md`).
2. `KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md` (all 13 owner selections; authoritative for their approved policy direction, with outstanding specifics explicitly pending).
3. The **actual post-Task-6 Python working tree**, its full changes/diff and Task 6 verification report, ideally the authorized reviewed clean source commit. This is the implementation destination.
4. `my-version(1).zip` Node.js reference, **read-only**.
5. The original integration master contract, if available.

**Source identity is a hard gate:** Phase 0R recorded Python HEAD `1de393c77dfc6db9d8722d8a611d2384d64d12c0` *plus uncommitted Task 6 changes*, and documented the audited archive SHA-256 `873cc27c3d98a9a061a843d4a63948ac7db178555c4c8757fbee31c59b2285e7`. Earlier `main-repo(1).zip` is an **older snapshot** and must not be substituted. Validate the supplied source against the manifests; if it differs, report exact differences, affected traces and what requires review. Never manufacture a commit or silently drop incoming modifications.

## Required work

### A. Reconcile all owner decisions — documentation only
- For AUTH-001, AUTH-002, CATALOG-001, ENT-001, PROMO-001, CUSTOM-001, CUSTOM-002, TRANSITION-001, IMPORT-001, PRICE-001, MPI-001, ACCOUNTING-001, PRIVACY-001, update the matching ADR and owner worksheet to record exactly the owner's approved choice, preserving original source comparison, selected technical architecture, dependencies, risks and applicable acceptance cases.
- Record the approval as **architecture/business policy only**. **Do not** reinterpret it as approval for implementation, deployment, pricing changes, revocation of existing rights or destruction of data.
- Keep each unresolved numeric, legal and operational setting marked `PENDING`, including: quote margins/fees/rates/rounding/expiry/renewals; individual promo terms; grandfathering impacts; pricing observation freshness and invalid-most-recent handling; MPI minimum/sample cap/recency; per-feature accounting units and adjustment limits; ambiguous import key conflicts; manual versus Stripe exception details; Shopify fields, retention, jurisdiction and legal exceptions.
- Preserve Python's sole identity/Stripe/entitlement/credit/canonical-data authorities and Python-only behavior; Node stays read-only.
- Maintain an updated architecture decision status matrix and reconcile every documentation edit with the unified per-file change ledger and actual Git diff.

### B. Establish source/baseline provenance
- Record both repositories' exact input hashes, approved source commit (if one has genuinely been reviewed and created through the team workflow), `git status`, staged/unstaged/untracked changes and the Task 6 delta. Review all Task 6 fixes, related migration and tests against expected behavior; do not assert that prior test counts prove runtime correctness.
- If the post-Task-6 state is still uncommitted, identify its exact file list and ask for the authorized team's review/commit; **do not commit, reset, rebase, overwrite or merge without explicit permission**.
- If the correct Python source is not supplied, complete only the ADR reconciliation and report `SOURCE-001 BLOCKED`. Do not continue native verification against the older source or mark Phase 0V completed.

### C. Phase 0V native verification — only with an isolated disposable PostgreSQL 17 instance
- Use the repository's guarded test environment (inspect `backend/tests/billing/docker-compose.yml` and its guarded runner before executing). Reject any production/staging/shared database URLs, production Stripe credentials or other live customer secrets. If the disposable environment cannot be proven isolated, stop and report the blocker; never use a shared database as a substitute.
- Exercise fresh migrations, repeat/idempotent migration behavior and migration against a populated disposable historical fixture, including Task 6 report-key/period evolution. Inspect the actual effective database catalog: runtime-role login, `ceopro_app` RLS and grants, tenant context isolation, policies/functions/owners and 23 identified dynamic SQL obligations. Merely parsing migration text is insufficient.
- Run real, multi-connection PostgreSQL concurrency tests for last-unit quota/capacity reservations, report keys bound to actor/period, duplicate/reordered Stripe invoice events, and stale old/new subscription transitions; run existing auth, entitlement, billing and relevant worker regressions.
- Run the existing guarded `integration_review --database` suite when safe, plus applicable backend tests, frontend tests and build. Log exact command, environment description, version, pass/fail/skip, and captured evidence paths. Stripe TEST, Shopify and WooCommerce live/sandbox flows are **separate provider certification gates**; never claim them verified if not run.
- Never apply new production migrations or introduce new production functionality as part of this task. If verification exposes a defect, record a precise defect report and a recommended minimal corrective task; do not quietly fix source code.

### D. Final deliverables
Provide all updated files under `docs/keel-integration/`:
1. `OWNER_APPROVAL_RECONCILIATION.md`: 13 selected policies and every PENDING subdecision, with links to matching ADRs.
2. `SOURCE_BASELINE_VERIFICATION.md`: exact source fingerprints, commit/diff provenance, Task 6 file and migration inventory, and comparison result.
3. `PHASE0V_NATIVE_VERIFICATION.md`: DB build/versions/isolation, commands, outcomes, logs, failed/skipped tests, schema/RLS/concurrency evidence and blocking issue IDs.
4. Updated ADRs, owner worksheet, `DOMAIN_READINESS.md`, dependency/trace reports affected by verified facts, and `UNIFIED_FILE_CHANGE_LEDGER.md` reconciled against the actual Git diff.
5. `NEXT_IMPLEMENTATION_HANDOFF.md`: exact prerequisites for **Phase 1A only**, including AUTH-001..013 and PLATFORM-001, proposed file scopes/migration, acceptance test IDs, features preserved, blockers and explicit owner permissions still needed.

## Completion and safety gates
- **Do not start Phase 1A or any feature port.** Do not modify Node source, Python production source/models/workers/frontend or live schemas.
- Do not silently change current Python plan prices, trials, capacities, historical contracts, Data/AI Credit accounting, or invoices.
- Treat unexecuted, skipped or provider-mocked tests as not verified. Report `READY FOR PHASE 1A APPROVAL REVIEW` only if the correct clean/reviewed source baseline, required native foundation checks, and relevant ADR decisions are sufficiently established. Otherwise return `BLOCKED` with numbered reasons and the exact minimal next actions.
- Do not commit, push, merge or deploy without fresh explicit permission. Do not ask the owner to reapprove settled policy selections; ask only about truly unresolved decisions when needed.

End with a concise summary of: what was verified, exact unchanged/modified file sets, what remains blocked, and the **single next bounded task**. 
