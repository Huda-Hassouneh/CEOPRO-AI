# Source trace refinement — AUTH

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified AUTH lineage](../evidence/phase0r/SCHEMA_LINEAGE_AUTH.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: AUTH-001; AUTH-002

## AUTH-001 — Pending signup and duplicate email

Proposed behavior remains: Node registers a pending signup before identity; Python creates users/company/owner during signup. Preserve Python token ownership; approve creation timing and anti-enumeration response.

Acceptance specification: `AT-AUTH-001` — Concurrent same email; expired pending record; SMTP failure. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/register @ backend/src/modules/auth/route/auth.route.ts:186 | POST /auth/verification/resend @ backend/src/modules/auth/route/auth.route.ts:192. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/auth/service/auth.service.ts:117:1::register | backend/src/modules/auth/repo/auth.repo.ts:242:1::findPendingSignupByEmail | backend/src/modules/auth/repo/auth.repo.ts:246:1::createPendingSignup`.

**Schema/access:** public.pending_signups; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:230::signup | backend/src/ai/routers/auth.py:185::_insert_company`.

**Schema/access:** public.auth_tokens; public.billing_subscriptions; public.billing_trials; public.companies; public.tenant_plan_assignments; public.tenant_users; public.usage_plans; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-002 — Verification code consume and resend

Proposed behavior remains: Reuse Python verification and throttle; preserve Node one-use expiry semantics via tests.

Acceptance specification: `AT-AUTH-002` — Reused/expired code; resend cooldown. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/verify-email/confirm @ backend/src/modules/auth/route/auth.route.ts:199 | POST /auth/verification/exchange @ backend/src/modules/auth/route/auth.route.ts:205 | POST /auth/verification/resend @ backend/src/modules/auth/route/auth.route.ts:192. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/auth/service/auth.service.ts:212:1::confirmEmail | backend/src/modules/auth/service/auth.service.ts:241:1::exchangeVerificationCode | backend/src/modules/auth/service/auth.service.ts:178:1::resendVerification | backend/src/modules/auth/repo/auth.repo.ts:286:1::createAccountFromVerifiedSignup | backend/src/modules/auth/repo/auth.repo.ts:374:1::consumeEmailVerificationGrant`.

**Schema/access:** public.auth_sessions; public.companies; public.email_verification_grants; public.pending_signups; public.tenant_users; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/email/verify @ backend/src/ai/routers/auth.py:675 | POST /auth/email/resend-verification @ backend/src/ai/routers/auth.py:653 | POST /auth/password/verify-code @ backend/src/ai/routers/auth.py:607 | POST /auth/password/reset @ backend/src/ai/routers/auth.py:627. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:675::verify_email | backend/src/ai/routers/auth.py:653::resend_email_verification | backend/src/ai/routers/auth.py:553::_active_code_or_reject`.

**Schema/access:** public.auth_tokens

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-003 — Password login and tenant choice

Proposed behavior remains: Reuse Python login 409 workspace choice; never mint or accept Node session tokens.

Acceptance specification: `AT-AUTH-003` — Wrong password; removed membership; ambiguous workspace. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/login @ backend/src/modules/auth/route/auth.route.ts:69 | POST /auth/change-password @ backend/src/modules/auth/route/auth.route.ts:213 | POST /platform-admin/me/password @ backend/src/modules/owner-portal/route/owner.route.ts:65. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/auth/route/auth.route.ts:69:23::@callback:router.post:/login:69 | backend/src/modules/auth/service/login-membership.ts:12:1::selectLoginMembership | backend/src/modules/auth/repo/auth.repo.ts:39:1::findLoginMemberships | backend/src/utils/token.ts:81:1::verifyPassword`.

**Schema/access:** public.auth_sessions; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/login @ backend/src/ai/routers/auth.py:99 | GET /auth/workspaces @ backend/src/ai/routers/auth.py:364 | POST /auth/workspaces/switch @ backend/src/ai/routers/auth.py:380 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411 | POST /auth/refresh @ backend/src/ai/routers/auth.py:460. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:99::login | backend/src/ai/routers/auth.py:84::_fetch_user_memberships`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-004 — JWT lifetime issuer and audience boundary

Proposed behavior remains: Retain Python HS256 claims; inventory trusted issuers and internal service tokens; add explicit verifier constraints only with approved compatibility rollout.

Acceptance specification: `AT-AUTH-004` — Missing exp; wrong signature; wrong purpose/issuer. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/login @ backend/src/modules/auth/route/auth.route.ts:69 | POST /auth/verification/exchange @ backend/src/modules/auth/route/auth.route.ts:205 | REGISTERED_GUARD get(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:211 | REGISTERED_GUARD post(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:213 | REGISTERED_GUARD get(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:221 | REGISTERED_GUARD post(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:234 | REGISTERED_GUARD post(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:263 | REGISTERED_GUARD use(authenticateUser) @ backend/src/modules/business-recommendations/route.ts:14. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/utils/token.ts:25:1::generateAccessToken | backend/src/middleware/validators/validateUser.ts:9:1::authenticateUser`.

**Schema/access:** public.auth_sessions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/refresh @ backend/src/ai/routers/auth.py:460 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743 | POST /auth/login @ backend/src/ai/routers/auth.py:99 | POST /auth/workspaces/switch @ backend/src/ai/routers/auth.py:380 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411 | GET /alerts @ backend/src/ai/routers/alerts.py:15 | POST /alerts/read @ backend/src/ai/routers/alerts.py:36 | GET /auth/workspaces @ backend/src/ai/routers/auth.py:364 | POST /auth/logout @ backend/src/ai/routers/auth.py:452. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/core/security.py:147::create_access_token | backend/src/ai/core/security.py:73::get_tenant_context`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-005 — Refresh maximum session age

Proposed behavior remains: Reuse Python refresh and auth_time; preserve idle and maximum-age contracts.

Acceptance specification: `AT-AUTH-005` — Expired/revoked token; maximum age reached. NOT RUN as an implementation test.

**NODE entry and UI boundary:** Family entry boundary /auth/; exact atomic caller joins in phase0r/CALLER_ENTRY_JOINS.csv; do not treat family prefix as proven caller. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/utils/token.ts:33:1::generateRefreshToken`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No mounted refresh endpoint. generateRefreshToken is a utility; Node login returns refreshToken:null. Do not migrate an unused utility as an operational session flow.

**PYTHON entry and UI boundary:** POST /auth/refresh @ backend/src/ai/routers/auth.py:460. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:460::refresh | backend/src/ai/core/security.py:169::session_age_seconds`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-006 — Logout and session revocation outage

Proposed behavior remains: Python Redis revocation fails open; Node validates stored active sessions. Decide outage/availability policy before hardening.

Acceptance specification: `AT-AUTH-006` — Redis unavailable; replay logged-out token. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/logout @ backend/src/modules/auth/route/auth.route.ts:234 | REGISTERED_GUARD get(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:211 | REGISTERED_GUARD post(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:213 | REGISTERED_GUARD get(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:221 | REGISTERED_GUARD post(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:234 | REGISTERED_GUARD post(authenticateUser) @ backend/src/modules/auth/route/auth.route.ts:263 | REGISTERED_GUARD use(authenticateUser) @ backend/src/modules/business-recommendations/route.ts:14. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/auth/route/auth.route.ts:238:3::@callback:router.post:/logout:238 | backend/src/middleware/validators/validateUser.ts:9:1::authenticateUser`.

**Schema/access:** public.auth_sessions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/logout @ backend/src/ai/routers/auth.py:452 | POST /auth/workspaces/switch @ backend/src/ai/routers/auth.py:380 | DELETE /settings/company @ backend/src/ai/routers/settings.py:336 | GET /alerts @ backend/src/ai/routers/alerts.py:15 | POST /alerts/read @ backend/src/ai/routers/alerts.py:36 | GET /auth/workspaces @ backend/src/ai/routers/auth.py:364 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:452::logout | backend/src/ai/core/security.py:127::revoke_token | backend/src/ai/core/security.py:139::is_token_revoked`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-007 — Forgot reset and password change

Proposed behavior remains: Reuse Python token hashing, expiry, password validation; verify reset invalidates all intended existing sessions.

Acceptance specification: `AT-AUTH-007` — Account enumeration; token replay; concurrent consume. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/change-password @ backend/src/modules/auth/route/auth.route.ts:213. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/auth/service/auth.service.ts:297:1::changePassword | backend/src/modules/auth/repo/auth.repo.ts:211:1::updatePassword`.

**Schema/access:** public.auth_sessions; public.users

**Missing/unequal edge:** Password-forgot/verify-code/reset endpoints in authContracts.js are placeholders with no matching mounted server handlers. Only authenticated change-password is implemented here.

**PYTHON entry and UI boundary:** POST /auth/password/forgot @ backend/src/ai/routers/auth.py:574 | POST /auth/password/verify-code @ backend/src/ai/routers/auth.py:607 | POST /auth/password/reset @ backend/src/ai/routers/auth.py:627 | POST /settings/security/change-password @ backend/src/ai/routers/settings.py:746. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:574::forgot_password | backend/src/ai/routers/auth.py:607::verify_reset_code | backend/src/ai/routers/auth.py:627::reset_password | backend/src/ai/routers/settings.py:746::change_password`.

**Schema/access:** public.auth_tokens; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-008 — Invitation expiry and accept

Proposed behavior remains: Preserve Python tenant team invitation/seat flow and separately implement approved Node platform-admin invitation semantics; these are different recipient/authority domains.

Acceptance specification: `AT-AUTH-008` — Expired invitation; revoked invite; last seat race. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /auth/invitations/:token @ backend/src/modules/auth/route/auth.route.ts:251 | POST /auth/invitations/:token/accept @ backend/src/modules/auth/route/auth.route.ts:263 | POST /platform-admin/admin-team/new/invite @ backend/src/modules/owner-portal/route/owner.route.ts:25. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/owner-portal/service/owner-write.service.ts:289:1::invitationDetails | backend/src/modules/owner-portal/service/owner-write.service.ts:317:1::acceptInvite | backend/src/modules/owner-portal/service/owner-write.service.ts:122:1::createInvite`.

**Schema/access:** public.audit_logs; public.companies; public.platform_invitations; public.tenant_users; public.users

**Missing/unequal edge:** invitationDetails/acceptInvite operate platform_invitations and require platform business_type; not equivalent to tenant team seat invitations.

**PYTHON entry and UI boundary:** POST /settings/team/invitations @ backend/src/ai/routers/settings.py:573 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/settings.py:573::invite_team_member | backend/src/ai/routers/settings.py:543::_ensure_seat_for_invitation | backend/src/ai/routers/auth.py:743::accept_invitation`.

**Schema/access:** public.auth_tokens; public.billing_trials; public.companies; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-009 — Role changes and last owner

Proposed behavior remains: Keep Python owner/admin/accountant and other existing roles; extend permissions rather than replacing with Node enum.

Acceptance specification: `AT-AUTH-009` — Two simultaneous owner demotions; admin escalation. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/admin-team/:id/role @ backend/src/modules/owner-portal/route/owner.route.ts:30 | POST /platform-admin/admin-team/:id/status @ backend/src/modules/owner-portal/route/owner.route.ts:35 | POST /platform-admin/admin-team/:id/remove @ backend/src/modules/owner-portal/route/owner.route.ts:40 | POST /platform-admin/admin-team/:id/resend @ backend/src/modules/owner-portal/route/owner.route.ts:45 | POST /platform-admin/admin-team/:id/cancel @ backend/src/modules/owner-portal/route/owner.route.ts:50 | POST /platform-admin/users/:id/status @ backend/src/modules/owner-portal/route/owner.route.ts:22. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/owner-portal/service/owner-write.service.ts:194:1::updateTeam | backend/src/modules/owner-portal/service/owner-write.service.ts:77:1::updateCustomerUser`.

**Schema/access:** public.audit_logs; public.companies; public.platform_invitations; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** PATCH /settings/team/members/{tenant_user_id} @ backend/src/ai/routers/settings.py:651 | DELETE /settings/team/members/{tenant_user_id} @ backend/src/ai/routers/settings.py:698. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/settings.py:651::update_team_member_role | backend/src/ai/routers/settings.py:698::remove_team_member | backend/src/ai/routers/settings.py:637::_count_active_owners`.

**Schema/access:** public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-010 — Workspace list switch and creation

Proposed behavior remains: Preserve Python workspaces/current membership selection and max-owned-workspace controls.

Acceptance specification: `AT-AUTH-010` — Cross-tenant switch; removed owner; concurrent workspace creation. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /auth/me @ backend/src/modules/auth/route/auth.route.ts:211. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/auth/service/auth.service.ts:259:1::me | backend/src/modules/auth/repo/auth.repo.ts:92:1::findActiveMemberships`.

**Schema/access:** public.tenant_users; public.users

**Missing/unequal edge:** me returns memberships, but no mounted workspace switch/create flow matching Python is established; Node login chooses selectLoginMembership.

**PYTHON entry and UI boundary:** GET /auth/workspaces @ backend/src/ai/routers/auth.py:364 | POST /auth/workspaces/switch @ backend/src/ai/routers/auth.py:380 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:364::list_workspaces | backend/src/ai/routers/auth.py:380::switch_workspace | backend/src/ai/routers/auth.py:411::create_workspace`.

**Schema/access:** public.billing_subscriptions; public.billing_trials; public.companies; public.tenant_plan_assignments; public.tenant_users; public.usage_plans; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-011 — Activation suspended tenant and revoked member

Proposed behavior remains: Preserve Python SQL get_current_tenant removed_at human-membership enforcement plus documented nil-UUID service actor. Evaluate Node stronger company/member suspension/platform-status and boundary diagnostics without adding second membership authority.

Acceptance specification: `AT-AUTH-011` — JWT minted before removal/suspension; paid tenant still suspended. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD get(requireTenant) @ backend/src/modules/auth/route/auth.route.ts:211 | REGISTERED_GUARD post(requireTenant) @ backend/src/modules/auth/route/auth.route.ts:213 | REGISTERED_GUARD get(requireTenant) @ backend/src/modules/auth/route/auth.route.ts:221 | REGISTERED_GUARD post(requireTenant) @ backend/src/modules/auth/route/auth.route.ts:234 | REGISTERED_GUARD post(requireTenant) @ backend/src/modules/auth/route/auth.route.ts:263 | REGISTERED_GUARD use(requireTenant) @ backend/src/modules/business-recommendations/route.ts:14 | REGISTERED_GUARD get(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:30 | REGISTERED_GUARD post(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:40 | REGISTERED_GUARD delete(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:49 | REGISTERED_GUARD patch(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:59 | REGISTERED_GUARD use(requirePlatformRole) @ backend/src/modules/features/route/features-management.route.ts:22 | REGISTERED_GUARD use(requirePlatformRole) @ backend/src/modules/platform-admin/route/platform-admin.route.ts:88. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/subscription/repo/user-tenant.repo.ts:5:1::getActiveTenantUser | backend/src/middleware/validators/validateUser.ts:80:1::requireTenant | backend/src/middleware/validators/validatePlatformUser.ts:51:1::requirePlatformRole`.

**Schema/access:** public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /alerts @ backend/src/ai/routers/alerts.py:15 | POST /alerts/read @ backend/src/ai/routers/alerts.py:36 | GET /auth/workspaces @ backend/src/ai/routers/auth.py:364 | POST /auth/workspaces/switch @ backend/src/ai/routers/auth.py:380 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411 | POST /auth/logout @ backend/src/ai/routers/auth.py:452 | PATCH /settings/team/members/{tenant_user_id} @ backend/src/ai/routers/settings.py:651 | DELETE /settings/team/members/{tenant_user_id} @ backend/src/ai/routers/settings.py:698 | POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/core/security.py:73::get_tenant_context | backend/src/ai/routers/settings.py:625::_fetch_active_member | backend/src/ai/db.py:87::app_role_connection`.

**Schema/access:** public.tenant_users

**Missing/unequal edge:** core/security decodes context; human removed_at protection already exists in SQL get_current_tenant (20260928000000). Node platform_status/company suspension is not an equivalent Python column/gate.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-012 — Login bootstrap RLS lookup

Proposed behavior remains: Reuse Python auth_lookup_connection and auth SQL functions; audit fixed search_path/grants and recursion under ceopro_app.

Acceptance specification: `AT-AUTH-012` — User lookup before tenant; recursive users/tenant_users policy. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/login @ backend/src/modules/auth/route/auth.route.ts:69 | POST /auth/register @ backend/src/modules/auth/route/auth.route.ts:186 | POST /auth/verification/resend @ backend/src/modules/auth/route/auth.route.ts:192 | POST /auth/verify-email/confirm @ backend/src/modules/auth/route/auth.route.ts:199. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/modules/auth/repo/auth.repo.ts:7:1::findUserByEmail | backend/src/modules/auth/repo/auth.repo.ts:39:1::findLoginMemberships | backend/src/modules/auth/repo/auth.repo.ts:137:1::createTenantAccount`.

**Schema/access:** public.companies; public.tenant_users; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/password/forgot @ backend/src/ai/routers/auth.py:574 | POST /auth/email/resend-verification @ backend/src/ai/routers/auth.py:653 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743 | POST /auth/login @ backend/src/ai/routers/auth.py:99 | POST /auth/password/verify-code @ backend/src/ai/routers/auth.py:607 | GET /auth/workspaces @ backend/src/ai/routers/auth.py:364 | POST /auth/workspaces/switch @ backend/src/ai/routers/auth.py:380 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411 | POST /auth/refresh @ backend/src/ai/routers/auth.py:460. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/routers/auth.py:60::_fetch_user_by_email | backend/src/ai/routers/auth.py:84::_fetch_user_memberships | backend/src/ai/db.py:146::auth_lookup_connection`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## AUTH-013 — Identity migration compatibility

Proposed behavior remains: Do not bulk copy Node password/session records; inventory hashes, collisions, consent and invitation history then approve explicit migration/cutover.

Acceptance specification: `AT-AUTH-013` — Existing Python/Node duplicate email; old sessions; no user lockout. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /auth/login @ backend/src/modules/auth/route/auth.route.ts:69 | POST /auth/change-password @ backend/src/modules/auth/route/auth.route.ts:213 | POST /platform-admin/me/password @ backend/src/modules/owner-portal/route/owner.route.ts:65 | POST /auth/register @ backend/src/modules/auth/route/auth.route.ts:186 | POST /auth/verify-email/confirm @ backend/src/modules/auth/route/auth.route.ts:199. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/auth/api/authContracts.js; owner-portal invitations via /auth/invitations.

**Exact source roots:** `backend/src/utils/token.ts:81:1::verifyPassword | backend/src/utils/token.ts:77:1::hashPassword | backend/src/modules/auth/repo/auth.repo.ts:286:1::createAccountFromVerifiedSignup`.

**Schema/access:** public.companies; public.email_verification_grants; public.pending_signups; public.tenant_users; public.users

**Missing/unequal edge:** No existing cross-repository identity/password/session migration flow; hashes alone do not establish collision/consent/cutover behavior.

**PYTHON entry and UI boundary:** POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/password/reset @ backend/src/ai/routers/auth.py:627 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743 | POST /settings/security/change-password @ backend/src/ai/routers/settings.py:746 | POST /auth/login @ backend/src/ai/routers/auth.py:99. UI: frontend/src/features/auth/api/authHttpAdapter.js; frontend/src/features/settings/api/teamApi.js; workspacesApi.js.

**Exact source roots:** `backend/src/ai/core/security.py:205::hash_password | backend/src/ai/core/security.py:214::verify_password | backend/src/ai/routers/auth.py:230::signup`.

**Schema/access:** public.auth_tokens; public.billing_subscriptions; public.billing_trials; public.companies; public.tenant_plan_assignments; public.tenant_users; public.usage_plans; public.users

**Missing/unequal edge:** No cross-repository identity migration flow; native identity/collision inventory and owner cutover decision needed.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
