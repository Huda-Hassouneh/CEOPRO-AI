# Source trace refinement — ENT

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified ENT lineage](../evidence/phase0r/SCHEMA_LINEAGE_ENT.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: ACCOUNTING-001; ENT-001

## ENT-001 — All 21 feature-code grants

Proposed behavior remains: Use FEATURE_AND_ENTITLEMENT_CROSSWALK.csv; approve missing Boolean rights and aliases; one Python get_plan evaluator.

Acceptance specification: `AT-ENT-001` — Alias query; disabled Boolean; no limit row vs explicit NULL. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD use(requireFeatureAccess('business_recommendations')) @ backend/src/modules/business-recommendations/route.ts:14 | REGISTERED_GUARD get(requireFeatureAccess("dashboard_analytics")) @ backend/src/modules/dashboard/route/dashboard.route.ts:19 | REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:46 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:51 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:56 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:61 | REGISTERED_GUARD post(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/catalog.ts:287:1::canonicalizeFeatureCode | backend/src/modules/features/repo/usage.repo.ts:213:1::getFeatureAccessInfo | backend/src/middleware/validators/validateFeatures.ts:77:35::requireEntitlement | backend/src/middleware/validators/validateFeatures.ts:35:37::requireFeatureAccess`.

**Schema/access:** public.data_sources; public.plan_features; public.products; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/subscription @ backend/src/ai/routers/billing.py:101 | GET /competitors/landscape @ backend/src/ai/routers/competitors.py:121 | GET /discovery/competitors @ backend/src/ai/routers/discovery.py:123 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51 | POST /auth/invitations/{token}/accept @ backend/src/ai/routers/auth.py:743 | POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /dashboard/products/{product_id}/forecast @ backend/src/ai/routers/dashboard.py:401. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:139::get_plan | backend/src/ai/core/entitlements.py:51::requires | backend/src/ai/core/usage.py:263::require_entitlement`.

**Schema/access:** public.billing_trials; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-002 — Missing limits fail closed

Proposed behavior remains: Python _missing_limit only fails closed for four credit-era codes; make all newly mapped rights explicit without altering existing contracts silently.

Acceptance specification: `AT-ENT-002` — Missing ai_pricing row; missing connected source row. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD use(requireFeatureAccess('business_recommendations')) @ backend/src/modules/business-recommendations/route.ts:14 | REGISTERED_GUARD get(requireFeatureAccess("dashboard_analytics")) @ backend/src/modules/dashboard/route/dashboard.route.ts:19 | REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:46 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:51 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:56 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:213:1::getFeatureAccessInfo | backend/src/modules/features/service/entitlement-policy.ts:13:1::getConsumptionBlockReason`.

**Schema/access:** public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/image @ backend/src/ai/routers/marketing.py:543 | POST /marketing/campaigns/{campaign_id}/remove-background @ backend/src/ai/routers/marketing.py:590 | POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /reviews/import @ backend/src/ai/routers/reviews.py:48 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99 | POST /competitors/reclassify @ backend/src/ai/routers/competitors.py:79. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:324::_missing_limit | backend/src/ai/core/usage.py:333::reserve | backend/src/ai/core/usage.py:485::capacity_left`.

**Schema/access:** public.billing_trials; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_usage_counters; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-003 — SUM reservations integer units

Proposed behavior remains: Reuse Python conditional upsert, invalid-amount rejection and reserve/settle; add request receipts for newly deferred work.

Acceptance specification: `AT-ENT-003` — Boolean/fraction/NaN/negative amount; units KB vs bytes. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/imports/:kind @ backend/src/modules/dataconnection/route/dataconnection.route.ts:82 | POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33 | POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15 | POST /features/rag/documents @ backend/src/modules/rag/route/rag.route.ts:42 | POST /features/rag/query @ backend/src/modules/rag/route/rag.route.ts:55 | GET /features/rag/sessions @ backend/src/modules/rag/route/rag.route.ts:30 | GET /features/rag/sessions/:session_id @ backend/src/modules/rag/route/rag.route.ts:31 | POST /features/sentiment/analyze-pending @ backend/src/modules/sentiment/route/sentiment.route.ts:23. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:289:1::reserveFeatureUsageInTransaction | backend/src/modules/features/repo/usage.repo.ts:392:1::releaseFeatureUsageInTransaction | backend/src/modules/features/repo/usage.repo.ts:519:31::incrementUsage`.

**Schema/access:** public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/image @ backend/src/ai/routers/marketing.py:543 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /reviews/import @ backend/src/ai/routers/reviews.py:48 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | POST /sentiment/analyze-pending @ backend/src/ai/routers/sentiment.py:13 | POST /discovery/competitors/{competitor_id}/analysis @ backend/src/ai/routers/discovery.py:245 | POST /discovery/market/analysis @ backend/src/ai/routers/discovery.py:286 | GET /reports/sales/export @ backend/src/ai/routers/reports.py:122. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:333::reserve | backend/src/ai/core/usage.py:284::record | backend/src/ai/core/usage.py:302::settle | backend/src/ai/core/usage.py:473::release`.

**Schema/access:** public.billing_trials; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_usage_counters; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-004 — Period-bound idempotency replay

Proposed behavior remains: Preserve Task 6 monthly report fingerprint actor period receipt and replay rules; extend only after approval to other operations.

Acceptance specification: `AT-ENT-004` — Cancelled subscription same key; next period same key; stale refund. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/pricing/repo/pricing-request.repo.ts:34:1::lookupPricingRequest | backend/src/modules/pricing/repo/pricing-request.repo.ts:40:1::beginPricingRequest | backend/src/modules/pricing/repo/pricing-request.repo.ts:52:1::failPricingRequest`.

**Schema/access:** public.pricing_requests; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** pricing request keys are tenant/user/request with product binding, not report period+fingerprint+receipt semantics; no exact equivalent report key authority.

**PYTHON entry and UI boundary:** GET /reports/sales/export @ backend/src/ai/routers/reports.py:122. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:365::reserve_request | backend/src/ai/core/usage.py:439::release_request | backend/src/ai/routers/reports.py:122::export_sales_report`.

**Schema/access:** public.billing_trials; public.companies; public.invoice_items; public.invoices; public.metered_request_keys; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_usage_counters; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-005 — MAX live capacity locks

Proposed behavior remains: Reuse lock_feature plus mutation in same transaction, live counts and last-slot tests for each mapped resource.

Acceptance specification: `AT-ENT-005` — Two product/source/seat creates; downgrade below occupancy. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/rag/documents @ backend/src/modules/rag/route/rag.route.ts:42 | REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:56 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | POST /data-connection/imports/:kind @ backend/src/modules/dataconnection/route/dataconnection.route.ts:82 | POST /data-connection/imports/:kind/previews/:draftId/confirm @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:734:1::assertFeatureCapacity | backend/src/modules/features/service/capacity.service.ts:23:1::getCurrentCapacityUsage | backend/src/modules/products/repo/product-capacity.ts:4:1::lockProductCatalog`.

**Schema/access:** public.data_sources; public.plan_features; public.products; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /marketing/campaigns/{campaign_id}/image @ backend/src/ai/routers/marketing.py:543 | POST /marketing/campaigns/{campaign_id}/remove-background @ backend/src/ai/routers/marketing.py:590 | POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99 | POST /competitors/reclassify @ backend/src/ai/routers/competitors.py:79 | POST /products @ backend/src/ai/routers/products.py:549. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:225::lock_feature | backend/src/ai/core/usage.py:485::capacity_left | backend/src/ai/core/usage.py:498::ensure_capacity | backend/src/ai/routers/products.py:336::create_product`.

**Schema/access:** public.billing_trials; public.inventory; public.products; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-006 — Connected-source counting

Proposed behavior remains: Node counts active listed types; Python counts active OWN_SYSTEM_CONNECTOR. Decide count population for dedicated stores and existing connections.

Acceptance specification: `AT-ENT-006` — Reconnect same source; disabled source; legacy website source. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/sources @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | PATCH /data-connection/sources/:sourceId @ backend/src/modules/dataconnection/route/dataconnection.route.ts:31 | GET /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:89 | POST /data-connection/store/shopify/authorize @ backend/src/modules/dataconnection/store/routes.ts:31 | POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33 | WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:56 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | POST /data-connection/store/shopify/complete @ backend/src/modules/dataconnection/store/routes.ts:30. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:461:1::getConnectedDataSourceCapacityInTransaction | backend/src/modules/features/service/capacity.service.ts:23:1::getCurrentCapacityUsage | backend/src/modules/dataconnection/store/connections.repo.ts:15:1::sourceSlot`.

**Schema/access:** public.data_sources; public.products; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/subscription @ backend/src/ai/routers/billing.py:101 | POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /marketing/campaigns/{campaign_id}/image @ backend/src/ai/routers/marketing.py:543 | POST /marketing/campaigns/{campaign_id}/remove-background @ backend/src/ai/routers/marketing.py:590 | POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /onboarding/connect/database @ backend/src/ai/routers/onboarding.py:97. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:233::_live_used | backend/src/ai/routers/onboarding.py:133::onboarding_connect_api | backend/src/ai/routers/onboarding.py:97::onboarding_connect_database`.

**Schema/access:** public.billing_trials; public.data_sources; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-007 — Document storage and cleanup

Proposed behavior remains: Preserve Python rag_documents_metadata plus tenant_storage_objects; compare Node retained_document_bytes; reserve before object write and release exactly once.

Acceptance specification: `AT-ENT-007` — Object succeeds DB fails; deletion retry; orphaned upload. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:56 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:66 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:72 | REGISTERED_GUARD post(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:77 | GET /features/rag/documents @ backend/src/modules/rag/route/rag.route.ts:33 | DELETE /features/rag/documents/:document_id @ backend/src/modules/rag/route/rag.route.ts:39. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/service/capacity.service.ts:23:1::getCurrentCapacityUsage | backend/src/modules/rag/repo/rag.repo.ts:318:1::storageInTransaction | backend/src/modules/rag/repo/rag.repo.ts:305:1::deleteStoredRagDocument`.

**Schema/access:** public.data_sources; public.products; public.rag_documents_metadata; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/subscription @ backend/src/ai/routers/billing.py:101 | POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /marketing/campaigns/{campaign_id}/image @ backend/src/ai/routers/marketing.py:543 | POST /marketing/campaigns/{campaign_id}/remove-background @ backend/src/ai/routers/marketing.py:590 | POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:233::_live_used | backend/src/ai/core/storage_ledger.py:10::record | backend/src/ai/core/storage_ledger.py:22::forget`.

**Schema/access:** public.tenant_storage_objects

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-008 — Execution-time access and budgets

Proposed behavior remains: Introduce shared Python execution authorization and receipt ownership for jobs; revalidate membership/status/feature before provider calls and before canonical commit.

Acceptance specification: `AT-ENT-008` — Cancelled while queued; revoked actor; quota period rollover. NOT RUN as an implementation test.

**NODE entry and UI boundary:** WORKER store-connectors.worker.ts due.map -> syncStorePage @ backend/src/workers/store-connectors.worker.ts:39 | PATCH /data-connection/sources/:sourceId @ backend/src/modules/dataconnection/route/dataconnection.route.ts:31 | DELETE /data-connection/sources/:sourceId/connection @ backend/src/modules/dataconnection/route/dataconnection.route.ts:36 | GET /data-connection/store/:sourceId/privacy-reports @ backend/src/modules/dataconnection/store/routes.ts:34 | POST /data-connection/store/shopify/authorize @ backend/src/modules/dataconnection/store/routes.ts:31 | POST /data-connection/store/detect @ backend/src/modules/dataconnection/store/routes.ts:32 | POST /data-connection/store/connect @ backend/src/modules/dataconnection/store/routes.ts:33 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/dataconnection/store/sync.repo.ts:91:1::claimStorePage | backend/src/modules/dataconnection/store/sync.repo.ts:115:1::syncStorePage | backend/src/modules/dataconnection/store/context.ts:6:1::storeContext | backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:458:22::ingestionWorkerRepo.processClaimedJob`.

**Schema/access:** public.companies; public.data_sources; public.import_sale_identities; public.import_staging_rows; public.ingestion_jobs; public.inventory; public.invoice_items; public.invoices; public.product_price_history; public.products; public.store_connections; public.store_inventory_links; public.store_inventory_locations; public.store_order_exclusions; public.store_order_item_links; public.store_order_links; public.store_product_links; public.store_sale_links; public.subscriptions; public.tenant_users; public.transactions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272 | POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/image @ backend/src/ai/routers/marketing.py:543 | POST /marketing/campaigns/{campaign_id}/remove-background @ backend/src/ai/routers/marketing.py:590 | POST /onboarding/connect/api @ backend/src/ai/routers/onboarding.py:133 | WORKER_OR_PRIVATE python -m src.market_scraper.connector_worker @ backend/src/market_scraper/connector_worker.py:120 | POST /competitors/sources/{source_id}/review @ backend/src/ai/routers/competitors.py:196. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:328::_require_active | backend/src/market_scraper/connector_worker.py:80::run_connector_syncs_for_tenant | backend/src/market_scraper/enqueue.py:65::enqueue_collection`.

**Schema/access:** public.companies; public.competitor_product_mappings; public.data_sources; public.import_staging_rows; public.ingestion_jobs; public.products; public.scraping_cost_ledger; public.tenant_storage_objects

**Missing/unequal edge:** Generic connector service actor and due-source polling do not invoke a shared execution-time commercial authorization at every queue/provider/commit boundary.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-009 — Plan cache invalidation

Proposed behavior remains: Replace process-only forget with bounded shared version invalidation while preserving short cache; mutations and webhooks invalidate all replicas.

Acceptance specification: `AT-ENT-009` — Two API replicas; trial expires during cache TTL. NOT RUN as an implementation test.

**NODE entry and UI boundary:** REGISTERED_GUARD use(requireFeatureAccess('business_recommendations')) @ backend/src/modules/business-recommendations/route.ts:14 | REGISTERED_GUARD get(requireFeatureAccess("dashboard_analytics")) @ backend/src/modules/dashboard/route/dashboard.route.ts:19 | REGISTERED_GUARD post(requireEntitlement("data_integration")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:26 | REGISTERED_GUARD get(requireEntitlement("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:41 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:46 | REGISTERED_GUARD get(requireFeatureAccess("document_extraction")) @ backend/src/modules/dataconnection/route/dataconnection.route.ts:51. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:213:1::getFeatureAccessInfo`.

**Schema/access:** public.subscriptions

**Missing/unequal edge:** getFeatureAccessInfo reads database directly; no equivalent Python-style process entitlement cache invalidation flow needed on this Node path.

**PYTHON entry and UI boundary:** POST /dashboard/products/{product_id}/forecast @ backend/src/ai/routers/dashboard.py:401 | POST /billing/trial @ backend/src/ai/routers/billing.py:187 | POST /billing/webhook @ backend/src/ai/routers/billing.py:349 | POST /discovery/competitors/{competitor_id}/refresh @ backend/src/ai/routers/discovery.py:162 | POST /discovery/competitors/{competitor_id}/intel/review @ backend/src/ai/routers/discovery.py:194 | POST /reviews/import @ backend/src/ai/routers/reviews.py:48 | GET /forecasting/overview @ backend/src/ai/routers/forecasting.py:34 | POST /forecasting/refresh @ backend/src/ai/routers/forecasting.py:53 | POST /extraction/upload @ backend/src/ai/routers/extraction.py:272. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/entitlements.py:27::_plan | backend/src/ai/core/entitlements.py:45::forget | backend/src/ai/core/tenant_cache.py:46::bump`.

**Schema/access:** public.billing_trials; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-010 — Failure release settle and crash

Proposed behavior remains: Use durable operation state; partial committed work cannot be refunded as if no work occurred; maintain Python stale-credit conservative policy pending owner decision.

Acceptance specification: `AT-ENT-010` — Worker crash after provider charge; partial canonical promotion; retry twice. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /data-connection/ @ backend/src/modules/dataconnection/route/dataconnection.route.ts:94 | POST /features/extraction/upload @ backend/src/modules/features/route/features.route.ts:33 | POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15 | GET /features/rag/sessions @ backend/src/modules/rag/route/rag.route.ts:30 | GET /features/rag/sessions/:session_id @ backend/src/modules/rag/route/rag.route.ts:31 | POST /features/rag/query @ backend/src/modules/rag/route/rag.route.ts:55 | GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13 | WORKER_OR_PRIVATE Node data-ingestion.worker.ts module startup @ backend/src/workers/data-ingestion.worker.ts:253. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/repo/usage.repo.ts:392:1::releaseFeatureUsageInTransaction | backend/src/modules/pricing/repo/pricing-request.repo.ts:17:1::expired | backend/src/modules/dataconnection/repo/ingestion-worker.repo.ts:521:24::ingestionWorkerRepo.scheduleRetryOrFail`.

**Schema/access:** public.pricing_requests; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /reports/sales/export @ backend/src/ai/routers/reports.py:122 | WORKER_OR_PRIVATE python -m scripts.billing_admin @ backend/scripts/billing_admin.py:51 | WORKER_OR_PRIVATE main.py lifespan -> maintenance thread @ backend/src/ai/billing/maintenance.py:22 | POST /marketing/campaigns @ backend/src/ai/routers/marketing.py:183 | POST /marketing/campaigns/{campaign_id}/generate-image @ backend/src/ai/routers/marketing.py:812 | POST /discovery/competitors/{competitor_id}/analysis @ backend/src/ai/routers/discovery.py:245 | POST /discovery/market/analysis @ backend/src/ai/routers/discovery.py:286 | POST /rag/query @ backend/src/ai/routers/rag.py:60 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/core/usage.py:439::release_request | backend/src/ai/billing/credits.py:662::expire_stale_reservations | backend/src/ai/billing/credits.py:527::settle`.

**Schema/access:** public.billing_cost_policy; public.metered_request_keys; public.provider_cost_schedules; public.tenant_credit_balances; public.tenant_usage_counters; public.usage_ledger

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## ENT-011 — Usage dashboard and conversions

Proposed behavior remains: Keep billing API feature raw units and customer view conversion KB/1024, MB/1024; preserve internal safety limits.

Acceptance specification: `AT-ENT-011` — Unlimited vs absent; 402 remaining; exhausted allowance UI. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /subscriptions/current/usage @ backend/src/modules/features/route/feature-plan.route.ts:71. UI: billingApi.getSubscriptionUsage; requireFeatureAccess/requireEntitlement at mounted feature routers.

**Exact source roots:** `backend/src/modules/features/service/usage.service.ts:6:28::usageService.getTenantUsageDashboard | backend/src/modules/features/controller/usage.controller.ts:8:17::usageController.getDashboard | frontend/src/features/billing/api/billingApi.js:48:24::normalizeUsage`.

**Schema/access:** public.data_sources; public.plan_features; public.products; public.subscription_usage; public.subscriptions; public.tenant_competitors; public.tenant_users

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** GET /billing/subscription @ backend/src/ai/routers/billing.py:101. UI: billingApi.getSubscription plus PlanGate.jsx; backend usage/entitlements and caller gates.

**Exact source roots:** `backend/src/ai/routers/billing.py:101::get_subscription | backend/src/ai/core/usage.py:241::current_usage | frontend/src/features/billing/api/billingApi.js:32:1::mapPlan`.

**Schema/access:** public.billing_cost_policy; public.billing_customers; public.billing_subscriptions; public.billing_trials; public.tenant_credit_balances; public.tenant_entitlement_overrides; public.tenant_plan_assignments; public.tenant_usage_counters; public.tenant_users; public.usage_features; public.usage_plan_entitlements; public.usage_plan_limits; public.usage_plans

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
