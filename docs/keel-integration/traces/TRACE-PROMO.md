# Source trace refinement — PROMO

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified PROMO lineage](../evidence/phase0r/SCHEMA_LINEAGE_PROMO.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: PROMO-001

## PROMO-001 — Promo create and update disable

Proposed behavior remains: Add managed promotion lifecycle to Python billing; Python allow_promotion_codes is only Stripe-hosted entry support.

Acceptance specification: `AT-PROMO-001` — Duplicate code; coupon creation succeeds DB fails; disabled code. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/promo-codes @ backend/src/modules/platform-admin/route/platform-admin.route.ts:221 | POST /subscription/promo-codes/ @ backend/src/modules/subscription/route/promo-codes.route.ts:42 | PATCH /platform-admin/billing/promo-codes/:id @ backend/src/modules/platform-admin/route/platform-admin.route.ts:227 | PATCH /subscription/promo-codes/:id @ backend/src/modules/subscription/route/promo-codes.route.ts:58. UI: billingApi.validateCoupon/createPromoCode/updatePromoCode; platformBillingApi promo methods.

**Exact source roots:** `backend/src/modules/subscription/service/promocodes.service.ts:94:1::createPromocodeService | backend/src/modules/subscription/service/promocodes.service.ts:58:1::updatePromocodeService | backend/src/modules/subscription/client/payment-providers/stripe/stripe.client.ts:516:1::createPromoCode`.

**Schema/access:** public.promo_codes

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: billingApi.checkout -> /billing/checkout; no managed promo API/UI method.

**Exact source roots:** `backend/src/ai/billing/service.py:63::create_checkout | backend/src/ai/billing/stripe_api.py:39::create_checkout_session`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.usage_plans

**Missing/unequal edge:** Hosted Checkout allow_promotion_codes=True is the only analogous path; managed create/update/disable API/service/tables absent.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PROMO-002 — Plan association and eligibility

Proposed behavior remains: Preserve Node plan association, startsAt/expiresAt, maxUses and tenant use checks; decide term/currency extensions.

Acceptance specification: `AT-PROMO-002` — Wrong plan; before start; expiry boundary; currency mismatch. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/promo-codes/validate @ backend/src/modules/subscription/route/promo-codes.route.ts:50 | POST /subscription/checkout @ backend/src/modules/subscription/route/subscriptions.route.ts:54 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /subscription/promo-codes/:promoCodeId/plans/:planId @ backend/src/modules/subscription/route/promo-codes.route.ts:67. UI: billingApi.validateCoupon/createPromoCode/updatePromoCode; platformBillingApi promo methods.

**Exact source roots:** `backend/src/modules/subscription/service/promocodes.service.ts:23:1::validatePromoCode | backend/src/modules/subscription/service/promocodes-plans.service.ts:57:1::linkPromoCodePlan | backend/src/modules/subscription/repo/promocodes.repo.ts:34:1::countPromoRedemptionsForTenant`.

**Schema/access:** public.plans; public.promo_code_redemptions; public.promo_codes; public.promo_codes_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: billingApi.checkout -> /billing/checkout; no managed promo API/UI method.

**Exact source roots:** `backend/src/ai/billing/service.py:63::create_checkout`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.usage_plans

**Missing/unequal edge:** No managed promotion plan/date/tenant/term eligibility evaluator in billing service; Stripe-hosted validation is not a Python equivalent.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PROMO-003 — Redemption concurrency and audit

Proposed behavior remains: Persist reservations/redemptions uniquely per tenant/provider session; consume on authoritative paid/subscription outcome; reconcile abandoned checkout.

Acceptance specification: `AT-PROMO-003` — Last use race; duplicate webhook; abandoned session; repeated customer. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /stripe/webhooks/ @ backend/src/modules/subscription/route/stripe-webhook.route.ts:7. UI: billingApi.validateCoupon/createPromoCode/updatePromoCode; platformBillingApi promo methods.

**Exact source roots:** `backend/src/modules/subscription/repo/promocodes.repo.ts:52:1::consumePromocode | backend/src/utils/webhook handlers.ts:214:1::handleInvoicePaid`.

**Schema/access:** public.plan_features; public.plan_price_versions; public.plans; public.promo_code_redemptions; public.promo_codes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/webhook @ backend/src/ai/routers/billing.py:349. UI: billingApi.checkout -> /billing/checkout; no managed promo API/UI method.

**Exact source roots:** `backend/src/ai/billing/webhooks.py:152::_handle_locked | backend/src/ai/billing/store.py:361::record_payment`.

**Schema/access:** public.billing_customers; public.billing_payments; public.billing_plan_prices; public.billing_subscriptions; public.billing_webhook_events; public.tenant_plan_assignments

**Missing/unequal edge:** No managed promo reservation/redemption table or webhook consume counterpart. Existing payment idempotency does not implement promo limits.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PROMO-004 — Stacking discount ownership

Proposed behavior remains: Select Stripe monetary authority plus Python eligibility; do not stack automatic quote discounts with hosted codes implicitly.

Acceptance specification: `AT-PROMO-004` — Fixed amount vs percent; custom quote; changed code during checkout. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/checkout @ backend/src/modules/subscription/route/subscriptions.route.ts:54 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65 | POST /subscription/promo-codes/validate @ backend/src/modules/subscription/route/promo-codes.route.ts:50. UI: billingApi.validateCoupon/createPromoCode/updatePromoCode; platformBillingApi promo methods.

**Exact source roots:** `backend/src/modules/subscription/service/subscription.service.ts:381:1::checkoutService | backend/src/modules/subscription/client/payment-providers/stripe/stripe.client.ts:593:1::createCheckoutSession | backend/src/modules/subscription/service/promocodes.service.ts:23:1::validatePromoCode`.

**Schema/access:** public.plans; public.promo_code_redemptions; public.promo_codes; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: billingApi.checkout -> /billing/checkout; no managed promo API/UI method.

**Exact source roots:** `backend/src/ai/billing/service.py:63::create_checkout`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.usage_plans

**Missing/unequal edge:** Existing hosted-code option does not define cross-discount stacking or Node tenant repeat limits.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PROMO-005 — Promo customer and operator dashboard

Proposed behavior remains: Add Python billing customer feedback and platform management UI; authorization on API not UI only.

Acceptance specification: `AT-PROMO-005` — Invalid code message; secret cost leakage; operator permission denial. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /subscription/promo-codes/validate @ backend/src/modules/subscription/route/promo-codes.route.ts:50. UI: billingApi.validateCoupon/createPromoCode/updatePromoCode; platformBillingApi promo methods.

**Exact source roots:** `backend/src/modules/subscription/controller/promocode.controller.ts:13:1::validatePromoHandler | frontend/src/features/billing/api/billingApi.js:121:19::billingApi.validateCoupon | frontend/src/features/platform-admin/api/platformBillingApi.js:94:20::platformBillingApi.createPromoCode`.

**Schema/access:** public.promo_code_redemptions; public.promo_codes

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /billing/checkout @ backend/src/ai/routers/billing.py:253. UI: billingApi.checkout -> /billing/checkout; no managed promo API/UI method.

**Exact source roots:** `frontend/src/features/billing/api/billingApi.js:87:13::billingApi.checkout | backend/src/ai/routers/billing.py:253::start_checkout`.

**Schema/access:** public.billing_customers; public.billing_plan_prices; public.billing_subscriptions; public.billing_trials; public.companies; public.tenant_users; public.usage_plans; public.users

**Missing/unequal edge:** Python billingApi has no validateCoupon/admin promotion methods; no managed promo dashboard.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
