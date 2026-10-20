> Phase 0R: read [SOURCE_TRACE_CORRECTIONS.md](../SOURCE_TRACE_CORRECTIONS.md) and [PHASE0R_README.md](../PHASE0R_README.md) before relying on original source-inference wording. Native/runtime gates remain pending.

# Feature architecture — pricing

Status: PROPOSED for architecture review; capability families PRICE. Single Python authority is already approved by user; no conflicting policy is selected.


Current Python UI: PricingPage → usePriceRecommendation → pricingApi.recommend → POST `/pricing/recommend?product_id=...` (null JSON body; product_id is query) → routers/pricing.py tenant connection → pricing.pipeline.run_price_recommendation. `/recommend-all` is a second write surface. main.py mounts pricing.router without requires; no ai_pricing feature count or credits call is present in the pipeline. Credit charging is required only for actual paid provider calls, not invented for local deterministic inference; customer operation quotas remain independent.

Data dependencies: products cost/current price/currency; competitor_product_mappings and tenant_competitors/global competitors; competitor price observations with approved source/exactness/availability; exchange rates for reference; market observations and peer products for estimation; forecasting.overview and inventory/sales for demand/stock holds. `_demand_context` failure is logged and pricing continues; this must not fabricate forecasts or justify a model rewrite. Python latest-qualifying SQL can retain an older qualifying price behind a newer invalid observation; Node comparablePrices reserves latest competitor slot before validity/freshness. PRICE-001 decides the allowed evidence policy.

Python pipeline: same-currency mapped market prices → recommendation or estimation fallback (wider market/peer/internal cost basis with confidence caps) → max price change and cost-markup floor → demand/stock hold logic → evidence_records plus recommendation_outcomes → response with action/suggested price/basis/explanation/market/demand/evidence. OLD_DATA_NOTE_AFTER_DAYS=90 annotates old data rather than Node 30-day exclusion. Cross-currency `_build_cross_currency_reference` explicitly does not blend converted values into recommendation math. Both default price-change cap 15% and cost markup 10% exist; cost floor may exceed change cap, and money rounding must preserve supported currency decimals.

Node pricing.policy provides finite numeric validation, approved newest competitor evidence, 30-day market/7-day FX eligibility, currency minor-unit Decimal rounding, median/average and guardrail enforcement; pricing-request.repo supports durable request identity. Node inference client is not the target algorithm. Preserve Python recommendation/estimation/demand behavior; add validated orchestration and typed error/result persistence.

Target: shared active principal/role → approved ai_pricing gate/quota reserve with actor/product/params/period fingerprint → persist operation → run existing Python inference with approved input policy → validate finite output and evidence → atomically persist outcome and settle once. Bulk requests authorize each item and explicit aggregate/reservation policy; retries return the same persisted result only after fresh access validation. Paid external enrichment remains separate Data Credits operation and requires confirmed provider rate.

`evidence_records` chk_evidence_shape migration 20260827000000 requires forecast_id OR non-null category/source_module/explanation_text, not a guessed JSON schema. Python evidence writer already sets these; Node persists richer metric/provenance fields. Preserve or add metadata without weakening constraint. Test both FACT and UNKNOWN paths against actual native schema and RLS; a unit JSON assertion does not prove this regression fixed.

Frontend stays compatible with existing query-parameter API and modal fields; add provenance/freshness/history/unavailable/retry states and no automatic product-price mutation. Error paths: missing product 404; malformed input typed 422; forbidden rights 402/403 per existing Python envelope; provider failure truthful 502/503; replay mismatch 409. Exact public extension fields require contract snapshots in Phase 5.


## Verification and migration gate

Use domain rows in CAPABILITY_TRACEABILITY.csv, exact symbols in evidence/FUNCTION_CALL_INDEX.csv, and ordered SQL_OBJECT_LINEAGE.csv. Phase-specific schema/file scopes and disable strategy are in IMPLEMENTATION_PHASES.md. All applicable AT IDs require native tenant/RLS, service, HTTP, worker and frontend proof; source-level parity is not a passing test. No destructive backfill or existing customer change is authorized by this note.
