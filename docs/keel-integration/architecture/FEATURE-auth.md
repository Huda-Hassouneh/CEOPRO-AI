> Phase 0R: read [SOURCE_TRACE_CORRECTIONS.md](../SOURCE_TRACE_CORRECTIONS.md) and [PHASE0R_README.md](../PHASE0R_README.md) before relying on original source-inference wording. Native/runtime gates remain pending.

# Feature architecture — auth

Status: PROPOSED for architecture review; capability families AUTH and PLATFORM. Single Python authority is already approved by user; no conflicting policy is selected.


Current Node chain: `backend/src/app.ts` → `modules/auth/route/auth.route.ts` → auth.controller.ts → auth.service.ts (`register`, `confirmEmail`, `issueSession`) → auth.repo.ts → Prisma plus transaction-local tenant context. `authenticateUser` validates stored active sessions; `requireTenant`/`requirePermission` query memberships. Platform routes separately require validatePlatformUser.ts. Pending signup is not a live user/company yet.

Current Python chain: frontend authApi/authHttpAdapter/authContracts → `/auth/*` → `routers/auth.py` (`login`, `signup`, `refresh`, reset/verification/invitation handlers) → `db.auth_lookup_connection`/security helpers and SQL auth lookup/join functions. `core/security.py::get_tenant_context` verifies HS256/exp, user_id/tenant_id, optional jti revocation and email-verification claim; it does not itself query active membership. `db.app_role_connection` uses the restricted tenant pool and resets transaction context after commit/rollback. Python signup inserts the company, user and owner membership before email confirmation; do not transplant Node pending tables blindly.

Python preserves workspace list/switch/create, existing role keys, password hashing, verification/reset, per-person/per-tenant trial eligibility and auth_time session age. Role mutation and invitation entrypoints are in `routers/settings.py`; latest owner, pending seats and invitation consumption are concurrency cases, not just UI checks. Existing Redis revocation is explicitly fail-open on outage, a security/availability decision (AUTH-001).

Target: one Python identity; a shared active-principal/tenant membership policy used at HTTP and job execution. Tenant roles retain Python's accountant and other supported roles. Add platform permissions under the same users; do not grant all tenant owners global access. Operator HTTP wraps existing billing.admin with server-derived actor and reason; retain CLI automation separately and audit it. Fresh `approved_by` strings from a browser are never authority.

SQL: audit users/tenant_users/companies, password_reset_tokens/email_verification tokens/codes, tenant invitations, plus lookup SECURITY DEFINER functions. `db.py::auth_lookup_connection` and migrations 20260915020000, 20260919000000, 20261011000000/100, and 20261020000000 auth_join_tenant are the Python bootstrap dependencies. Compare Node break_auth_rls_recursion migrations and platform cycle fixes; port intent, not SQL policy text. Native tests must reject revoked memberships, platform escalation and users/tenant_users recursion without a superuser/BYPASSRLS runtime role.

API compatibility: keep existing Python Bearer token shape, auth 409 workspace-choice flow, X-Auth-Reason and frontend sessionKeeper. If JWT issuer/audience enforcement is added, stage issuer changes with an explicitly approved token-renewal transition. No Node-issued token bridge by default. AUTH-001 controls creation/verification and revocation policy; AUTH-002 controls operator permission scope and support actions.

Proposed new files: `core/authorization.py`, `routers/platform_admin.py`, `billing/platform_service.py`; additive permission/audit migration. Endpoints expose bounded platform reads/mutations only after policy approval, with typed DTOs. Notifications for required offers use an audited outbox, not direct arbitrary cross-tenant messages.


## Verification and migration gate

Use domain rows in CAPABILITY_TRACEABILITY.csv, exact symbols in evidence/FUNCTION_CALL_INDEX.csv, and ordered SQL_OBJECT_LINEAGE.csv. Phase-specific schema/file scopes and disable strategy are in IMPLEMENTATION_PHASES.md. All applicable AT IDs require native tenant/RLS, service, HTTP, worker and frontend proof; source-level parity is not a passing test. No destructive backfill or existing customer change is authorized by this note.


## Authorized Phase 1A update

Current behavior, exact active Node/Python trace and compatibility are in [PHASE1A_TRACE_MAP.md](../PHASE1A_TRACE_MAP.md) and [PHASE1A_IMPLEMENTATION_REPORT.md](../PHASE1A_IMPLEMENTATION_REPORT.md). The earlier flow text describes the supplied baseline. This phase changes pending signup, fail-closed revocation and platform authority only within the approved policies; native integration remains blocked.
