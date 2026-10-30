# Source trace refinement — PLATFORM

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified PLATFORM lineage](../evidence/phase0r/SCHEMA_LINEAGE_PLATFORM.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: AUTH-002; CATALOG-001

## PLATFORM-001 — Platform identity and permissions

Proposed behavior remains: Add platform operator membership/permission records under existing Python user IDs; tenant owner is not platform admin.

Acceptance specification: `AT-PLATFORM-001` — Tenant owner requests global companies; revoked operator; privilege escalation. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD get(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:30 | REGISTERED_GUARD post(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:40 | REGISTERED_GUARD delete(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:49 | REGISTERED_GUARD patch(requirePlatformRole) @ backend/src/modules/features/route/feature-plan.route.ts:59 | REGISTERED_GUARD use(requirePlatformRole) @ backend/src/modules/features/route/features-management.route.ts:22 | REGISTERED_GUARD use(requirePlatformRole) @ backend/src/modules/platform-admin/route/platform-admin.route.ts:88 | REGISTERED_GUARD get(requirePlatformPermission("billing.read")) @ backend/src/modules/features/route/feature-plan.route.ts:30 | REGISTERED_GUARD post(requirePlatformPermission("billing.manage")) @ backend/src/modules/features/route/feature-plan.route.ts:40 | REGISTERED_GUARD delete(requirePlatformPermission("billing.manage")) @ backend/src/modules/features/route/feature-plan.route.ts:49 | REGISTERED_GUARD patch(requirePlatformPermission("billing.manage")) @ backend/src/modules/features/route/feature-plan.route.ts:59 | REGISTERED_GUARD get(requirePlatformPermission("billing.read")) @ backend/src/modules/features/route/features-management.route.ts:26 | REGISTERED_GUARD get(requirePlatformPermission("billing.read")) @ backend/src/modules/features/route/features-management.route.ts:34. UI: frontend/src/features/platform-admin/api/platformAdminApi.js; platformBillingApi.js; routes.jsx.

**Exact source roots:** `backend/src/middleware/validators/validatePlatformUser.ts:51:1::requirePlatformRole | backend/src/middleware/validators/validatePlatformUser.ts:71:1::requirePlatformPermission`.

**Schema/access:** public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** PATCH /settings/company @ backend/src/ai/routers/settings.py:250 | POST /settings/company/onboarding/complete @ backend/src/ai/routers/settings.py:289 | GET /settings/company/export @ backend/src/ai/routers/settings.py:313 | DELETE /settings/company @ backend/src/ai/routers/settings.py:336 | PATCH /settings/company/search-scope @ backend/src/ai/routers/settings.py:412 | PUT /settings/company/target-markets @ backend/src/ai/routers/settings.py:475 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: No platform-admin frontend/router; settings UI is tenant-scoped; billing_admin.py is operator CLI.

**Exact source roots:** `backend/src/ai/routers/settings.py:74::_require_role | backend/src/ai/billing/admin.py:28::_require`.

**Schema/access:** public.tenant_users

**Missing/unequal edge:** No mounted platform identity/permission API. Tenant role guards and CLI input validation are not platform authorization.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PLATFORM-002 — Companies users overview and detail

Proposed behavior remains: Add bounded audited platform read services and UI with explicit grants, not ceopro_app broad RLS bypass.

Acceptance specification: `AT-PLATFORM-002` — Counts vs detail visibility; cross-tenant data minimization. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /platform-admin/overview @ backend/src/modules/owner-portal/route/owner.route.ts:6 | GET /platform-admin/companies @ backend/src/modules/owner-portal/route/owner.route.ts:7 | GET /platform-admin/companies/:id @ backend/src/modules/owner-portal/route/owner.route.ts:8. UI: frontend/src/features/platform-admin/api/platformAdminApi.js; platformBillingApi.js; routes.jsx.

**Exact source roots:** `backend/src/modules/owner-portal/service/owner-read.service.ts:136:1::overview | backend/src/modules/owner-portal/repo/owner.repo.ts:19:1::platformOverviewCounts | backend/src/modules/owner-portal/repo/owner.repo.ts:43:1::companiesPage | backend/src/modules/owner-portal/repo/owner.repo.ts:81:1::companyById`.

**Schema/access:** public.audit_logs; public.companies; public.plans; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /settings/company @ backend/src/ai/routers/settings.py:198 | GET /settings/team/members @ backend/src/ai/routers/settings.py:502. UI: No platform-admin frontend/router; settings UI is tenant-scoped; billing_admin.py is operator CLI.

**Exact source roots:** `backend/src/ai/routers/settings.py:198::get_company | backend/src/ai/routers/settings.py:502::list_team_members`.

**Schema/access:** public.companies; public.tenant_users; public.users

**Missing/unequal edge:** Tenant settings company/team queries are not global platform overview/companies/users services.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PLATFORM-003 — Catalog feature plan administration

Proposed behavior remains: Add authenticated operator endpoints around Python catalog maintenance with immutable price versioning.

Acceptance specification: `AT-PLATFORM-003` — Mutate historic price; disabled feature with active contracts. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/plans @ backend/src/modules/platform-admin/route/platform-admin.route.ts:105 | POST /subscription/plans/ @ backend/src/modules/subscription/route/plans.route.ts:28 | PATCH /platform-admin/billing/plans/:id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:111 | PATCH /subscription/plans/:id @ backend/src/modules/subscription/route/plans.route.ts:37 | PATCH /plans/:plan_id/features/:feature_id @ backend/src/modules/features/route/feature-plan.route.ts:59 | PATCH /platform-admin/billing/plans/:plan_id/features/:feature_id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:287 | PATCH /features/:id @ backend/src/modules/features/route/features-management.route.ts:59 | PATCH /platform-admin/billing/features/:id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:260. UI: frontend/src/features/platform-admin/api/platformAdminApi.js; platformBillingApi.js; routes.jsx.

**Exact source roots:** `backend/src/modules/subscription/service/plans.service.ts:352:1::createPlansService | backend/src/modules/subscription/service/plans.service.ts:428:1::updatePlansService | backend/src/modules/features/repo/plan-feature.repo.ts:24:17::planFeatureRepository.updateLimits | backend/src/modules/features/repo/feature.repo.ts:28:11::featureRepository.update`.

**Schema/access:** public.app_config; public.features; public.plan_features; public.plan_price_versions; public.plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.stripe_sync_catalog @ backend/scripts/stripe_sync_catalog.py:46 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: No platform-admin frontend/router; settings UI is tenant-scoped; billing_admin.py is operator CLI.

**Exact source roots:** `backend/src/ai/billing/catalog_sync.py:69::plan | backend/src/ai/billing/catalog_sync.py:111::apply | backend/src/ai/billing/admin.py:113::set_custom_contract`.

**Schema/access:** public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments

**Missing/unequal edge:** Catalog sync/CLI changes exist, but no platform authenticated plan/feature mutation dashboard/API.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PLATFORM-004 — Pricing costs controls credit adjustments

Proposed behavior remains: Wrap existing Python billing.admin functions in permissioned HTTP workflows; preserve CLI and entitlement_audit_log.

Acceptance specification: `AT-PLATFORM-004` — Customer sees provider cost; forged approved_by; duplicate adjustment. NOT RUN as an implementation test.

**NODE entry and UI boundary:** PATCH /platform-admin/billing/pricing-policy @ backend/src/modules/platform-admin/route/platform-admin.route.ts:199 | POST /platform-admin/billing/vendor-rates @ backend/src/modules/platform-admin/route/platform-admin.route.ts:206 | POST /subscription/custom-plans/vendor-rates @ backend/src/modules/subscription/route/custom-plan.route.ts:168 | POST /platform-admin/billing/infrastructure-rates @ backend/src/modules/platform-admin/route/platform-admin.route.ts:123 | POST /platform-admin/settings/new/update @ backend/src/modules/owner-portal/route/owner.route.ts:58. UI: frontend/src/features/platform-admin/api/platformAdminApi.js; platformBillingApi.js; routes.jsx.

**Exact source roots:** `backend/src/modules/platform-admin/controller/platform-admin.controller.ts:305:1::updatePlatformPricingPolicyHandler | backend/src/modules/subscription/service/custom-plan.service.ts:1101:1::createVendorRate | backend/src/modules/subscription/service/custom-plan.service.ts:1197:1::createInfrastructureRate | backend/src/modules/owner-portal/service/owner-write.service.ts:428:1::updateSettings`.

**Schema/access:** public.app_config; public.audit_logs; public.companies; public.features; public.infrastructure_rates; public.vendor_rates

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: No platform-admin frontend/router; settings UI is tenant-scoped; billing_admin.py is operator CLI.

**Exact source roots:** `backend/src/ai/billing/admin.py:46::set_price | backend/src/ai/billing/admin.py:88::set_control | backend/src/ai/billing/admin.py:194::adjust_credits`.

**Schema/access:** public.billing_trials; public.entitlement_audit_log; public.provider_cost_schedules; public.provider_spend_controls; public.tenant_credit_balances; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_ledger_adjustments; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** set_price/set_control/adjust_credits are implemented operator functions invoked by billing_admin CLI, not authenticated customer-facing HTTP.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PLATFORM-005 — Notifications audit and worker identity

Proposed behavior remains: Carry required offer/admin notifications with Python durable outbox and restricted worker identity; preserve existing Python notifications.

Acceptance specification: `AT-PLATFORM-005` — Actor vs service identity; retry; no SMTP configuration. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7 | POST /platform-admin/billing/custom-quotes/:id/send @ backend/src/modules/platform-admin/route/platform-admin.route.ts:185 | POST /subscription/custom-plans/quotes/:id/send @ backend/src/modules/subscription/route/custom-plan.route.ts:145 | POST /platform-admin/admin-team/new/invite @ backend/src/modules/owner-portal/route/owner.route.ts:25. UI: frontend/src/features/platform-admin/api/platformAdminApi.js; platformBillingApi.js; routes.jsx.

**Exact source roots:** `backend/src/modules/platform-notifications/platform-notification.producer.ts:13:1::paymentFailed | backend/src/modules/tenant-notifications/tenant-notification.producer.ts:11:1::customPlanOfferReady | backend/src/modules/owner-portal/service/owner-write.service.ts:122:1::createInvite`.

**Schema/access:** public.audit_logs; public.platform_invitations; public.platform_notification_outbox; public.tenant_notification_outbox; public.tenant_users; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/password/forgot @ backend/src/ai/routers/auth.py:574 | POST /settings/team/invitations @ backend/src/ai/routers/settings.py:573 | POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/email/resend-verification @ backend/src/ai/routers/auth.py:653 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: No platform-admin frontend/router; settings UI is tenant-scoped; billing_admin.py is operator CLI.

**Exact source roots:** `backend/src/ai/core/notifications.py:55::send_email | backend/src/ai/billing/admin.py:34::_audit`.

**Schema/access:** public.entitlement_audit_log

**Missing/unequal edge:** Existing notification helpers/audit preserved; no Node-style quote/platform notification outbox workflow.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
