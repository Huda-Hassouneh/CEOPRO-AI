# Source trace refinement — CUSTOM

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified CUSTOM lineage](../evidence/phase0r/SCHEMA_LINEAGE_CUSTOM.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: AUTH-002; CUSTOM-001; CUSTOM-002

## CUSTOM-001 — Configurator feature quantities

Proposed behavior remains: Add server-driven configurator to Python billing catalog; quantities in canonical feature units, monitoring cadence as configuration.

Acceptance specification: `AT-CUSTOM-001` — Unknown feature; omitted required dependency; zero/unlimited quantity. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /subscription/custom-plans/configurator @ backend/src/modules/subscription/route/custom-plan.route.ts:53 | POST /platform-admin/billing/custom-quotes @ backend/src/modules/platform-admin/route/platform-admin.route.ts:153 | PATCH /platform-admin/billing/custom-quotes/:id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:165 | POST /subscription/custom-plans/quotes @ backend/src/modules/subscription/route/custom-plan.route.ts:108 | PATCH /subscription/custom-plans/quotes/:id @ backend/src/modules/subscription/route/custom-plan.route.ts:122 | POST /subscription/custom-plans/preview @ backend/src/modules/subscription/route/custom-plan.route.ts:54 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-configurator.service.ts:336:1::getCustomPlanConfigurator | backend/src/modules/subscription/service/custom-plan.service.ts:101:1::validateQuoteFeatures | backend/src/modules/subscription/service/custom-plan-policy.service.ts:318:1::resolveAutomaticFeatureLimit`.

**Schema/access:** public.app_config; public.features

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/plans @ backend/src/ai/routers/billing.py:90 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/store.py:32::catalog | backend/src/ai/billing/admin.py:113::set_custom_contract`.

**Schema/access:** public.billing_plan_prices; public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** catalog/set_custom_contract expose base terms/operator grant, not server configurator feature selection/quantity validation.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-002 — Preview and instant checkout eligibility

Proposed behavior remains: Reproduce Node preview/manual-review decision in Python; never trust browser-calculated totals.

Acceptance specification: `AT-CUSTOM-002` — Changed preview rates; missing verified vendor rate; unsafe price. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/custom-plans/preview @ backend/src/modules/subscription/route/custom-plan.route.ts:54 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-configurator.service.ts:383:1::previewCustomPlanConfiguration | backend/src/modules/subscription/service/custom-plan-configurator.service.ts:623:1::checkoutCustomPlanConfiguration | backend/src/modules/subscription/service/custom-plan-configurator.service.ts:90:1::calculateConfiguration`.

**Schema/access:** public.app_config; public.custom_plan_quote_features; public.custom_plan_quotes; public.features; public.infrastructure_rates; public.plan_features; public.plans; public.promo_code_redemptions; public.promo_codes; public.subscriptions; public.vendor_rates

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51 | POST /billing/change-plan @ backend/src/ai/routers/billing.py:288 | POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/admin.py:113::set_custom_contract | backend/src/ai/billing/store.py:78::current_price`.

**Schema/access:** public.billing_plan_prices; public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_plans

**Missing/unequal edge:** No customer quote preview/instant-custom-checkout eligibility service; current_price is standard catalog lookup.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-003 — Quote create draft edit revisions

Proposed behavior remains: Add immutable quote revisions/snapshots linked to Python tenant; editing invalidates prior calculation/approval.

Acceptance specification: `AT-CUSTOM-003` — Concurrent edit/approve; stale revision acceptance. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/custom-quotes @ backend/src/modules/platform-admin/route/platform-admin.route.ts:153 | POST /subscription/custom-plans/quotes @ backend/src/modules/subscription/route/custom-plan.route.ts:108 | PATCH /platform-admin/billing/custom-quotes/:id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:165 | PATCH /subscription/custom-plans/quotes/:id @ backend/src/modules/subscription/route/custom-plan.route.ts:122. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan.service.ts:319:1::createCustomPlanQuote | backend/src/modules/subscription/service/custom-plan.service.ts:434:1::updateCustomPlanQuote | backend/src/modules/subscription/repo/custom-plan.repo.ts:80:21::customPlanRepository.updateDraftQuote`.

**Schema/access:** public.app_config; public.custom_plan_quote_features; public.custom_plan_quotes; public.features

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/admin.py:113::set_custom_contract | backend/src/ai/billing/admin.py:34::_audit`.

**Schema/access:** public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments

**Missing/unequal edge:** set_custom_contract overwrites current contract snapshot with audit; no customer quote draft/revision/approval lifecycle.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-004 — Vendor costs monitoring quantity

Proposed behavior remains: Retain Node estimated feature usage and minutes-per-month/cadence costs; map verified runtime providers to Python schedules, not a second live cost ledger.

Acceptance specification: `AT-CUSTOM-004` — Absent rate; cadence missing competitor count; unit mismatch. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/custom-quotes/:id/calculate @ backend/src/modules/platform-admin/route/platform-admin.route.ts:172 | POST /subscription/custom-plans/quotes/:id/calculate @ backend/src/modules/subscription/route/custom-plan.route.ts:130 | POST /subscription/custom-plans/preview @ backend/src/modules/subscription/route/custom-plan.route.ts:54 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-pricing.service.ts:112:1::resolveRateUsage | backend/src/modules/subscription/service/custom-plan-pricing.service.ts:260:1::calculateCustomPlanPrice | backend/src/modules/subscription/repo/custom-plan.repo.ts:154:25::customPlanRepository.getActiveVendorRates`.

**Schema/access:** public.vendor_rates

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | POST /discovery/competitors/{competitor_id}/analysis @ backend/src/ai/routers/discovery.py:245 | POST /discovery/market/analysis @ backend/src/ai/routers/discovery.py:286 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/credits.py:222::schedule | backend/src/ai/billing/cost_model.py:105::recommended_budgets`.

**Schema/access:** public.provider_cost_schedules

**Missing/unequal edge:** Verified runtime provider rates and credit cost model exist, but no Node-style feature/cadence estimate quote projection.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-005 — Infrastructure usage and allocation

Proposed behavior remains: Implement Node usage-driven infrastructure and per-paying-tenant allocation with Decimal and versioned inputs.

Acceptance specification: `AT-CUSTOM-005` — Zero tenant divisor; deprecated rates; duplicate cost driver. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/custom-quotes/:id/calculate @ backend/src/modules/platform-admin/route/platform-admin.route.ts:172 | POST /subscription/custom-plans/quotes/:id/calculate @ backend/src/modules/subscription/route/custom-plan.route.ts:130 | POST /subscription/custom-plans/preview @ backend/src/modules/subscription/route/custom-plan.route.ts:54 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-pricing.service.ts:234:1::resolveInfrastructureFeatureQuantity | backend/src/modules/subscription/service/custom-plan-pricing.service.ts:260:1::calculateCustomPlanPrice | backend/src/modules/subscription/repo/custom-plan.repo.ts:171:33::customPlanRepository.getActiveInfrastructureRates`.

**Schema/access:** public.infrastructure_rates

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/cost_model.py:76::max_variable_cost | backend/src/ai/billing/cost_model.py:83::plan_budget`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Budget model has platform cost assumptions; no Node quote infrastructure feature-rate/allocation workflow.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-006 — Gross margin and vendor ratio floors

Proposed behavior remains: Port formulas with explicit policy: total cost/(1-margin), optional vendor cost/ratio, max floors, fee then round upward.

Acceptance specification: `AT-CUSTOM-006` — Margin 1; missing ratio; boundary rounding; override below floor. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/custom-quotes/:id/calculate @ backend/src/modules/platform-admin/route/platform-admin.route.ts:172 | POST /subscription/custom-plans/quotes/:id/calculate @ backend/src/modules/subscription/route/custom-plan.route.ts:130 | POST /subscription/custom-plans/preview @ backend/src/modules/subscription/route/custom-plan.route.ts:54 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-pricing.service.ts:260:1::calculateCustomPlanPrice | backend/src/modules/subscription/service/custom-plan-pricing.service.ts:193:1::assertGrossMargin | backend/src/modules/subscription/service/custom-plan-pricing.service.ts:205:1::roundUpToIncrement`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/cost_model.py:83::plan_budget | backend/src/ai/billing/cost_model.py:105::recommended_budgets`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Current budget-margin math is not Node quote floor/fee/up-rounding contract; no equivalent quote price preview.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-007 — Quote FX and payment currency

Proposed behavior remains: Keep quote FX snapshot; separately convert only at Stripe boundary; no hardcoded current rate.

Acceptance specification: `AT-CUSTOM-007` — Missing/inverted/stale FX; quote JOD vs payment USD. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/custom-plans/quotes/:id/accept @ backend/src/modules/subscription/route/custom-plan.route.ts:94 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /platform-admin/billing/custom-quotes/:id/calculate @ backend/src/modules/platform-admin/route/platform-admin.route.ts:172 | POST /subscription/custom-plans/quotes/:id/calculate @ backend/src/modules/subscription/route/custom-plan.route.ts:130 | POST /subscription/custom-plans/preview @ backend/src/modules/subscription/route/custom-plan.route.ts:54 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-payment-currency.service.ts:57:1::convertCustomPlanAmountToPaymentCurrency | backend/src/modules/subscription/service/custom-plan-pricing.service.ts:214:1::convertRateToQuoteCurrency | backend/src/modules/subscription/service/custom-plan.service.ts:775:1::acceptCustomPlanQuote`.

**Schema/access:** public.app_config; public.custom_plan_quotes; public.plan_features; public.plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.stripe_sync_catalog @ backend/scripts/stripe_sync_catalog.py:46 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/catalog_sync.py:42::minor_units | backend/src/ai/billing/admin.py:113::set_custom_contract`.

**Schema/access:** public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments

**Missing/unequal edge:** Currency minor-unit conversion exists; no frozen quote FX/payment-boundary conversion workflow.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-008 — Approve unsafe floor override

Proposed behavior remains: Enforce separate pricing override permission, reason and audit; send only approved revision.

Acceptance specification: `AT-CUSTOM-008` — Missing override privilege/reason; stale approval. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/custom-quotes/:id/approve @ backend/src/modules/platform-admin/route/platform-admin.route.ts:178 | POST /subscription/custom-plans/quotes/:id/approve @ backend/src/modules/subscription/route/custom-plan.route.ts:137. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan.service.ts:656:1::approveCustomPlanQuote | backend/src/modules/subscription/controller/custom-plan.controller.ts:199:1::approveQuoteHandler | backend/src/modules/platform-admin/controller/platform-admin.controller.ts:239:1::approvePlatformQuoteHandler`.

**Schema/access:** public.custom_plan_quotes

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/admin.py:113::set_custom_contract | backend/src/ai/billing/admin.py:28::_require`.

**Schema/access:** public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments

**Missing/unequal edge:** Operator CLI approved_by/reason and limits grant are not quote approval/unsafe-price privilege workflow.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-009 — Offer send notification outbox

Proposed behavior remains: Keep transactional offer state plus durable notification event; consumer retry must not duplicate sends.

Acceptance specification: `AT-CUSTOM-009` — Worker crash after send; offer expires; tenant recipient changed. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/custom-quotes/:id/send @ backend/src/modules/platform-admin/route/platform-admin.route.ts:185 | POST /subscription/custom-plans/quotes/:id/send @ backend/src/modules/subscription/route/custom-plan.route.ts:145. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan.service.ts:704:1::sendCustomPlanQuote | backend/src/modules/tenant-notifications/tenant-notification.producer.ts:11:1::customPlanOfferReady`.

**Schema/access:** public.custom_plan_quotes; public.tenant_notification_outbox

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /auth/password/forgot @ backend/src/ai/routers/auth.py:574 | POST /settings/team/invitations @ backend/src/ai/routers/settings.py:573 | POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/email/resend-verification @ backend/src/ai/routers/auth.py:653. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/core/notifications.py:55::send_email`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Email helper exists but no quote state plus offer-ready transactional outbox/consumer.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-010 — Accept reject expire

Proposed behavior remains: Accept immutable priced revision idempotently; create provider price mapping only; do not invoke set_custom_contract automatically.

Acceptance specification: `AT-CUSTOM-010` — Duplicate accept; expired quote; provider success DB failure. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/custom-plans/quotes/:id/accept @ backend/src/modules/subscription/route/custom-plan.route.ts:94 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /platform-admin/billing/custom-quotes/:id/reject @ backend/src/modules/platform-admin/route/platform-admin.route.ts:191 | POST /subscription/custom-plans/quotes/:id/reject @ backend/src/modules/subscription/route/custom-plan.route.ts:152. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan.service.ts:775:1::acceptCustomPlanQuote | backend/src/modules/subscription/service/custom-plan.service.ts:760:1::rejectCustomPlanQuote | backend/src/modules/subscription/repo/custom-plan.repo.ts:300:23::customPlanRepository.convertQuoteToPlan`.

**Schema/access:** public.app_config; public.custom_plan_quotes; public.plan_features; public.plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51 | POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/admin.py:113::set_custom_contract | backend/src/ai/billing/stripe_api.py:39::create_checkout_session`.

**Schema/access:** public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments

**Missing/unequal edge:** No quote acceptance/rejection/expiry or quote-to-provider-price mapping. set_custom_contract directly grants access and must not substitute.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-011 — Custom activation and contract history

Proposed behavior remains: Reuse Python audited operator contract activation and paid Stripe activation as distinct authorized paths; quote acceptance alone grants nothing.

Acceptance specification: `AT-CUSTOM-011` — Unpaid accepted offer; operator grant overwrites live Stripe assignment. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /subscription/custom-plans/quotes/:id/accept @ backend/src/modules/subscription/route/custom-plan.route.ts:94 | POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-configurator.service.ts:623:1::checkoutCustomPlanConfiguration | backend/src/modules/subscription/service/custom-plan.service.ts:775:1::acceptCustomPlanQuote | backend/src/utils/webhook handlers.ts:74:1::handleSubscriptionCreated`.

**Schema/access:** public.app_config; public.custom_plan_quote_features; public.custom_plan_quotes; public.features; public.infrastructure_rates; public.plan_features; public.plan_price_versions; public.plans; public.promo_code_redemptions; public.promo_codes; public.subscription_usage; public.subscriptions; public.vendor_rates

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51 | POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/admin.py:113::set_custom_contract | backend/src/ai/billing/store.py:265::apply_subscription | backend/src/ai/billing/webhooks.py:74::sync_subscription`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments

**Missing/unequal edge:** Manual approved contract activation exists and is distinct from Stripe payment activation; no accepted quote linkage/history authority precedence.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-012 — Customer and operator custom dashboards

Proposed behavior remains: Add builder, safe offer tracking and platform quote/cost/rate/policy screens in existing Python frontend patterns.

Acceptance specification: `AT-CUSTOM-012` — Costs hidden from customer; wrong tenant offer; loading/stale conflict. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /subscription/custom-plans/quotes/:id/offer @ backend/src/modules/subscription/route/custom-plan.route.ts:89 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59 | GET /platform-admin/billing/custom-quotes @ backend/src/modules/platform-admin/route/platform-admin.route.ts:152. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan.service.ts:380:1::getCustomPlanOffer | backend/src/modules/subscription/service/custom-plan-configurator.service.ts:578:1::requestCustomPlanManualReview | backend/src/modules/platform-admin/controller/platform-admin.controller.ts:176:1::listPlatformQuotesHandler`.

**Schema/access:** public.app_config; public.custom_plan_quote_features; public.custom_plan_quotes; public.features; public.infrastructure_rates; public.vendor_rates

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `frontend/src/features/billing/api/billingApi.js:78:13::billingApi.getPlans | backend/src/ai/billing/admin.py:113::set_custom_contract`.

**Schema/access:** public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments

**Missing/unequal edge:** Current billing page and operator CLI do not supply custom builder/offer tracking/operator quote-cost dashboards.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CUSTOM-013 — Private plan access isolation

Proposed behavior remains: Extend Python canonical catalog with tenant-private price/contract visibility; no shadow assignment/catalog authority.

Acceptance specification: `AT-CUSTOM-013` — Other tenant guesses plan key; webhook references private price. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /subscription/custom-plans/ @ backend/src/modules/subscription/route/custom-plan.route.ts:88 | PATCH /platform-admin/billing/custom-plans/:id/status @ backend/src/modules/platform-admin/route/platform-admin.route.ts:138 | POST /subscription/checkout @ backend/src/modules/subscription/route/subscriptions.route.ts:54 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: billingApi.getCustomPlanConfigurator/previewCustomPlan/checkoutCustomPlan; CustomPlanBuilder.jsx; platformBillingApi quote/rate methods.

**Exact source roots:** `backend/src/modules/subscription/repo/custom-plan.repo.ts:204:29::customPlanRepository.listCustomPlansForTenant | backend/src/modules/subscription/repo/custom-plan.repo.ts:267:29::customPlanRepository.setCustomPlanActiveState | backend/src/modules/subscription/service/subscription.service.ts:381:1::checkoutService`.

**Schema/access:** public.plans; public.promo_code_redemptions; public.promo_codes; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/plans @ backend/src/ai/routers/billing.py:90 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: PlansSubscriptionPage.jsx -> billingApi.getPlans/getSubscription; operator CLI scripts/billing_admin.py; no quote customer/operator API.

**Exact source roots:** `backend/src/ai/billing/store.py:32::catalog | backend/src/ai/billing/admin.py:113::set_custom_contract`.

**Schema/access:** public.billing_plan_prices; public.companies; public.entitlement_audit_log; public.tenant_custom_contracts; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Public custom base plan plus per-tenant overrides is not Node tenant-private purchasable plan catalog/Stripe price lifecycle.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
