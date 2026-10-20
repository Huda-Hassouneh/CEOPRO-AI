> Phase 0R: read [SOURCE_TRACE_CORRECTIONS.md](../SOURCE_TRACE_CORRECTIONS.md) and [PHASE0R_README.md](../PHASE0R_README.md) before relying on original source-inference wording. Native/runtime gates remain pending.

# Feature architecture — entitlements

Status: PROPOSED for architecture review; capability families ENT CREDIT. Single Python authority is already approved by user; no conflicting policy is selected.


One evaluator remains `core/usage.py::get_plan`; one Boolean dependency remains `core/entitlements.py::requires`; extend their typed result rather than introducing a parallel Node-derived evaluator. Existing data/AI credits remain in billing.credits, distinct from per-feature counters and provider USD cost/spend controls.

Python SUM: reserve conditional upsert → caller commits before work → settle actual amount or release; MAX: lock_feature plus counted mutation in same transaction, using live rows. Current `_missing_limit` returns zero only for monthly_reports/team_seats/data_credits/ai_credits; other missing limit rows become None. That is a fail-open migration hazard for newly mapped codes. Explicit disabled/zero/NULL unlimited/missing must remain distinguishable, with approved versioned backfill (ENT-001).

All 21 Node feature codes are individually crosswalked, including report_generation→monthly_reports and team_members→team_seats. Node legacy ai_queries→rag_assistant and pricing_intelligence→ai_pricing are input aliases, not independent allowances. Python-only web_searches, data_credits, ai_credits and technical AI request/concurrency safety limits remain intact. Node monitoring cadence is configuration, not a new registered feature code. Python market_perception currently inherits market_intelligence; ai_pricing and six Node Boolean codes lack independent Python grants. Do not claim a general active plan substitutes for missing feature rights.

Units: extraction ceil(bytes/1024) KB; storage MiB (bytes/1048576, displayed GB by /1024); assistant tokens; sentiment analyzed records; reports/items; product/competitor/source/seat live counts. Preserve fractional storage in live count, do not floor away over-capacity. Usage view is `routers/billing.py::_PAGE_KEYS` and frontend LIMIT_KEYS; raw `features` remain available. Plan status active/trialing only, per-period dates are UTC/calendar fallback in get_plan; trial exact ends_at respected. Custom overrides replace plan limits; test NULL override semantics explicitly.

Python connected sources counts active OWN_SYSTEM_CONNECTOR; Node COUNTED_CONNECTED_SOURCE_TYPES includes Shopify/database/GA4/website types. Python tracked_competitors is explicitly unlimited for public current plans under the credit migration while Node has MAX capacity. Keep credit enforcement; owner selects whether any fixed cap is restored, and defines what sources count (ENT-001/CATALOG-001).

Task 6 report keys: active status and membership checked before reuse; identity=(tenant,feature,period,key), actor/fingerprint binding; UUID receipt; failure release matches period/receipt; replay flag prevents unsafe late refunds. Historical current-period keys without fingerprint return conflict and require a new key. Do not run old/new report implementations simultaneously after migration.

Python provider calls: credits.metering/metered attaches tenant operation, reserve checks cost schedule/tenant balance/global or provider/model caps and kill switch, provider_call records whether request sent/usage measured, settle appends ledger; maintenance expires and conservatively charges stale reservations, reconcile/admin adjustments remain audited. Unconfigured paid provider cost blocks work. Credits.bind copies thread context; queues must serialize tenant/actor/request identity, never a live context object. Technical controls are retained even for unlimited custom feature allowances.

Target deferred action: API authenticates active principal and authorizes right → durable operation/quota/credit receipt + outbox in same transaction → worker claims lease → revalidates current subscription/membership and receipt/period → provider work outside DB lock → conditional persisted result + usage settle/checkpoint → API/UI status. No free replays after cancellation, no duplicate debit, no blanket refund after partial commit/provider billing. ACCOUNTING-001 defines billable failure and stale/partial accounting.

Cache: entitlements.forget is process-local and CACHE_SECONDS defaults 30s. Shared invalidation/version check is required for multiple API replicas and execution-time gates. Include cancellation during TTL, exact trial expiry and no stale rights on webhook assignment change.


## Verification and migration gate

Use domain rows in CAPABILITY_TRACEABILITY.csv, exact symbols in evidence/FUNCTION_CALL_INDEX.csv, and ordered SQL_OBJECT_LINEAGE.csv. Phase-specific schema/file scopes and disable strategy are in IMPLEMENTATION_PHASES.md. All applicable AT IDs require native tenant/RLS, service, HTTP, worker and frontend proof; source-level parity is not a passing test. No destructive backfill or existing customer change is authorized by this note.
