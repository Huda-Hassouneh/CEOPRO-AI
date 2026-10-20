> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

> **Phase 0V — BLOCKED:** exact supplied Task 6 content and 13 selected policies verified; clean reviewed commit/native PG17/full runtime regression gates remain open. Read [SOURCE_BASELINE_VERIFICATION.md](SOURCE_BASELINE_VERIFICATION.md), [PHASE0V_NATIVE_VERIFICATION.md](PHASE0V_NATIVE_VERIFICATION.md) and [NEXT_IMPLEMENTATION_HANDOFF.md](NEXT_IMPLEMENTATION_HANDOFF.md). No production implementation authorized.

> **Owner update — 2026-10-20:** 13/13 architecture policy directions are now SELECTED. Earlier statements below that all ADRs are pending are historical and superseded by [DECISION_REGISTER.md](DECISION_REGISTER.md) and [OWNER_RECONCILIATION_REPORT.md](OWNER_RECONCILIATION_REPORT.md). Explicit detailed values/legal/operational rules remain PENDING. Implementation remains NOT AUTHORIZED.

# Next Work task after Phase 0R

Phase 0R source/decision refinement is complete for review; Phase 1 remains unauthorized. Read OWNER_DECISION_WORKSHEET.md and SOURCE_TRACE_CORRECTIONS.md first. All 13 decisions are PENDING.

The supplied Python working bytes already contain Task 6 repairs and match the Phase 0 manifest; do not replace them with an older ZIP, reset, or rebase them away. Obtain/establish the reviewed clean post-Task-6 commit through the authorized team workflow, with full diff and source comparison. No commit was authorized or created in this task.

Then execute bounded Phase 0V with the existing guarded native disposable PG17 environment, actual schema/RLS/role catalog comparison, empty/populated/repeat migration and multi-session reservation/webhook/capacity tests. Preserve provider tests as separate release gates; no live credentials or fabricated results. Resolve the relevant owner worksheet selections before a bounded Phase 1A implementation task. Do not convert a source-ready trace or architecture recommendation into implementation permission.

The exact Phase 0V prompt retained below remains applicable, with the refined source/schema/decision tables replacing older filename/domain inferences. No new production source scope is authorized by this handoff.

---

# Exact next Work task — verification prerequisite, no implementation yet

Use this after the owner reviews the Phase 0 decision register. For a production implementation task, first provide an approved architecture decision selection and a clean post-Task-6 Python main commit.

```text
Continue KEEL Unified Python Integration under the supplied master contract and docs/keel-integration/ review pack.

This run is Phase 0V baseline verification only. Do not implement contested commercial policy or change production source/model/frontend/Node code.

Frozen supplied Python HEAD: 1de393c77dfc6db9d8722d8a611d2384d64d12c0 (main); this is NOT a verified post-Task-6 commit. The working archive contained five Task 6 production modifications and an untracked report-key migration/tests. Compare current approved post-Task-6 commit and full diff against evidence/SUPPLIED_CONTENT_HASHES.json and INPUT_ARCHIVE_HASHES.json. If different, identify exact changed capability paths and revise source traces before using old claims. Node remains strictly read-only and must match its input manifest.

1. Record reviewed clean base/current commit and exact incoming Task 6 changes; verify all seven repair rows in SOURCE_BASELINES.md, including request/actor/period/receipt rules and invalid amount rejection.
2. Provision only the dedicated disposable native PostgreSQL 17 test environment using backend/tests/billing/docker-compose.yml and the existing guarded runner. Run migration fresh/repeat and populated historical report-key upgrade, runtime ceopro_app password login/RLS/privileges, last-unit HTTP report/quota races, reordered/duplicate invoice events and old/new subscription assignment races. PGlite/SQLite/fakes are not native proof. No shared/production DSN or destructive seed.
3. Run existing guarded integration_review --database, full relevant baseline regressions and frontend tests/build. Record exact commands, runtime/DB versions, pass/fail/skip and logs. Test Stripe TEST only with authorized local test resources. If unavailable, preserve blockers honestly.
4. Reconcile runtime route/frontend/job/gate/write coverage against the static indexes, resolve dynamic/SQL terminal branches relevant to Phase 1, and update TRACE_BOUNDARIES/coverage maps with actual verification.
5. Update only integration architecture/evidence/ledger docs. Reconcile docs delta against actual clean Git baseline plus staged/unstaged/untracked paths. Do not claim a clean commit or passing native test if missing.
6. Return READY FOR REVIEW or BLOCKED with exact unresolved SOURCE-001/VERIFY-001/TRACE-001 IDs and the approved owner decisions still required. No commit/push/merge/deploy unless authorized.

Only after owner architecture approval and successful prerequisites, start bounded Phase 1A, with file scopes and AT-AUTH-* cases from IMPLEMENTATION_PHASES.md. Do not combine all phases in one patch.
```

## Owner review response template

Select the rules in each linked ADR rather than approving an unspecified “strongest” implementation. At minimum record AUTH-001, AUTH-002 and ENT-001/ACCOUNTING-001 before Phase 1; CATALOG-001/TRANSITION-001/PROMO-001/CUSTOM-001/CUSTOM-002 before billing; IMPORT-001 before canonical import/store accounting; PRIVACY-001 before Shopify privacy; PRICE-001/MPI-001 before respective policy changes. One approved authority architecture does not imply approval of altered prices, rights, retention or algorithm inputs.
