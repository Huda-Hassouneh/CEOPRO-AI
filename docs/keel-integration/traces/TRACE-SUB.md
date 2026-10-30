# Source trace refinement — SUB

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified SUB lineage](../evidence/phase0r/SCHEMA_LINEAGE_SUB.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: CATALOG-001; CUSTOM-002; TRANSITION-001

## SUB-001 — Catalog and historical Stripe prices

Proposed behavior remains: Preserve Python stable keys and historic price mapping; version approved new grants without overwriting existing subscriptions.

Acceptance specification: `AT-SUB-001` — Retired price event; inactive price; private plan exposure. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /subscription/plans/ @ backend/src/modules/subscription/route/plans.route.ts:26 | POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7 | PATCH /platform-admin/billing/plans/:id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:111 | PATCH /subscription/plans/:id @ backend/src/modules/subscription/route/plans.route.ts:37. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/plans.service.ts:110:1::getPlans | backend/src/modules/subscription/repo/plans.repo.ts:75:1::getPlanByPriceId | backend/src/modules/subscription/service/plans.service.ts:428:1::updatePlansService`.

**Schema/access:** public.app_config; public.plan_price_versions; public.plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/plans @ backend/src/ai/routers/billing.py:90 | POST /billing/webhook @ backend/src/ai/routers/billing.py:349 | WORKER_OR_PRIVATE python -m scripts.stripe_sync_catalog @ backend/scripts/stripe_sync_catalog.py:46. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/billing/store.py:32::catalog | backend/src/ai/billing/store.py:104::resolve_price | backend/src/ai/billing/catalog_sync.py:69::plan`.

**Schema/access:** public.billing_plan_prices; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-002 — Trials eligibility and exact expiry

Proposed behavior remains: Retain Python per-person/per-tenant trial checks and exact UTC expiry; obtain owner decision for different Node trial terms.

Acceptance specification: `AT-SUB-002` — Another workspace already trialed; simultaneous trial start. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/checkout @ backend/src/modules/subscription/route/subscriptions.route.ts:54 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/subscription.service.ts:381:1::checkoutService | backend/src/utils/webhook handlers.ts:74:1::handleSubscriptionCreated`.

**Schema/access:** public.plan_features; public.plan_price_versions; public.plans; public.promo_code_redemptions; public.promo_codes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/trial @ backend/src/ai/routers/billing.py:187 | GET /billing/subscription @ backend/src/ai/routers/billing.py:101 | POST /auth/signup @ backend/src/ai/routers/auth.py:230 | POST /auth/workspaces @ backend/src/ai/routers/auth.py:411 | GET /competitors/landscape @ backend/src/ai/routers/competitors.py:121 | GET /discovery/competitors @ backend/src/ai/routers/discovery.py:123 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743 | POST /competitors @ backend/src/ai/routers/competitors.py:305. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/routers/billing.py:187::start_trial | backend/src/ai/billing/store.py:116::trial_eligibility | backend/src/ai/billing/store.py:142::start_trial | backend/src/ai/core/usage.py:139::get_plan`.

**Schema/access:** public.billing_subscriptions; public.billing_trials; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-003 — Checkout and customer reuse

Proposed behavior remains: Reuse create_checkout stored customer mapping and provider idempotency; no entitlements before confirmed billing.

Acceptance specification: `AT-SUB-003` — Duplicate checkout; provider outage; missing Stripe key. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/checkout @ backend/src/modules/subscription/route/subscriptions.route.ts:54 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/subscription.service.ts:381:1::checkoutService | backend/src/modules/subscription/client/payment-providers/stripe/stripe.client.ts:593:1::createCheckoutSession`.

**Schema/access:** public.plans; public.promo_code_redemptions; public.promo_codes; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/routers/billing.py:253::start_checkout | backend/src/ai/billing/service.py:63::create_checkout | backend/src/ai/billing/service.py:53::_ensure_customer`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.companies; public.tenant_users; public.usage_plans; public.users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-004 — Billing portal

Proposed behavior remains: Reuse Python general billing portal. Node recovery selects payable hosted invoice or customer portal only for recoverable states; preserve that stronger recovery UX as approved extension.

Acceptance specification: `AT-SUB-004` — Wrong role; no provider customer; 503 disabled. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/current/recovery @ backend/src/modules/subscription/route/subscriptions.route.ts:30. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/subscription.service.ts:238:1::createSubscriptionRecoveryService | backend/src/modules/subscription/client/payment-providers/stripe/stripe.client.ts:481:1::createCustomerPortalSession`.

**Schema/access:** public.subscriptions

**Missing/unequal edge:** Customer portal reachable through recovery service only after recoverable subscription/provider checks; not the same public flow as unrestricted Python billing portal action.

**PYTHON entry and UI boundary:** POST /billing/portal @ backend/src/ai/routers/billing.py:272. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/routers/billing.py:272::open_portal | backend/src/ai/billing/service.py:103::create_portal`.

**Schema/access:** public.billing_customers; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-005 — Plan transition gain loss mixed

Proposed behavior remains: Implement entitlement-vector classification around Python change_plan; tier/amount comparison is insufficient for private mixed-right plans.

Acceptance specification: `AT-SUB-005` — Cheaper plan grants more; mixed gains/losses; same tier longer period. NOT RUN as an implementation test.

**NODE entry and UI boundary:** PATCH /subscription/current/plan @ backend/src/modules/subscription/route/subscriptions.route.ts:47 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | GET /platform-admin/billing/subscriptions @ backend/src/modules/platform-admin/route/platform-admin.route.ts:98. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/plans.service.ts:135:1::changePlanService | backend/src/modules/subscription/service/plan-transition.service.ts:101:1::analyzePlanTransition`.

**Schema/access:** public.plans; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/change-plan @ backend/src/ai/routers/billing.py:288. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/billing/service.py:119::change_plan | backend/src/ai/billing/store.py:97::plan_tier`.

**Schema/access:** public.billing_plan_prices; public.billing_subscriptions; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-006 — Schedule reductions and proration

Proposed behavior remains: Reuse Python Stripe schedule/release path; timing of mixed changes requires owner decision.

Acceptance specification: `AT-SUB-006` — Trial retained; SCA pending payment; existing scheduled reduction. NOT RUN as an implementation test.

**NODE entry and UI boundary:** PATCH /subscription/current/plan @ backend/src/modules/subscription/route/subscriptions.route.ts:47 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | DELETE /subscription/current/plan/scheduled @ backend/src/modules/subscription/route/subscriptions.route.ts:60. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/plans.service.ts:135:1::changePlanService | backend/src/modules/subscription/client/payment-providers/stripe/stripe.client.ts:909:1::updateSubscription | backend/src/modules/subscription/service/subscription.service.ts:517:1::cancelScheduledPlanChangeService`.

**Schema/access:** public.plans; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/change-plan @ backend/src/ai/routers/billing.py:288 | DELETE /billing/scheduled-change @ backend/src/ai/routers/billing.py:306. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/billing/service.py:119::change_plan | backend/src/ai/billing/service.py:199::cancel_scheduled_change`.

**Schema/access:** public.billing_plan_prices; public.billing_subscriptions; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-007 — Cancel resume and resubscribe

Proposed behavior remains: Reuse Python cancel_at_period_end/resume and new checkout after terminal subscription; never apply old subscription identity to new assignment.

Acceptance specification: `AT-SUB-007` — Old cancellation after new paid subscription; retry cancellation. NOT RUN as an implementation test.

**NODE entry and UI boundary:** PATCH /subscription/current/cancel @ backend/src/modules/subscription/route/subscriptions.route.ts:35 | PATCH /subscription/current/cancel/undo @ backend/src/modules/subscription/route/subscriptions.route.ts:41 | POST /subscription/checkout @ backend/src/modules/subscription/route/subscriptions.route.ts:54 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/subscription.service.ts:62:1::cancelSubscriptionService | backend/src/modules/subscription/service/subscription.service.ts:126:1::undoCancelSubscriptionService | backend/src/modules/subscription/service/subscription.service.ts:381:1::checkoutService`.

**Schema/access:** public.plans; public.promo_code_redemptions; public.promo_codes; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/cancel @ backend/src/ai/routers/billing.py:339 | POST /billing/resume @ backend/src/ai/routers/billing.py:344 | POST /billing/checkout @ backend/src/ai/routers/billing.py:253 | POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/billing/service.py:214::set_cancellation | backend/src/ai/billing/service.py:63::create_checkout | backend/src/ai/billing/store.py:265::apply_subscription`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.tenant_plan_assignments; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-008 — Signed webhook event locking

Proposed behavior remains: Preserve Task 6 event/subscription/invoice/tenant locks, raw-body signature and retry rollback.

Acceptance specification: `AT-SUB-008` — Invalid signature; duplicate concurrent event; reconciliation outage. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/controller/stripe-webhook.controller.ts:7:1::webhookHandler | backend/src/modules/subscription/service/stripe-webhook.service.ts:35:1::webhookService | backend/src/modules/subscription/repo/webhook.repo.ts:83:1::getWebhookEventByProviderId`.

**Schema/access:** public.payment_provider_webhook_events; public.plan_features; public.plan_price_versions; public.plans; public.platform_notification_outbox; public.promo_code_redemptions; public.promo_codes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/routers/billing.py:349::stripe_webhook | backend/src/ai/billing/webhooks.py:142::handle_event | backend/src/ai/billing/webhooks.py:152::_handle_locked`.

**Schema/access:** public.billing_customers; public.billing_payments; public.billing_plan_prices; public.billing_subscriptions; public.billing_webhook_events; public.tenant_plan_assignments

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-009 — Paid invoice monotonic reconciliation

Proposed behavior remains: Preserve Task 6 retrieve_invoice and record_payment guard; native reordered-event proof still required.

Acceptance specification: `AT-SUB-009` — Paid then delayed failed; mismatched customer/subscription. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/utils/webhook handlers.ts:429:1::handleInvoicePaymentFailed | backend/src/utils/webhook handlers.ts:314:1::handleInvoicePaymentSucceeded | backend/src/utils/webhook handlers.ts:214:1::handleInvoicePaid`.

**Schema/access:** public.plan_features; public.plan_price_versions; public.plans; public.platform_notification_outbox; public.promo_code_redemptions; public.promo_codes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/billing/webhooks.py:152::_handle_locked | backend/src/ai/billing/store.py:361::record_payment`.

**Schema/access:** public.billing_customers; public.billing_payments; public.billing_plan_prices; public.billing_subscriptions; public.billing_webhook_events; public.tenant_plan_assignments

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-010 — Current subscription assignment identity

Proposed behavior remains: Preserve Task 6 apply_subscription tenant binding and history; competing live provider subscriptions fail for reconciliation.

Acceptance specification: `AT-SUB-010` — Subscription A terminal event after B activation. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/utils/webhook handlers.ts:125:1::handleSubscriptionDeleted | backend/src/utils/webhook handlers.ts:110:1::handleSubscriptionUpdated`.

**Schema/access:** public.plan_features; public.plan_price_versions; public.plans; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/billing/store.py:265::apply_subscription | backend/src/ai/billing/webhooks.py:74::sync_subscription`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.tenant_plan_assignments

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-011 — Invoices payment status and dashboard

Proposed behavior remains: Retain billing payments separate from business sales invoices; display real provider amounts/links and 502/empty states.

Acceptance specification: `AT-SUB-011` — Failed then succeeded; wrong tenant invoice; missing URL. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /subscription/invoices @ backend/src/modules/subscription/route/invoice.route.ts:10. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/invoice.service.ts:105:1::getTenantInvoicesService | backend/src/modules/subscription/service/invoice.service.ts:64:1::classifyInvoice | backend/src/modules/subscription/repo/invoice.repo.ts:35:37::invoiceRepo.getPaymentEventsBySubscriptionId`.

**Schema/access:** public.payment_provider_webhook_events; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/invoices @ backend/src/ai/routers/billing.py:232. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/routers/billing.py:232::list_invoices | backend/src/ai/billing/store.py:392::payments`.

**Schema/access:** public.billing_payments; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-012 — Past due grace and refund policy

Proposed behavior remains: Do not infer access from provider status or implement refunds as failed invoices; define contractual grace and refund support explicitly.

Acceptance specification: `AT-SUB-012` — past_due/unpaid/paused; refund after paid invoice; renewal failure. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7 | POST /subscription/current/recovery @ backend/src/modules/subscription/route/subscriptions.route.ts:30. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/utils/webhook.ts:30:1::mapStripeSubscriptionStatus | backend/src/modules/subscription/service/subscription.service.ts:238:1::createSubscriptionRecoveryService`.

**Schema/access:** public.subscriptions

**Missing/unequal edge:** Status mapping/recovery paths exist; no mounted comprehensive refund issuance or owner-approved contractual grace policy is proven.

**PYTHON entry and UI boundary:** GET /billing/subscription @ backend/src/ai/routers/billing.py:101 | GET /competitors/landscape @ backend/src/ai/routers/competitors.py:121 | GET /discovery/competitors @ backend/src/ai/routers/discovery.py:123 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743 | POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /billing/change-plan @ backend/src/ai/routers/billing.py:288 | DELETE /billing/scheduled-change @ backend/src/ai/routers/billing.py:306 | POST /billing/cancel @ backend/src/ai/routers/billing.py:339 | POST /billing/resume @ backend/src/ai/routers/billing.py:344 | POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/core/usage.py:139::get_plan | backend/src/ai/billing/service.py:112::_live_subscription | backend/src/ai/billing/webhooks.py:152::_handle_locked`.

**Schema/access:** public.billing_customers; public.billing_payments; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.billing_webhook_events; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** Status mapping/access and payment recording exist; no comprehensive customer refund issuance/grace policy is established by those paths.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-013 — Billing terms taxes currencies rounding

Proposed behavior remains: Python API accepts yearly but UI offers 1/3/6 months; preserve existing mappings and approve offered terms/taxes/FX.

Acceptance specification: `AT-SUB-013` — Zero/three decimal currencies; provider not configured; annual legacy term. NOT RUN as an implementation test.

**NODE entry and UI boundary:** PATCH /platform-admin/billing/plans/:id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:111 | PATCH /subscription/plans/:id @ backend/src/modules/subscription/route/plans.route.ts:37 | PATCH /subscription/current/plan @ backend/src/modules/subscription/route/subscriptions.route.ts:47 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /platform-admin/billing/plans @ backend/src/modules/platform-admin/route/platform-admin.route.ts:105 | POST /subscription/plans/ @ backend/src/modules/subscription/route/plans.route.ts:28 | POST /subscription/custom-plans/quotes/:id/accept @ backend/src/modules/subscription/route/custom-plan.route.ts:94. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/plan-pricing.ts:12:1::resolveBillingOption | backend/src/modules/subscription/service/plan-pricing.ts:28:1::optionPrice | backend/src/modules/subscription/client/payment-providers/stripe/stripe.client.ts:234:1::createPlan`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE python -m scripts.stripe_sync_catalog @ backend/scripts/stripe_sync_catalog.py:46 | POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/billing/catalog_sync.py:42::minor_units | backend/src/ai/billing/service.py:63::create_checkout | backend/src/ai/billing/config.py:30::automatic_tax`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## SUB-014 — Customer billing usage state

Proposed behavior remains: Extend Python PlansSubscriptionPage and billingApi without replacing current camelCase API; keep canManageBilling and credit budgets.

Acceptance specification: `AT-SUB-014` — 402 detail; payment_required; scheduledChange; loading/error/empty. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /subscription/current @ backend/src/modules/subscription/route/subscriptions.route.ts:29 | GET /subscriptions/current/usage @ backend/src/modules/features/route/feature-plan.route.ts:71. UI: frontend/src/features/billing/api/billingApi.js::billingApi; hooks/useSubscriptionRecovery.js.

**Exact source roots:** `backend/src/modules/subscription/service/subscription.service.ts:178:1::getCurrentSubscriptionService | backend/src/modules/features/service/usage.service.ts:6:28::usageService.getTenantUsageDashboard | frontend/src/features/billing/api/billingApi.js:48:24::normalizeUsage`.

**Schema/access:** public.data_sources; public.plan_features; public.plan_price_versions; public.products; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/subscription @ backend/src/ai/routers/billing.py:101. UI: frontend/src/features/billing/api/billingApi.js::billingApi; PlansSubscriptionPage.jsx.

**Exact source roots:** `backend/src/ai/routers/billing.py:101::get_subscription | frontend/src/features/billing/api/billingApi.js:82:20::billingApi.getSubscription | backend/src/ai/core/usage.py:241::current_usage`.

**Schema/access:** public.billing_cost_policy; public.billing_customers; public.billing_subscriptions; public.billing_trials; public.tenant_credit_balances; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_usage_counters; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
