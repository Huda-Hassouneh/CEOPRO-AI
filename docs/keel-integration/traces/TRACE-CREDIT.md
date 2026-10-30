# Source trace refinement — CREDIT

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified CREDIT lineage](../evidence/phase0r/SCHEMA_LINEAGE_CREDIT.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: ACCOUNTING-001

## CREDIT-001 — Independent Data AI budgets

Proposed behavior remains: Preserve credits.summary and separate balances/immutable usage ledger; never replace with Node feature-count ledger.

Acceptance specification: `AT-CREDIT-001` — Customer credit caps vs provider spending caps. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:56 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77. UI: Feature usage dashboard; quote cost estimates; no Node data_credits/ai_credits authority.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:546:34::getRemainingUsage`.

**Schema/access:** public.data_sources; public.plan_features; public.products; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No registered Node Data/AI credit or provider-spend authority matching Python. Cited feature quota/quote/provider boundary is comparison context, not a credit-ledger equivalent.

**PYTHON entry and UI boundary:** GET /billing/subscription @ backend/src/ai/routers/billing.py:101 | GET /alerts @ backend/src/ai/routers/alerts.py:15 | POST /discovery/runs @ backend/src/ai/routers/discovery.py:69 | POST /pricing/market-coverage/fill @ backend/src/ai/routers/competitor_enrichment.py:179 | POST /competitors/enrich-failed @ backend/src/ai/routers/competitor_enrichment.py:67 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99. UI: CreditBudgets.jsx -> billingApi.getSubscription/getUsageHistory; paid calls attach credits.metering contexts.

**Exact source roots:** `backend/src/ai/billing/credits.py:746::summary | backend/src/ai/billing/credits.py:348::balance | backend/src/ai/core/usage.py:214::_credits_used`.

**Schema/access:** public.billing_cost_policy; public.billing_subscriptions; public.billing_trials; public.tenant_credit_balances; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CREDIT-002 — Verified provider prices fail closed

Proposed behavior remains: Preserve schedule and provider_controls monthly caps/kill switch; unknown paid rates remain blocked.

Acceptance specification: `AT-CREDIT-002` — Missing price; stale/unverified rate; provider cap exhausted. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /platform-admin/billing/custom-quotes/:id/calculate @ backend/src/modules/platform-admin/route/platform-admin.route.ts:172 | POST /subscription/custom-plans/quotes/:id/calculate @ backend/src/modules/subscription/route/custom-plan.route.ts:130 | POST /subscription/custom-plans/preview @ backend/src/modules/subscription/route/custom-plan.route.ts:54 | POST /subscription/custom-plans/manual-review @ backend/src/modules/subscription/route/custom-plan.route.ts:59 | POST /subscription/custom-plans/checkout @ backend/src/modules/subscription/route/custom-plan.route.ts:65. UI: Feature usage dashboard; quote cost estimates; no Node data_credits/ai_credits authority.

**Exact source roots:** `backend/src/modules/subscription/service/custom-plan-pricing.service.ts:260:1::calculateCustomPlanPrice`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No registered Node Data/AI credit or provider-spend authority matching Python. Cited feature quota/quote/provider boundary is comparison context, not a credit-ledger equivalent.

**PYTHON entry and UI boundary:** POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | POST /discovery/competitors/{competitor_id}/analysis @ backend/src/ai/routers/discovery.py:245 | POST /discovery/market/analysis @ backend/src/ai/routers/discovery.py:286 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99. UI: CreditBudgets.jsx -> billingApi.getSubscription/getUsageHistory; paid calls attach credits.metering contexts.

**Exact source roots:** `backend/src/ai/billing/credits.py:222::schedule | backend/src/ai/billing/credits.py:362::_provider_controls | backend/src/ai/billing/credits.py:370::_provider_month_spend`.

**Schema/access:** public.provider_cost_schedules; public.provider_spend_controls; public.usage_ledger

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CREDIT-003 — Reserve settle billable provider errors

Proposed behavior remains: Keep provider_call sent/measured/billed_unreported and credits.settle; reconcile actual charge on error rather than unconditional refund.

Acceptance specification: `AT-CREDIT-003` — HTTP error billed; lost response; provider reports usage. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/imports/:kind @ backend/src/modules/dataconnection/route/dataconnection.route.ts:82 | POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33 | POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15 | POST /features/rag/documents @ backend/src/modules/rag/route/rag.route.ts:42 | POST /features/rag/query @ backend/src/modules/rag/route/rag.route.ts:55 | GET /features/rag/sessions @ backend/src/modules/rag/route/rag.route.ts:30 | GET /features/rag/sessions/:session_id @ backend/src/modules/rag/route/rag.route.ts:31. UI: Feature usage dashboard; quote cost estimates; no Node data_credits/ai_credits authority.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:289:1::reserveFeatureUsageInTransaction | backend/src/modules/features/repo/usage.repo.ts:392:1::releaseFeatureUsageInTransaction`.

**Schema/access:** public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No registered Node Data/AI credit or provider-spend authority matching Python. Cited feature quota/quote/provider boundary is comparison context, not a credit-ledger equivalent.

**PYTHON entry and UI boundary:** POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | POST /discovery/competitors/{competitor_id}/analysis @ backend/src/ai/routers/discovery.py:245 | POST /discovery/market/analysis @ backend/src/ai/routers/discovery.py:286 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99. UI: CreditBudgets.jsx -> billingApi.getSubscription/getUsageHistory; paid calls attach credits.metering contexts.

**Exact source roots:** `backend/src/ai/billing/credits.py:400::reserve | backend/src/ai/billing/credits.py:527::settle | backend/src/ai/billing/credits.py:638::provider_call`.

**Schema/access:** public.billing_cost_policy; public.billing_subscriptions; public.billing_trials; public.provider_cost_schedules; public.provider_spend_controls; public.tenant_credit_balances; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_ledger; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CREDIT-004 — Expired reservations and reconciliation

Proposed behavior remains: Retain maintenance conservative stale reservation charge and ledger reconciliation/admin adjustments.

Acceptance specification: `AT-CREDIT-004` — Crash after request; duplicate reconciliation; old period. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15 | GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13 | POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33 | GET /features/rag/sessions @ backend/src/modules/rag/route/rag.route.ts:30 | GET /features/rag/sessions/:session_id @ backend/src/modules/rag/route/rag.route.ts:31 | POST /features/rag/query @ backend/src/modules/rag/route/rag.route.ts:55. UI: Feature usage dashboard; quote cost estimates; no Node data_credits/ai_credits authority.

**Exact source roots:** `backend/src/modules/pricing/repo/pricing-request.repo.ts:26:1::recoverPricingRequests | backend/src/modules/features/repo/usage.repo.ts:392:1::releaseFeatureUsageInTransaction`.

**Schema/access:** public.pricing_requests; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No registered Node Data/AI credit or provider-spend authority matching Python. Cited feature quota/quote/provider boundary is comparison context, not a credit-ledger equivalent.

**PYTHON entry and UI boundary:** WORKER_OR_PRIVATE main.py lifespan -> maintenance thread @ backend/src/ai/billing/maintenance.py:22 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51. UI: CreditBudgets.jsx -> billingApi.getSubscription/getUsageHistory; paid calls attach credits.metering contexts.

**Exact source roots:** `backend/src/ai/billing/maintenance.py:22::run_once | backend/src/ai/billing/credits.py:662::expire_stale_reservations | backend/src/ai/billing/credits.py:693::reconcile | backend/src/ai/billing/admin.py:194::adjust_credits`.

**Schema/access:** public.billing_cost_policy; public.billing_trials; public.entitlement_audit_log; public.tenant_credit_balances; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_ledger; public.usage_ledger_adjustments; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CREDIT-005 — Context propagation async service cost

Proposed behavior remains: Preserve credits.bind thread context and provider_billing/data cost ledger; queued job carries tenant and operation receipt.

Acceptance specification: `AT-CREDIT-005` — ThreadPool loses context; nested metering; cross tenant job. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/store/detect @ backend/src/modules/dataconnection/store/routes.ts:32 | POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30. UI: Feature usage dashboard; quote cost estimates; no Node data_credits/ai_credits authority.

**Exact source roots:** `backend/src/modules/dataconnection/store/provider.client.ts:4:1::storeProvider`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No registered Node Data/AI credit or provider-spend authority matching Python. Cited feature quota/quote/provider boundary is comparison context, not a credit-ledger equivalent.

**PYTHON entry and UI boundary:** POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | POST /discovery/competitors/{competitor_id}/analysis @ backend/src/ai/routers/discovery.py:245 | POST /discovery/market/analysis @ backend/src/ai/routers/discovery.py:286 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99 | POST /discovery/competitors/{competitor_id}/refresh @ backend/src/ai/routers/discovery.py:162. UI: CreditBudgets.jsx -> billingApi.getSubscription/getUsageHistory; paid calls attach credits.metering contexts.

**Exact source roots:** `backend/src/ai/billing/credits.py:183::bind | backend/src/ai/billing/credits.py:137::metering | backend/src/ai/billing/credits.py:156::metered | backend/src/market_scraper/provider_billing.py:78::metered_request`.

**Schema/access:** public.billing_cost_policy; public.billing_subscriptions; public.billing_trials; public.provider_cost_schedules; public.provider_spend_controls; public.tenant_credit_balances; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_ledger; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## CREDIT-006 — Existing AI and data capabilities

Proposed behavior remains: Preserve RAG references, marketing, discovery/enrichment, forecasts and generic connectors; touch only their required gates/dependencies, not algorithms.

Acceptance specification: `AT-CREDIT-006` — Existing baseline regressions; unknown provider prices; direct service bypass. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD use(requireFeatureAccess('business_recommendations')) @ backend/src/modules/business-recommendations/route.ts:14 | REGISTERED_GUARD get(requireFeatureAccess("dashboard_analytics")) @ backend/src/modules/dashboard/route/dashboard.route.ts:19 | REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:46 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:51. UI: Feature usage dashboard; quote cost estimates; no Node data_credits/ai_credits authority.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:213:1::getFeatureAccessInfo`.

**Schema/access:** public.subscriptions

**Missing/unequal edge:** No registered Node Data/AI credit or provider-spend authority matching Python. Cited feature quota/quote/provider boundary is comparison context, not a credit-ledger equivalent.

**PYTHON entry and UI boundary:** POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99 | POST /discovery/competitors/{competitor_id}/refresh @ backend/src/ai/routers/discovery.py:162 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /competitors/sources/{source_id}/review @ backend/src/ai/routers/competitors.py:196. UI: CreditBudgets.jsx -> billingApi.getSubscription/getUsageHistory; paid calls attach credits.metering contexts.

**Exact source roots:** `backend/src/ai/billing/credits.py:156::metered | backend/src/ai/core/usage.py:525::ensure_ai_rate | backend/src/market_scraper/cost_ledger.py:182::evaluate_cost_margin_gate`.

**Schema/access:** public.competitor_product_mappings; public.products; public.scraping_cost_ledger

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
