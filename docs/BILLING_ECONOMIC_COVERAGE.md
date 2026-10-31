# Billing economic coverage and pre-PAYG inventory

Source review: integrated baseline `0bfd1bd55d2b92186addbaf264143042c8e8b3dd`.
Read-only local inspection: 2026-10-31. This report distinguishes source facts,
local configuration, and unavailable economic evidence. No provider was called.

## Root cause and authorities

The feature catalog stores executable allowance units, aggregation/reset behavior
and labels, not a complete provider bill of materials. It has 16 usage-feature
identifiers; three of those also appear as module entitlements. Three additional
baseline entitlements make **19 distinct supported identifiers**. There are three
active self-serve Standard Plans; two retired Standard packages remain for history.

Provider schedules already initialize through migrations: public/self-hosted zero
costs, conditional free-image accounts, missing paid rates, and two approved Groq
token rates. Re-entering all these manually is unnecessary. However, an allowance
such as sentiment records does not imply a hosted LLM bill: the classifier runs
locally. Studio previously required manual coverage for every capability. It also
requires an explicit analysis policy: the inspected local database has **zero**
analysis policies. No migration may invent owner allocations, utilization, margin
or FX assumptions just to remove that blocker.

Current authority chain:

* `core/usage.py`, `billing/credits.py`, provider adapters: actual enforced usage.
* `usage_features`, `usage_plan_limits`, `usage_plan_entitlements`: catalog units
  and supported packages; assignment snapshots retain historical terms.
* `provider_cost_schedules`: actual USD provider cost, with owner before/after
  audit via `billing.admin.set_price` / `billing_provider_accounting`.
* `billing_custom_cost_rates` and approved bindings: separate versioned quotation
  economics. Their rates are not automatically actual provider-spend prices.
* `billing_cost_policy.credit_usd_value`: USD exposure per Credit, currently
  initialized at 0.01. This is not a vendor rate or customer selling price.
* `billing_plan_analysis_policies`: explicit immutable Studio assumptions.
* `billing_plan_prices` / Stripe catalog and frozen subscriber terms: commercial
  authority, untouched by analysis and bootstrap.

## Feature → economic requirements

Paths below are relative to `backend/src/ai/` unless prefixed `market_scraper/`
(which is relative to `backend/src/`). A/D means AI/Data Credits. A+D denotes
possible downstream calls to both pools, not two charges for the same call.
"Internal" still requires owner infrastructure/support assumptions; it is not
a zero-total-cost claim. Provider classes and metric/status detail follow below.

| Identifier | Customer capability/unit | Consumption | Runtime provider path / metric | Incremental external charge? | Source / exact remaining requirement |
|---|---|---|---|---|---|
| ai_credits | AI spend allowance / Credits | A pool | LLM input/output tokens; images | No: pool exposure itself | `billing/credits.py:provider_call`; finite allowance + Credit value + owner utilization/FX |
| data_credits | Data spend allowance / Credits | D pool | Paid collector requests/records | No: pool exposure itself | `market_scraper/provider_billing.py:metered_request`; same requirements |
| rag_assistant | Assistant / tokens | A+D | Configured LLM; optional research/search | No, already in pools | `routers/rag.py`, `rag/llm_client.py`, `research/research.py`; provider alternatives below |
| marketing_image_generation | Marketing / images | A | Image pool; LLM copy/prompt | No, already in A | `marketing/image_generation.py:generate_image`, `routers/marketing.py`; conditional free tiers need verification |
| web_searches | External search / searches | D | Tavily/Brave/CSE/SearXNG request | No, already in D | `market_scraper/web_search.py`, `provider_billing.py`; configured search provider rate/credentials |
| tracked_competitors | Competitor capacity | D downstream | Discovery/enrichment; request/record | No, already in D | `market_scraper/tenant_discovery.py`, `competitor_enrichment.py`; terms/approvals depend on collection path |
| competitor_management | Monitoring module | A+D | Collectors; optional LLM comparison | No, already in pools | `market_scraper/competitor_enrichment.py`, `market_inputs/competitor_analysis.py`; AI analysis also reserves assistant tokens |
| market_intelligence | Market evidence/module | A+D downstream | MPI itself local; optional collector/research/LLM paths | No, already in pools | `mpi/pipeline.py`, `market_inputs/competitor_intel.py`, `research/research.py`; do not bill hosted inference for deterministic MPI scoring |
| sentiment_analysis | Review sentiment / records | Neither for local classification | Local XLM-R model; optional star-rating fallback | No known external unit charge | `sentiment/model.py:classify_or_unavailable`, `sentiment/pipeline.py`; model weights/runtime capacity, internal allocation |
| document_extraction | Upload parsing / KB | Neither for upload parser | Local adapters/OCR/regex | No known external unit charge | `extraction/durable_uploads.py`, `structured_business.py`, `file_dispatch.py`; OCR/model/dependency availability and allocation. Optional discovery vision is a separate D-funded path |
| document_storage_mb | Document capacity / MB | Neither | Local/object storage | Internal allocation | `core/usage.py:_LIVE_COUNTS`, `core/storage_ledger.py`; real storage allocation required |
| connected_data_sources | Connector capacity / sources | Neither for connection capacity | Tenant-authorized stores/APIs | No blanket per-connection vendor price | `core/usage.py`, `market_scraper/connector_sync.py`; valid tenant credentials/source approval; paid discovery handled separately |
| tracked_products | Product capacity / products | Neither for capacity | Canonical local product records | Internal allocation; D discovery separate | `core/usage.py`, `extraction/promotion.py`; capacity/storage allocation |
| monthly_reports | Export allowance / reports | Neither for local exports | CSV/JSON/PDF generation | Internal allocation | `routers/reports.py:count_report`; job/CPU/storage allocation |
| team_seats | Active members / seats | Neither | Local membership | Internal allocation | `core/usage.py:_LIVE_COUNTS`; support/operations allocation |
| demand_prediction | Forecast module | Neither for forecast | Local forecasting model | Internal allocation | `forecasting/authorization.py`, `forecasting/pipeline.py`; model/data/runtime readiness |
| dashboard_analytics | Dashboard baseline | Neither for local queries | Local DB calculations | Internal allocation | `routers/dashboard.py`; real infrastructure allocation |
| product_management | Product management baseline | Neither for local management | Local product operations | Internal allocation | `core/usage.py:TRACKED_PRODUCTS`; external discovery separate |
| data_integration | Import/connection baseline | Neither for local ingestion | Local imports/authorized connectors | Internal allocation | `market_scraper/connector_sync.py`, `extraction/file_dispatch.py`; tenant source credentials/terms independent |

All 19 now have cited runtime coverage classifications (`economic_catalog.py`,
version `runtime-economics-2026-10-v1`). The six non-pool Credit-funded capability
groups plus the two pools require **no additional vendor charge for the same
spend**. Eleven identifiers need internal allocation. Zero require a proven
additional vendor charge outside the existing pools in current runtime paths.
Unknown future capabilities stay unmapped rather than defaulting to free.

## Provider units, cost evidence and operational prerequisites

The alternatives below are conditional. Do not sum every provider as though all
are used for one operation. Runtime configuration, fallback selection, source
policy and availability select the actual call.

| Provider/path | Accounting key / units | Canonical rate evidence | Local configuration observed | Credentials/approval requirements |
|---|---|---|---|---|
| Groq LLM | ai/groq/model/input_token, output_token | Approved model `openai/gpt-oss-20b`: USD .075 and .30 per million, 2026-10-28; verified catalog v1 | Both rows owner-configured with dates; key present | GROQ_API_KEY; different GROQ_MODEL requires corresponding verified units |
| Local LLM | ai/local/*/input_token, output_token | Zero external charge, migration source; no verification date | No explicit local URL in inspected integrations | Actual local server/models/capacity; default runtime routing can differ from explicit configuration |
| HF / paid LLM alternatives | ai/huggingface or paid/configured model/token units | Missing for unconfigured model; no fabricated wildcard rate | HF token absent; paid alternative not certified | HUGGINGFACE_API_TOKEN + HUGGINGFACE_LLM_MODEL; or PAID_LLM_BASE_URL/API_KEY with optional model override |
| Tavily | data/tavily/search/request | Canonical missing; plan/free credit marketing is not authoritative marginal price | Key and dated owner schedule present | TAVILY_API_KEY; actual account terms, source/date/finality |
| Brave | data/brave_search/search/request | Missing | Key absent | BRAVE_SEARCH_API_KEY |
| Google CSE | data/google_cse/search/request | Missing | Key/CX absent | GOOGLE_CUSTOM_SEARCH_API_KEY + GOOGLE_CUSTOM_SEARCH_CX; service/account eligibility |
| Google Places | data/google_places/text_search/request | Missing | Keys absent | GOOGLE_PLACES_API_KEY or GOOGLE_MAPS_API_KEY; PLACES_TERMS_APPROVAL_REFERENCE for review storage; source/tenant policy |
| Google geocoding | data/google_geocoding/geocode/request | Missing | Keys absent | Places/Maps key; usage terms |
| Apify | data/apify/actor_run/record | Missing, non-final; actual run reconciliation required | Tokens absent | APIFY_API_TOKEN or APIFY_TOKEN; SOCIAL_CONTENT_APPROVAL_REFERENCE for stored social posts; actor/source rules |
| SerpAPI | data/serpapi/search/request | Runtime adapter existed without initial row; new NULL placeholder | Not certified | SERPAPI_API_KEY; actual account rate |
| Gemini discovery vision | data/gemini_vision/read_image/request | Runtime adapter existed without initial row; new NULL placeholder | GEMINI_API_KEYS absent | GEMINI_API_KEYS and DISCOVERY_VISION_OCR selection; not the AI image-generation accounting key |
| SearXNG | data/searxng/search/request | Zero per-provider request; unverified date | URL absent | Actual self-hosted instance/hosting/availability |
| HF, Cloudflare, Together, Gemini images | ai/provider/image_generation/image | Historical conditional free-tier zero rows, **unverified**, not proof of actual account terms | Keys/accounts absent in inspected integration settings | Matching provider keys/accounts; validate free-plan eligibility or replace with actual paid rate |
| Pollinations / AI Horde images | ai/provider/image_generation/image | Historical zero rows, unverified dates | AI Horde anonymous path may be selected; Pollinations runtime now requires a key | POLLINATIONS_API_KEYS for Pollinations; AI Horde optional HORDE_API_KEYS; pool enablement, availability and acceptable use |
| Local images | ai/local/image_generation/image | Zero external unit charge, unverified date | No explicit local image URL in inspected integrations | LOCAL_IMAGE_BASE_URL(S), server/models; hosting allocation |
| OSM/Overpass, Nominatim, Photon, Wikidata, Overture, GDELT | Public data requests | Existing zero rows, no verification date; adapter bypasses paid metering for allowlisted public hosts | Actual network/availability untested | Public API/dataset terms/rate limits; optional server configuration; no invented keys |
| OpenFoodFacts / YouTube | Public allowlisted hosts/paths | No per-call paid schedule required by adapter | YouTube key absent | YouTube key/quota; EXTERNAL_COMMENTS_APPROVAL_REFERENCE for comment storage; source rules |
| Arbitrary remote hosts | data/unlisted:host/request/request | Unknown paid host fails closed, never implicitly free | Depends on selected source | Explicit operator verification, source terms/robots/tenant approval; cannot preseed infinite hosts |

Local presence checks disclose booleans only; no key validity, legal sufficiency,
provider health or external pricing was independently verified. The inspected
normal DB also has a synthetic owner accounting schedule: it is preserved but
excluded from canonical coverage counts. Catalog provenance is derived from the
stored installer/version marker; all other actors remain owner/operator. Historical
sources, verification/finality and actual owner reasons remain in accounting/audit.

## Bootstrap lifecycle and boundaries

Forward migration `20261119000000_billing_catalog_reconciliation.sql` installs
`billing_catalog_reconcile()`, executable only by installation authority. The
existing migration runner invokes it after migrations on repeat setup too.
API startup/request code never invokes it. A table lock serializes rate writers.
The function checks row existence, including NULL, before any insert. It does not
use the older `if_missing` meaning of "price is non-NULL" to overwrite an owner.
Approved missing Groq values use the same manual-owner accounting command and
constraints. The two unpriced runtime keys receive informational NULL entries,
because manual approved-price validation correctly refuses a missing price.

Every actual insert records `billing_catalog_bootstrap`, version, actor/session,
source and complete row evidence. Existing rows create no duplicate version/audit.
An entry previously created then removed is not resurrected. Changed defaults do
not update existing rows. Runtime roles get no bootstrap execute or table grant.
Earlier applied seed migrations are unchanged. Custom quotation rates, bindings,
policies, approvals and financial/assignment records are not seeded by this work.

Studio uses canonical coverage only where the explicit owner policy lacks it.
It freezes that catalog/version/source evidence with each analysis. Explicit
coverage remains visible and takes precedence, except a duplicate external charge
for a Credit-funded capability blocks a recommendation with
`CREDIT_COVERAGE_CONFLICT`. Credit exposure, observed spend, quoted vendor rates
and internal allocations are never silently added together for the same cost.

## Pre-PAYG readiness: counts and denominator

| Question | Confirmed result |
|---|---|
| Supported distinct billable/catalog identifiers | 19: 16 usage identifiers + 3 extra baseline entitlements |
| Complete source-backed consumption/coverage mappings | 19/19; this does **not** mean fully calibrated economics |
| Credit-funded identifiers | 8 including 2 Credit pools; 6 consuming capability groups |
| Internal-allocation identifiers | 11; actual owner allocation values are unavailable |
| Proven additional costs outside Credit pools | 0 current capability groups |
| Fresh canonical schedules after reconciliation | 26: 2 verified Groq token units, 16 unverified historical zero rows, 8 missing paid unit rates |
| Missing fixed paid keys | Google Places, CSE, geocoding, Apify, Brave, Tavily, SerpAPI, Gemini vision; dynamic HF/paid/changed-model and unlisted-host keys additionally need explicit configuration |
| Feature groups exposed to missing provider alternatives | 6 Credit-consuming groups; all alternatives are not mandatory |
| Feature groups exposed to unverified alternatives | Same 6 groups through image/local/data alternatives; not 6 separate additive costs |
| Credentials required | Hosted LLM, keyed image/search/Places/Apify/vision and tenant connectors; see provider matrix |
| Approval requirements | Places review storage, external comment storage, social content storage, plus existing per-source terms/robots/tenant gates |
| Safely analyzed active Standard Plans in inspected local state | **0/3 = 0%**: no explicit Studio analysis policy; this task does not invent one |
| Coverage mapping of active Standard Plan identifiers after this change | 100% of included known identifiers; pricing still requires owner economic assumptions |
| Fully calibrated feature economics in inspected local state | 0/19 certified; internal allocation/utilization/FX policy missing, not false zero costs |

These are different denominators. A bounded Credit-exposure plan model can be
calculated after an owner supplies its assumptions without pretending every
optional paid provider is configured. It is not a certification of that provider's
readiness or of a per-feature unit selling price. Unverified material **additional**
rates remain INCOMPLETE DATA. Bootstrap cannot truthfully turn current safe-plan
coverage from 0% into 100% without the missing business inputs.

Before designing PAYG: verify selected provider/account rates and metering units;
measure reliable settled usage and final run costs; resolve conditional free-tier
assumptions; record internal allocations/utilization/FX and commercial policy;
test legal/tenant gates and operational readiness; determine customer rate and
allowance contracts separately from provider cost. No PAYG tables, customer unit
rates, top-ups, overage charging or payment flows are introduced here.

For normal operation see [Platform Billing Owner Manual](PLATFORM_BILLING_OWNER_MANUAL.md).

## Verification evidence

All database writes below were confined to explicitly disposable test databases.

* Full billing/Custom Plan/Provider Accounting/Studio/Credits/allowances plus
  approved-provider catalog regression: **453 passed**, no skips. Command:
  `dev.ps1 test --suite backend --pytest-args tests/billing src/ai/tests/test_credits_integration_db.py src/ai/tests/test_usage_integration_db.py src/ai/tests/test_provider_pricing_bootstrap_integration_db.py -q`.
  Evidence: `.dev/evidence/tests/5296ac928967/backend.log`.
* Final reconciliation/removal-history/changed-default tests, Studio and browser
  acceptance, plus approved catalog migration tests: **57 passed**, no skips.
  Evidence: `.dev/evidence/tests/959e3c3c9003/backend.log`. This focused run followed
  the final audit-receipt preservation change. Fresh/repeat **154 migrations**,
  restricted password login and **122 FORCE RLS tables** passed.
* Browser scenarios: English owner, Arabic/RTL mobile owner, tenant denial and
  missing external rate all passed. Actual production Billing components/API and
  disposable PostgreSQL were used with explicit synthetic identity injection;
  this is not external authentication/provider acceptance. Both owner scenarios
  open coverage/readiness, verify default policy choices, change AI Credits in
  simulation, observe changed economics, and verify the real plan stays unchanged.
* `dev.ps1 test --suite frontend`: **244 passed**, lint PASS, production build
  PASS. Existing unresolved-font and ineffective-dynamic-import build warnings
  remain; neither is introduced by this billing change.
* Read-only normal-database fingerprints before/after were identical for provider
  schedules, plan catalog/limits/prices, subscriptions, payments, trials,
  assignments, Credit balances, Custom quotes/cost rates and Studio policies.
  `.dev/evidence/billing-catalog/normal-comparison.json` confirms the new migration
  is absent from that database. No normal migration or external financial action
  was performed. The running normal services were not restarted for this task.

The focused native test confirms the fresh canonical count of 26 schedules
(8 missing, 16 unverified, 2 verified); these are not fabricated complete rates.
Remaining owner assumptions and operational prerequisites are listed above.
