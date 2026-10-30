> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

# Next handoff — Phase 1A is not authorized

**Current verdict: BLOCKED.** This file defines prerequisites and a proposed Phase 1A scope for later approval. It is not an instruction to implement now.

## Single next bounded Work task

Execute **Phase 0V environment/baseline unblock and native foundation verification** only. Preserve Python HEAD `1de393c77dfc6db9d8722d8a611d2384d64d12c0` plus the exact supplied Task 6 working manifest and all 13 selected ADRs. The authorized team must first review and establish a clean post-Task-6 source commit (provide SHA/full diff/manifest; do not ask Work to manufacture it). Provide an isolated native PG17/pgvector Docker-capable environment with repository-declared Python auth/worker test dependencies. Inspect the existing guard and Compose again before connecting. Run the existing migration runner on disposable empty/populated historical fixtures and repeat; enumerate applied counts and failures, export effective role/RLS/owner/ACL catalogs and close the 23 dynamic SQL obligations. Run integration_review --database and independent-session quota/report/webhook/current-subscription races; map and close any missing capacity/seat/source coverage. Rerun auth/workers/frontend checks with exact logs. Report defects without source fixes. Keep provider certification separate. Never use shared DBs, live customer secrets, PGlite/parser substitutes, or commits/push/deployment. Return BLOCKED if any required native/source gate is missing.

This task currently blocks Phase 1A; no feature port or production migration is allowed as part of it.

## Proposed Phase 1A scope — subject to later explicit authorization

Capabilities: **AUTH-001..AUTH-013 and PLATFORM-001 only**. Acceptance IDs: **AT-AUTH-001..AT-AUTH-013, AT-PLATFORM-001**, plus existing auth, billing/usage consistency, native RLS and tenant-bootstrap regressions. Reuse exact source roots/caller/DTO/DDL traces in CAPABILITY_TRACEABILITY.csv and evidence/phase0r/. Re-evaluate proposed scopes against the eventual reviewed commit; do not import Node sessions or create a competing identity/platform authority.

Policy prerequisites already selected: AUTH-001 signup B (pending registration; permanent identity/company/workspace after email verification) plus revocation A (fail closed for protected operations); AUTH-002 platform A (strict platform versus tenant roles, exceptional financial/spend powers only for Platform Owner). Existing users/memberships/session compatibility, trial eligibility and historical commercial rights must survive. Selected policy is not implementation permission or a global revocation of current rights.

Existing paths proposed for narrow review/edit **only after permission**:

- backend/src/ai/core/security.py — authoritative Python JWT/revocation/principal checks; preserve refresh/auth_time/reset semantics.
- backend/src/ai/routers/auth.py — pending new registration and single-use verification/invitations with existing contracts.
- backend/src/ai/routers/settings.py — shared principal/member checks where needed; preserve tenant-team scope.
- backend/src/ai/db.py — tenant/bootstrap context boundaries; preserve active-human membership RLS/service exception protections.
- frontend/src/features/auth/api/authContracts.js and frontend/src/features/auth/permissions/rolePermissions.js — only if exact existing client contracts need a compatible, expressly authorized update.

Proposed additions: backend/src/ai/core/authorization.py; backend/tests/keel_integration/test_authorization.py; backend/tests/keel_integration/test_auth_rls.py. Proposed migration identifier from IMPLEMENTATION_PHASES.md: **20261025000100_integration_principal_permissions.sql**, not created or applied. Its exact forward-only pending-registration/platform-grant and safe bootstrap/RLS design must be reviewed against existing schema, native catalogs, auth-token tables and approved policy before approval; no second user/session/tenant authority. Numeric rollout values must be approved where material and not fabricated.

Excluded: Node and its AI subtree; Python inference/models/algorithm or worker changes; commercial catalog, prices, trial rules, promo/quote activation, Data/AI Credits/provider-cost accounting, source/stock reconciliation, pricing/MPI thresholds, privacy erasure or unrelated UI. Platform management dashboards/financial operations beyond PLATFORM-001 belong to later bounded slices. Preserve the five Task 6 source fixes and report-key migration unchanged unless separately authorized.

## Mandatory acceptance before a later Phase 1A completion

- Authenticated/anonymous/wrong-role/cross-tenant/removed/suspended/expired/revoked identities; protected requests fail closed during revocation-store outage, with defined outage response and safe refresh/session compatibility.
- Concurrent duplicate signup/verification and last-owner membership transitions; one-use/expired/reset/invitation tokens; no RLS recursion in login/bootstrap/service paths; verify customer-team versus platform invitations stay separate.
- Preserve existing login, refresh, reset, workspace switching, tenant exports/protection, JWT issuer/claims, billing history, credits and inference behavior. Existing contract tests plus genuine API→SQL→read model checks; frontend/browser contracts where changed.
- Platform staff permissions enforced server-side; tenant owner never becomes platform staff; exceptional financial/spend powers remain Platform Owner-only. Immutable audit and narrow function grants/search_path; runtime role cannot bypass RLS.
- Native migrations on empty/populated/repeat; runtime-role password login, effective ACL/RLS/owner comparisons, independent-connection concurrency and crash/retry behavior. Exact ledger reconciles all actual Git paths and tests. No skip becomes PASS.

## Explicit permissions still needed

Owner must separately authorize **one Phase 1A implementation task** naming precise writable backend/test/migration/frontend paths, accepted schema design and rollout safeguards. Any additional commercial/legal/destructive behavior is excluded. SOURCE-001/VERIFY-001/RUNTIME-001 must be closed with evidence; material pending details in OWNER_APPROVAL_RECONCILIATION.md remain gates for their affected future slices. Commits, pushes, merge and deployment require fresh explicit permission; none is granted here.
