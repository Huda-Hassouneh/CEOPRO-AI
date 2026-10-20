# Source trace refinement — PRICE

**TRACE READY FOR IMPLEMENTATION REVIEW (static source only).** Implementation/release remains BLOCKED by SOURCE-001, VERIFY-001 and the pending owner decisions below. Known absent target workflows are implementation gaps, not evidence of equivalence. This status does not authorize code edits.

Source roots are shown as a set, not a presumed sequential call chain. Actual known caller paths are in CALLER_ENTRY_JOINS.csv; branch/callback/default-transport edges are labeled in ATOMIC_CALL_EDGES.csv. Missing UI/API/worker joins are explicit. Native schema/role/concurrency/provider evidence remains unrun.

Schema: [source-verified PRICE lineage](../evidence/phase0r/SCHEMA_LINEAGE_PRICE.csv), [column operations](../evidence/phase0r/SCHEMA_COLUMNS.csv), [dynamic SQL obligations](../evidence/phase0r/DYNAMIC_SQL_OBLIGATIONS.csv). Owner decisions: ACCOUNTING-001; ENT-001; PRICE-001

## PRICE-001 — Single and bulk endpoint feature gate

Proposed behavior remains: Python pricing router is mounted without requires and pipeline has no quota reservation; add approved ai_pricing access/count around both and dashboard aliases.

Acceptance specification: `AT-PRICE-001` — Cancelled plan; bulk exceeds remaining; wrong role/product. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13 | POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/service/pricing.service.ts:15:1::authorizedProduct | backend/src/modules/pricing/service/pricing.service.ts:24:1::getPricingRecommendation | backend/src/modules/pricing/controller/pricing.controller.ts:15:1::recommendPrice`.

**Schema/access:** public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.evidence_records; public.pricing_requests; public.products; public.recommendation_outcomes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** Mounted single generation/history, no corresponding bulk endpoint identified; Python bulk must be retained and protected separately.

**PYTHON entry and UI boundary:** POST /pricing/recommend @ backend/src/ai/routers/pricing.py:11 | POST /pricing/recommend-all @ backend/src/ai/routers/pricing.py:28. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `backend/src/ai/routers/pricing.py:11::pricing_recommend | backend/src/ai/routers/pricing.py:28::pricing_recommend_all`.

**Schema/access:** public.companies; public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.demand_forecasts; public.evidence_records; public.global_competitors; public.inventory; public.invoice_items; public.invoices; public.market_price_observations; public.products; public.recommendation_outcomes; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PRICE-002 — Approved competitor provenance latest

Proposed behavior remains: Preserve Python mapped competitors and source-status evidence; compare newest observation before filtering with Node invalid-latest exclusion.

Acceptance specification: `AT-PRICE-002` — Latest invalid older valid; unsafe source; unavailable offer. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13 | POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/repo/pricing.repo.ts:75:1::getEligibleMarketPrices | backend/src/modules/pricing/service/pricing.policy.ts:27:1::comparablePrices | backend/src/modules/pricing/repo/pricing-request.repo.ts:60:1::finishPricingRequest`.

**Schema/access:** public.competitor_prices; public.competitor_product_mappings; public.evidence_records; public.pricing_requests; public.products; public.recommendation_outcomes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /pricing/recommend @ backend/src/ai/routers/pricing.py:11 | POST /pricing/recommend-all @ backend/src/ai/routers/pricing.py:28. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `backend/src/ai/pricing/data_access.py:106::load_competitor_prices | backend/src/ai/pricing/pipeline.py:111::run_price_recommendation`.

**Schema/access:** public.companies; public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.demand_forecasts; public.evidence_records; public.global_competitors; public.inventory; public.invoice_items; public.invoices; public.market_price_observations; public.products; public.recommendation_outcomes; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PRICE-003 — Freshness and FX market eligibility

Proposed behavior remains: Both actual services use cross-currency values as reference only. Resolve true differences: Node 30-day/7-day rejection versus Python >90-day annotation, newest-invalid versus latest-qualifying, no-source UNKNOWN versus Python fallback; preserve Python algorithm pending PRICE-001.

Acceptance specification: `AT-PRICE-003` — 31/91-day price; inverted FX; future observation. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15 | GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/service/pricing.service.ts:24:1::getPricingRecommendation | backend/src/modules/pricing/service/pricing.policy.ts:27:1::comparablePrices | backend/src/modules/pricing/repo/pricing.repo.ts:145:1::getExchangeRates`.

**Schema/access:** public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.evidence_records; public.pricing_requests; public.products; public.recommendation_outcomes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /pricing/recommend @ backend/src/ai/routers/pricing.py:11 | POST /pricing/recommend-all @ backend/src/ai/routers/pricing.py:28. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `backend/src/ai/pricing/pipeline.py:28::_build_cross_currency_reference | backend/src/ai/pricing/currency.py:58::get_latest_rate | backend/src/ai/pricing/data_access.py:106::load_competitor_prices`.

**Schema/access:** public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.global_competitors; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PRICE-004 — Guardrails cost floor decimals

Proposed behavior remains: Keep Python existing math; verify Node finite-number/Decimal safety and conflict where cost floor exceeds change cap.

Acceptance specification: `AT-PRICE-004` — Unknown cost; floor above 15% cap; JOD/JPY rounding. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15 | GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/service/pricing.policy.ts:58:1::enforcePriceGuardrails | backend/src/modules/pricing/service/pricing.policy.ts:77:1::localMarketTarget | backend/src/modules/pricing/service/pricing.policy.ts:17:1::roundMoney | backend/src/modules/pricing/service/pricing.service.ts:24:1::getPricingRecommendation`.

**Schema/access:** public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.evidence_records; public.pricing_requests; public.products; public.recommendation_outcomes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /pricing/recommend @ backend/src/ai/routers/pricing.py:11 | POST /pricing/recommend-all @ backend/src/ai/routers/pricing.py:28. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `backend/src/ai/pricing/guardrails.py:51::apply_price_change_guardrail | backend/src/ai/pricing/guardrails.py:65::apply_margin_guardrail | backend/src/ai/core/money.py:27::round_money`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PRICE-005 — No-market fallback demand stock

Proposed behavior remains: Retain Python estimation peer/internal margin basis, confidence caps and demand/stock holds unless owner approves policy change.

Acceptance specification: `AT-PRICE-005` — No market; cold start; stock shortage; rising/falling sales. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/service/pricing.service.ts:24:1::getPricingRecommendation`.

**Schema/access:** public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.evidence_records; public.pricing_requests; public.products; public.recommendation_outcomes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** With no comparable local-currency sources Node returns UNKNOWN and releases reservation; it does not run Python broader/peer/internal pricing fallback or demand/stock hold.

**PYTHON entry and UI boundary:** POST /pricing/recommend @ backend/src/ai/routers/pricing.py:11 | POST /pricing/recommend-all @ backend/src/ai/routers/pricing.py:28. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `backend/src/ai/pricing/estimation.py:129::build_estimate | backend/src/ai/pricing/pipeline.py:80::_demand_context | backend/src/ai/pricing/pipeline.py:111::run_price_recommendation`.

**Schema/access:** public.companies; public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.demand_forecasts; public.evidence_records; public.global_competitors; public.inventory; public.invoice_items; public.invoices; public.market_price_observations; public.products; public.recommendation_outcomes; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PRICE-006 — Request receipt replay failure accounting

Proposed behavior remains: Add Python durable pricing operation idempotency and result binding using existing usage/credit owners; bulk item settlement explicit.

Acceptance specification: `AT-PRICE-006` — Duplicate key changed product; failure after evidence commit. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15 | GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/repo/pricing-request.repo.ts:40:1::beginPricingRequest | backend/src/modules/pricing/repo/pricing-request.repo.ts:60:1::finishPricingRequest | backend/src/modules/pricing/repo/pricing-request.repo.ts:52:1::failPricingRequest | backend/src/modules/pricing/repo/pricing-request.repo.ts:26:1::recoverPricingRequests`.

**Schema/access:** public.competitor_prices; public.evidence_records; public.pricing_requests; public.products; public.recommendation_outcomes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /pricing/recommend @ backend/src/ai/routers/pricing.py:11 | POST /pricing/recommend-all @ backend/src/ai/routers/pricing.py:28. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `backend/src/ai/routers/pricing.py:11::pricing_recommend | backend/src/ai/pricing/pipeline.py:111::run_price_recommendation`.

**Schema/access:** public.companies; public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.demand_forecasts; public.evidence_records; public.global_competitors; public.inventory; public.invoice_items; public.invoices; public.market_price_observations; public.products; public.recommendation_outcomes; public.tenant_competitors

**Missing/unequal edge:** No durable pricing-specific request key/result receipt/reserve-release wrapper in mounted single/bulk handlers.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PRICE-007 — Evidence and outcomes persistence

Proposed behavior remains: Reuse Python evidence_records/recommendation_outcomes; check chk_evidence_shape category/module/explanation with actual SQL.

Acceptance specification: `AT-PRICE-007` — Missing explanation; tenant RLS; invalid confidence. NOT RUN as an implementation test.

**NODE entry and UI boundary:** POST /features/pricing/recommend @ backend/src/modules/pricing/route/pricing.route.ts:15. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/repo/pricing.repo.ts:185:1::persistPricingRecommendation | backend/src/modules/pricing/repo/pricing-request.repo.ts:60:1::finishPricingRequest`.

**Schema/access:** public.competitor_prices; public.evidence_records; public.pricing_requests; public.products; public.recommendation_outcomes; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** POST /dashboard/products/{product_id}/forecast @ backend/src/ai/routers/dashboard.py:401 | POST /pricing/recommend @ backend/src/ai/routers/pricing.py:11 | POST /competitors/{competitor_id}/enrich @ backend/src/ai/routers/competitor_enrichment.py:99 | POST /competitors @ backend/src/ai/routers/competitors.py:305 | POST /pricing/recommend-all @ backend/src/ai/routers/pricing.py:28 | POST /competitors/reclassify @ backend/src/ai/routers/competitors.py:79. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `backend/src/ai/forecasting/evidence.py:56::insert_evidence_record | backend/src/ai/pricing/evidence.py:14::insert_recommendation_outcome | backend/src/ai/pricing/pipeline.py:111::run_price_recommendation`.

**Schema/access:** public.companies; public.competitor_prices; public.competitor_product_mappings; public.currency_rates; public.demand_forecasts; public.evidence_records; public.global_competitors; public.inventory; public.invoice_items; public.invoices; public.market_price_observations; public.products; public.recommendation_outcomes; public.tenant_competitors

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.

## PRICE-008 — Modal history errors and approvals

Proposed behavior remains: Preserve Python query-parameter product_id and PriceRecommendationModal output; add history/provenance/unavailable states without automatic price mutation.

Acceptance specification: `AT-PRICE-008` — 502; no cost; stale recommendation; unauthorized apply. NOT RUN as an implementation test.

**NODE entry and UI boundary:** GET /features/pricing/history @ backend/src/modules/pricing/route/pricing.route.ts:13. UI: frontend/src/features/market-intelligence/api/pricingApi.js; usePricingRecommendation.js; PricingRecommendationContent.jsx.

**Exact source roots:** `backend/src/modules/pricing/service/pricing.service.ts:103:1::getPricingHistory | backend/src/modules/pricing/controller/pricing.controller.ts:88:1::listPricingHistory`.

**Schema/access:** public.competitor_product_mappings; public.currency_rates; public.pricing_requests; public.products; public.subscription_usage; public.subscriptions

**Missing/unequal edge:** No absence inferred from filenames; inspect exact symbols/branches and corresponding domain flow note.

**PYTHON entry and UI boundary:** Family entry boundary /pricing/recommend; /pricing/recommend-all; exact atomic caller joins in phase0r/CALLER_ENTRY_JOINS.csv; do not treat family prefix as proven caller. UI: frontend/src/features/pricing/api/pricingApi.js::pricingApi.recommend; usePriceRecommendation.js -> PriceRecommendationModal.jsx.

**Exact source roots:** `frontend/src/features/pricing/api/pricingApi.js:12:14::pricingApi.recommend | frontend/src/features/pricing/components/PriceRecommendationModal.jsx:18:1::PriceRecommendationModal`.

**Schema/access:** No direct canonical table reference in the selected helper closure; inspect caller/SQL function boundary rather than inventing a table.

**Missing/unequal edge:** Current recommendation modal exists; no equivalent Node stale-aware persisted pricing-history API in this router.

**Auth/entitlement, transaction, worker/provider and error evidence:** inspect the matching capability/repo rows in SOURCE_FUNCTION_REFERENCES, ATOMIC_CALL_EDGES, SQL_ACCESS_SOURCE_FACTS, DTO_SOURCE_REFERENCES, ATOMIC_FAILURE_AND_STATE_FACTS and EXTERNAL_BOUNDARIES. The current gate/transaction is a source fact, not a passing negative/RLS/concurrency test. External SDK/model/socket boundaries are named; private provider transport and Python credit context defaults remain explicit.
