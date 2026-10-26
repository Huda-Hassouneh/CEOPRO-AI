# KEEL remaining integration acceptance - 2026-10-26

## Current verdict

**READY FOR INTEGRATION REVIEW** for the implemented and guarded scope. No known critical integration-caused defect remains in the exercised paths. This is not full Node feature parity, merchant certification, production certification, deployment approval, or approval to enable automatic financial processing.

The application changes are integrated locally into `integration/keel-full-migration` at application revision `05874e8df27ff71a0b984a88e7e437199cc72de1`. The final handoff commit contains documentation only; its exact hash is recorded in the external master handoff and acceptance mirror after commit. Source and evidence continue from `a00669dd8500dcce7dba9d94e2fbfac5a22d8808`; completed billing/Stripe scenarios were not restarted.

## Phase outcomes and feature parity

| Original contribution / requirement | Existing Python authority retained | Integration action | Final status / evidence |
|---|---|---|---|
| Original bilingual product/catalog form, practical SKU/name identity | Canonical products, existing capacity, versioning and discovery | Original form/catalog pages, strict intersecting identifiers, active tenant SKU uniqueness, rename aliases and optimistic edits | VERIFIED: Phase3 native158 and actual browser; catalog/history group142 and actual browser. Counts overlap final suites. |
| Archive/restore, GTIN batch and catalog history | Existing product update and price-history trigger | Original CatalogPage/CatalogProductPage/CatalogTable/GtinImport/RecordSummary and styles; strict CSV/XLSX GTIN validation, atomic apply; `/catalog` and `/catalog/:productId` beside unchanged `/products` | VERIFIED: native, real multipart and English/Arabic Chrome; stock/history preserved across archive/restore. |
| Structured manual invoice/inventory imports | Existing M97 drafts, canonical invoices/items/transactions, manual stock and usage | Original preview/review UI; strict templates; durable staging; explicit confirmation; immutable posting receipt/audit; stale/ambiguous/conflicting rows held | VERIFIED: real parser/API/PG and browser inventory import/reload. Taxes/currencies preserved; historical invoices never decrement current stock. |
| Interrupted file uploads and knowledge documents | Existing extraction/RAG, jobs, object-storage registration and receipt accounting | Stable tenant/actor/file/request identity and deterministic PDF registration; replay and crash recovery; business imports stay separate from knowledge documents | VERIFIED at unit/API/native boundaries; no live AI document extraction/model certification claimed. |
| Shopify/Woo source connections and canonical identity | Existing OAuth/vault, pinned secure provider clients, M94 receipts, M95 identities, M98 staging and connector worker | Reuse existing connection lifecycle; correct actual Shopify scalar prices and cursor handling; retain real Woo product fields; current revision/source fences | VERIFIED controlled adapter/API/PG/worker contracts. Actual merchant OAuth/credential verification and real-store sync UNRUN. |
| Incremental order synchronization | Existing source checkpoint/lease authority | Provider-timestamp order watermarks; inclusive/overlap boundary handling; failed reads do not advance checkpoints; product/inventory full scans retained | VERIFIED native failure/retry, pagination and timestamp contracts. No second worker authority. |
| Source catalog review and canonical posting | Existing product/capacity service and M95/M98 reviews | Strict create/link, source version/hash proof, serialized capacity/revision locks, no overwrite of manually linked price/name/stock | VERIFIED native/concurrency and actual source catalog browser persistence. |
| Provider orders, taxes, shipping, refunds and sales | Existing business invoices/items/transactions, M95 association and audit | Original read-only Node-side Python pure normalizers reused without its HTTP service; SH-/WC-source invoice namespace; exact totals/rounding; stable source-owned line/sale links; cancellation updates only own records | VERIFIED for controlled Shopify/Woo native cases and Shopify browser invoice13 USD, one sale, persisted reload/audit. Distinct manual sales survive. This is business accounting, not Stripe subscription activation. |
| Source stock lineage and selected canonical stock | Existing M96 observations/location/authority decisions and Python single-balance inventory | Completed-scan membership, including duplicate observations; explicit owner source/field/location selection; conflict-safe refresh; existing numeric precision | VERIFIED native for both providers and browser selected Shopify stock8. PARTIAL relative to original multi-warehouse UI: all physical source evidence retained, but only one explicitly selected balance is projected; no automatic roll-up or universal priority. |
| Conditional automatic promotion | Same canonical services and worker; active-principal/capacity/RLS checks | Disabled by default; disposable-only runtime gate; Tenant Owner opt-in per source/category; existing selected stock only; per-record atomic receipts and staged-record retry | VERIFIED native default-off, tenant-admin/direct-SQL denial, concurrency, interrupted-write rollback/retry without new provider read. Browser verified opt-in persistence and restored it off. Automatic execution itself was tested natively, not as a merchant browser run. |
| Automatic invoice posting | Existing manual source accounting remains available | API AND database refuse enabling automatic invoice category | POLICY BLOCKED: separately approve payment, tax, currency, cancellation and deduplication mappings. Original manual reference rules are not treated as automatic financial authorization. |
| Signed Shopify events and privacy | Existing source binding and durable receipt authority | Exact-body HMAC, topic/shop binding, digest-only deduplication/conflict handling, uninstall source fencing, privacy job/hold and reimport prevention | VERIFIED native signed fixtures. Privacy intake never claims completed erasure. Irreversible targeted erasure remains POLICY BLOCKED. |
| Pricing recommendation orchestration/history | Existing pricing algorithm, currency guards, evidence and history | Optional single-product Idempotency-Key with immutable response/evidence link in one transaction; existing pipeline commit default preserved | VERIFIED native retry/concurrency/rollback and affected pricing guards. No automatic price update, model rewrite, new fee or charging unit. PRICE-001 numerical/newest-invalid policy remains pending. |
| Business/product/competitor MPI history | Existing MPI/sentiment scorer and evidence_records | Tenant-scoped read-only paginated history, subject checks, tenant cache keys and bilingual history/UNKNOWN UI | VERIFIED native and existing Phase5 browser. Read/history does not refresh models or charge. No new sample/cap/recency thresholds or fabricated reviews/scores. |
| Existing dashboard, forecast, market inputs, credits, RAG/storage and receipt consumers | Existing Python services/models/workers | Impact regressions and minimal integration wrappers only | VERIFIED affected native group237. No exhaustive unrelated AI/model/live-provider certification performed. |
| Business Recommendations | Existing deterministic Python insights engine | No new customer UI/entitlement/persistence | DEFERRED by owner priority; recorded in FEATURE_INVENTORY.md and prior ledger. |

Phase3 implemented business operations/manual ingestion; Phase4 implemented the supported source reconciliation and guarded conditional automation; Phase5 restored original catalog and feature-history boundaries. Phase6 verified those additions and their affected Python consumers. Gated rows above are not counted as completed operations.

## Verification actually performed

Evidence root: `%TEMP%/KEEL/RemainingIntegrationRuns/20261026-a00669d`. A sanitized selected copy is preserved beside the external report under `evidence/remaining-integration-20261026/`.

| Evidence | Result | Scope |
|---|---|---|
| `phase4-commerce-acceptance.xml` | 129 passed, 0 failed, 0 skipped | Provider adapters, real PostgreSQL APIs, M94/M95/M96/M98, signed webhook fixtures, stock/accounting, default-off owner opt-in, tenant boundaries, concurrency and crash/retry. |
| `phase6-final-affected.xml` | 237 passed, 0 failed, 0 skipped | Products/identity/catalog, structured imports, ordinary company deletion, credits/receipts, RAG upload/storage recovery, dashboard inventory/metrics/forecast, market inputs, pricing and MPI history. |
| `final-evidence-summary.json` | 366 unique native/backend tests | XML testcase identities prove these two groups are disjoint. Earlier overlapping suite counts are not added. |
| `phase6-final-glyph-frontend.log` | 201 passed, 0 failed/skipped | Full existing frontend suite plus real-Arabic/replacement-character and source-display regressions. |
| `phase6-integrated-final-lint.log`, `phase6-final-glyph-build.log` | PASS | Existing dependencies reused. Nonfatal bundle-size warning retained. |
| `phase6-integrated-source.xml` | 42 passed, 0 failed/skipped | Focused verification FROM actual integration worktree after fast-forward. Subset of the above366, not another42 unique cases. |
| `phase6-integrated-final-frontend.log` | 13 passed, 0 failed/skipped | Affected contract/localization checks FROM actual integration frontend. Subset of201. |
| `phase6-final-migrations/migration-results.json` | Fresh137; original123+14 upgrade; repeat0 | Restricted password login, FORCE RLS, no receipt UPDATE/DELETE privilege, legacy product/stock/paid invoice preservation. |
| `phase4-browser/provider-browser-ledger.json` and request/screenshot files | PASS | Actual Chrome/Python/PG manual source catalog -> invoice/stock review -> persistence/reload -> source opt-in/reload/disable -> English/Arabic390px RTL. Upstream explicitly CONTROLLED_PROVIDER_FIXTURE_NOT_REAL_STORE. |
| `phase4-browser/provider-accounting-db-proof.json` | PASS | ceopro_app reads confirm invoice12+1=13 USD; line3 x3.3333 +0.0001=10; one source sale; stock8; unchanged product price12.50; one order/stock receipt; exact audit; opt-ins off. |

The final replay response correction was verified by five affected native tests, then the same five FROM the integrated source (`phase6-replay-flag-final.xml`, `phase6-integrated-replay-final.xml`); these are existing cases within366, not additional unique tests. Reproduction first exposed two incorrect flags; all affected cases now pass. No migration changed after the137 rehearsal. Its ledger records preceding HEAD5960d87 plus pending source files later committed as3dab0d2; it is not a claim that5960d87 alone already contained137 committed migrations.

The earlier Phase3 product/import and Phase5 catalog/GTIN/archive/MPI browser ledgers remain valid for unchanged paths. The current browser uses the previously authorized synthetic Tenant Owner and existing database/services. No account, Checkout, Stripe resource or real merchant operation was created in this continuation. Separate Woo-specific browser and real Shopify/Woo merchant acceptance remain UNRUN; Woo adapter/worker/API/database contracts passed. No skip was converted into a pass.

The browser source is on `/connect-data`; original catalog is `/catalog`. Isolated frontend `http://127.0.0.1:5204`, API `http://127.0.0.1:8024`, database `keel_billing_test_ba624f1dc5ba47`, Redis `/14`. Recorded process ownership/parent/venv and Vite source path matched. API/backend and Vite now serve05874e8, matching integrated application code. The final handoff commit changes documents only. Readiness, new OpenAPI routes and exact CORS were verified. No protected5197/8017 runtime was restarted.

## Demonstrated defects fixed

- Shopify variant prices incorrectly requested object subfields instead of actual scalar fields; authenticated shop currency now supplies the internal money shape.
- Valid next-page cursor was rejected as already seen; valid outer paging works while replay/nonprogress and nested duplicate cursors remain rejected.
- Woo simple products/variation names lost usable typed fields; actual source fields now reach strict review.
- New pricing result FK blocked existing whole-company cleanup; forward migration130 handles whole-company cascade while direct immutable result deletion remains forbidden.
- Existing retained M95/M97 evidence requires review before company erasure. Return explicit409 before writes instead of partial deletion/500; ordinary deletion still passes.
- Localized catalog search matched locale JSON keys; existing text-search helper now searches values.
- JSON-default upload header broke actual multipart GTIN preview; narrow adapter fix and real multipart regression.
- Newly added Arabic source controls became question marks in PowerShell transport. Only those added values were repaired using ASCII-safe Unicode transport; regression asserts real Arabic. Existing translations remain preserved.
- New nested accounting JSON overflowed source tables; detailed accounting stays in the explicit review dialog. Stock fields have meaningful English/Arabic labels.
- Final screenshot review also corrected the encoded multiplication symbol in invoice details; a read-only browser assertion verifies the exact notation.
- An existing source-order replay truthfully created no new data but returned `canonical_write_performed=true`. It now returns false with replay=true; native and actual browser replay verify one unchanged invoice/sale/receipt/audit.
- Browser harness assumed synchronous controlled-checkbox updates; it now waits for authoritative API/state. Failed harness runs were not counted as application passes.

## Preservation and security

Python remains the sole authentication, billing, entitlement, Data/AI Credit and usage authority. Git diff from a00669d shows no changes to `backend/src/ai/billing`, `core`, `forecasting`, `sentiment`, or MPI pipeline. Pricing pipeline changes only add optional `commit=True` to support the atomic existing result transaction; inference/guardrail mathematics remain unchanged. Existing `/products`, ProductHub, forecast, knowledge-document and quick-sale workflows remain available beside original catalog pages. Existing Python forecast inclusion of non-cancelled unpaid invoices is preserved; provider sale mirrors retain original provider-specific eligibility.

Runtime role is ceopro_app, non-superuser/non-BYPASSRLS. New receipt/decision tables FORCE RLS and forbid runtime UPDATE/DELETE. New owner source locks are narrow definer functions with fixed search_path; broad source metadata UPDATE was not granted. Source opt-in requires actual Tenant Owner membership in API AND SQL; Tenant Admin cannot enable it. Review services revalidate source/revision/actor and existing capacity; manual or stale conflicts never silently overwrite canonical data. Canonical retries use the same existing services and receipts, not a second posting engine.

Original Node/React repositories under D: were read only; no write command targeted them. No push, protected-main merge, deployment, live Stripe operation, system permission weakening, new venv or new container. Existing test cluster/dependencies/services were reused. Fresh/upgrade databases were uniquely ledgered within that already-owned disposable cluster.

Protected integration `backend/.env.example` remains the sole unrelated source modification, SHA256 `6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28`. No conflicts were force-resolved; integration was a fast-forward. No implementation is stranded on a new permanent branch; the existing development branch was reused.

## Exact remaining boundaries

- **Critical integration-caused defects:** none known in exercised scope.
- **Policy blocked:** automatic invoice mappings; universal source priority/shared external-key collision policy; irreversible Shopify erasure fields, jurisdictions, legal exceptions and retention; deletion of retained import/provider audit lineage; PRICE-001 age/FX/newest-invalid specifics; MPI-001 count/cap/recency/source specifics; unapproved commercial values/meters remain gated.
- **Intentional noncritical differences:** one explicitly selected source field/location projects into existing Python single-balance inventory; no automatic multi-warehouse aggregation, source switching or unknown-to-zero inference. Source-owned history remains intact. Manual edits produce review holds. Catalog is additive beside existing Python product pages.
- **Unrun prerequisites:** actual Shopify development-store OAuth/scopes/webhooks/sync and Woo sandbox credentials/paging/rate-limit behavior; separate Woo-specific browser; live AI model/provider/store certification. Controlled fixtures are not merchant proof.
- **Production work:** owner/legal policy sign-offs, separately approved rollout beyond disposable-only automation, real merchant acceptance, environment/secrets/monitoring/migration rollout and unrelated deployment requirements. Unchanged historic Stripe/onboarding acceptance is inherited evidence, not rerun or promoted into production certification here.

## Git milestones

| Milestone | Local commit |
|---|---|
| Completed onboarding/billing baseline | `a00669dd8500dcce7dba9d94e2fbfac5a22d8808` |
| Phase3 business imports/identity | `2c56b18517a7ac10c03f5ebf758d22da24ab6bb8` |
| Initial commerce | `2143756d5252a5da5d2931758b97243f18adcb1a` |
| Catalog and feature history | `9a1b0790aeccc6c719175cd48c87d6e0c5b3053b` |
| Cleanup/retention compatibility | `4b0e6091855d596166f73ca16f71385d9c80ac79` |
| Source catalog | `5960d87121f97dbc8ba52a9d3d4ddb3e37e69f2a` |
| Source accounting/stock and conditional automation | `3dab0d2996057362403f08bd8c1e14068b815f7b` |
| Final browser/Arabic fixes | `980f8ec0f426626d340dcbbc62317f4ab37ca963` |
| Final replay response and invoice notation | `05874e8df27ff71a0b984a88e7e437199cc72de1` |

Forward migrations124-137 are new files only; original123 bytes were compared with a00669d during rehearsal. Full names are in the Git diff and `REMAINING_INTEGRATION_CHECKPOINT.md`. No applied target migration was replaced and no migration history was disguised.

## Review and resume instructions

Review application diff `a00669d..05874e8`; use this current acceptance section plus `REMAINING_INTEGRATION_CHECKPOINT.md`, `UNIFIED_FILE_CHANGE_LEDGER.md` and the existing external master handoff. New unit/native/browser tests are committed; secrets and raw runtime state remain outside Git. Rerun only affected tests after future code changes. Reconcile recorded ledgers before any new fixture/provider mutation. The completed app scope is ready for review; gated functionality must remain gated.

---

## Historical 2026-10-23 acceptance (preserved; superseded above only for the current scope)

# KEEL Phase 6 — Unified Integration Acceptance

**Run date:** 2026-10-23
**Source:** `integration/keel-full-migration` at `21472b4e3e14f4b7a9b222948150b694ace17801`; the final evidence and verification harness are recorded in local commit `2b7f858acdee0e84a1544f6882ab341bf98bd347`.
**Database:** reusable disposable PostgreSQL 17 / pgvector, migrations 1–103; restricted `ceopro_app`; Redis 7.4.11; MinIO; current-source FastAPI/Vite; installed Chromium. No development or production database was used.

## Acceptance matrix

PASS means the named local scenarios ran successfully. Fixture or inherited evidence is identified explicitly. BLOCKED identifies an external/policy gate; NOT RUN means this Phase 6 pass did not exercise that path; DEFERRED is outside the approved scope.

| Feature / original acceptance IDs | Backend and PostgreSQL | Worker | Current-source browser | External / policy status | Phase 6 result |
|---|---|---|---|---|---|
| Authentication, tenant/session/RLS — `AUTH-001..013` | **PASS**: current native auth/platform/RLS group, included in 90 passing tests; direct API role and cross-tenant product checks. | **PASS** for tested worker identities in the worker suites. | Login and tenant sessions were exercised in the current product, pricing, forecast, MPI, RAG, import, billing, notification and competitor journeys. Signup/invitation journeys are inherited from earlier acceptance evidence, not rerun here. | `AUTH-004` issuer/audience rollout and `AUTH-013` Node-account cutover remain owner-controlled. | **PASS** for Python local scope; release **BLOCKED** on the two decisions. |
| Platform authority/search — `PLATFORM-001..005` | **PASS** for platform permission/RLS regressions in the 90-test security group; platform directory/search acceptance has earlier native evidence. | Worker/platform separation covered natively. | Full operator dashboard/invitation workflow was **NOT RUN** in this pass; prior platform browser evidence is inherited only. Tenant Owner was denied platform `/platform/me` during current authenticated journeys. | Platform financial/catalog actions and platform notification delivery remain gated; `PLATFORM-003/004` are not activated. | **PARTIAL**; owner/admin customer separation tested, complete platform operator browser journey not newly verified. |
| Stripe subscriptions — `SUB-001..014` | **PASS**: 107 native tests. | Event receipt/order/reconciliation behavior covered by the native billing suite. | **PASS**: 9 assertions in authenticated Chromium: plan selection, local hosted checkout, signed checkout/invoice events, confirmed paid state, invoice history, portal, cancellation, reactivation, Arabic RTL, and cancelled-checkout honesty. | The browser used a local contract fixture and synthetic `sk_test` sentinel with no network Stripe calls. Live Stripe test-account/SCA/webhook certification is **BLOCKED**; one live-only pytest skipped for absent `STRIPE_E2E_SECRET_KEY` / `STRIPE_E2E_WEBHOOK_SECRET`. | **PASS** for local fixture contract; live certification **BLOCKED**. |
| Entitlements, usage, Data/AI Credits — `ENT-001..011`, `CREDIT-001..006` | **PASS** for exercised current grants, limits, tenant isolation, reservations, settlement/idempotency and credit paths in the billing, RLS, forecast/RAG/MPI and product groups. | Execution-time/fencing paths exercised by current forecast, connector and image-job worker tests. | Billing/usage and feature states were exercised through relevant journeys; not every U1–U5 operation has a browser case. | No unmapped feature was granted. U1–U5/U7 commercial choices remain release gates; no new charges, mappings or historical grants were inferred. | **PASS** for approved local behavior; policy-dependent activation **BLOCKED**. |
| Products and inventory — `IMPORT-003`, `IMPORT-006`, `ENT-005/006` (no standalone product CRUD ID in the matrix) | **PASS** in product/inventory/RLS tests; tenant SKU/identity and source-observation boundaries remain under existing contracts. | — | **PASS**: Owner create/edit/soft-delete and 4-decimal manual stock persisted; staff UI restriction plus direct create/edit/delete/stock API requests denied; guessed cross-tenant read/write hidden. English desktop and Arabic mobile RTL. | Provider observations remain separate from canonical stock. SKU policy, inventory history, provider stock reconciliation and unmapped U5 features remain gated. | **PASS** for existing CRUD/manual-stock scope; remaining inventory policy **BLOCKED**. |
| File imports and canonical sales — `IMPORT-001..012` | **PASS**: 98 import/dashboard/notification tests, including restricted-role promotion, replay, provenance and import review. | Retry and promotion paths covered in native tests. | **PASS 2/2 locales**: authenticated CSV upload → review → canonical post → dashboard, replay, tenant isolation, actual persisted figures. The synthetic fixture produced 4 paid sales, 8 units, 50 JOD, with invoice mirrors not double-counted. | XLSX/PDF parsers exercised with declared dependencies. Mixed-currency grouping, unsupported invoice/refund semantics and interrupted synchronous upload recovery remain policy/implementation boundaries already recorded in the ledger. | **PASS** for the supported CSV path and exercised promotion contract. |
| Dashboard Analytics — `SUB-011`, `IMPORT-012` and associated existing dashboard cases | **PASS** in dashboard metrics, totals, reports, search and canonical import groups. Revenue uses paid canonical invoices; units use invoice items; transaction mirrors are not counted as separate sales. | — | **PASS 2/2 locales** through import-to-dashboard; actual period figures and charts rendered. | Mixed-currency FX and `dashboard_analytics` U5 mapping remain unresolved; existing Python access was preserved. | **PASS** for verified canonical sales/period scope; U5/FX release limits remain. |
| Generic/provider staging and Shopify/WooCommerce — `CONNECT-001..006`, `STORE-001..008`, `SHOP-001..008`, `WOO-001..006` | **PASS**: 259 tests across provider API contracts, source identity, staging/review, worker sync, retries, discovery and provenance. | **PASS**: connector worker identity, lease/retry and staging paths ran against restricted `ceopro_app`. | Customer-facing Shopify/Woo connection/sync browser workflow was **NOT RUN** in this pass. | Controlled fixtures only; no Shopify app/store or Woo merchant credentials. Live provider certification is **BLOCKED**. Incremental cursor resume, order/refund reconciliation and stock posting remain gated as specified. | **PASS** for tested local staging contracts; live/provider UI certification **BLOCKED / NOT RUN**. |
| Competitor Intelligence and Market Intelligence — `MPI-001..010` plus related `STORE-*` cases | **PASS**: competitor/provider native group (259) and MPI/focused AI group (226), including tenant ownership, price history, source review, provenance and worker behavior. | **PASS** for controlled discovery/analysis/monitoring contracts; no arbitrary live crawling. | Competitor/Market Intelligence **PASS 2/2** locale journeys; MPI **PASS 2/2** (English desktop and Arabic 390px RTL): business/product/tracked competitor, search, actual review counts, low-sample suppression, empty/error and cross-tenant denial. | Search/scraping providers used controlled fixtures; live discovery/scraping is **BLOCKED** pending provider credentials. No dedicated competitor image gallery exists; teammate image URL association is preserved. | **PASS** for local fixture flows; live source certification **BLOCKED**. |
| Demand Prediction — `ENT-008`, `ENT-010` execution boundaries and forecast acceptance evidence | **PASS**: native generation, history, data sufficiency and entitlement tests. | **PASS** for execution-time authorization and durable forecast write. | **PASS 2/2 locales**: real synthetic canonical invoice history, current baseline forecaster, saved forecast row and UI result. | Existing baseline inference ran locally; no accuracy certification or optional large model download. | **PASS** for local baseline workflow. |
| RAG / Knowledge Base — `IMPORT-002`, `ENT-007/008/010` | **PASS**: 226 focused AI/RAG/storage cases plus upload, indexing, citations/access and recovery checks. | Index/storage recovery paths covered natively. | **PASS 2/2 locales**: supported synthetic file upload, indexing/search-ready state, conversation history, tenant checks and truthful unavailable-model result. | MinIO was local. No live LLM/embedding credentials or model weights; real provider answer certification is **BLOCKED**. | **PASS** for upload/index/retrieval/error contracts; live answer provider **BLOCKED**. |
| Pricing Recommendations — `PRICE-001..008` | **PASS**: pricing pipeline/history/guardrail tests in the 226-test AI group; actual evidence result generated. | — | **PASS 2/2 locales**: authenticated product selection, actual recommendation endpoint and one matched price observation; displayed `lower` recommendation, stored evidence, unchanged product selling price, RTL/no overflow. | Controlled local competitor observation only. `ai_pricing` U5 mapping and outstanding O-PRICE currency/freshness/guardrail decisions remain. | **PASS** for currently authorized local recommendation behavior; activation policy **BLOCKED**. |
| Durable Notifications / Smart Alerts — `PLATFORM-005` and Migration 103 acceptance evidence | **PASS**: inbox/digest/RLS/idempotency included in 98-test group and earlier dedicated 14-test native Migration 103 suite. | Failed-import producer is transactional; no redundant visibility-delay worker. | **PASS 2/2 locales**: persisted tenant notification, read/dismiss/history, refresh persistence, Smart Alerts dedup and cross-tenant denial. | `system_alerts` remains unmapped; platform/operator delivery is separate and incomplete. | Tenant inbox **PASS**; full `PLATFORM-005` remains **PARTIAL**. |
| Marketing Image Generation / gallery — Python-only teammate feature | **PASS** for job/gallery generation contracts, persistence, storage and worker authorization inside the 226-test AI group. | Controlled provider job/retry path passed natively. | Full campaign/image gallery Chromium journey was **NOT RUN**; its browser harness requires model/image-provider configuration not present in this environment. | Startup had no `GROQ_API_KEY`; live model/image-provider execution is **BLOCKED**. No image algorithm was changed and no fabricated success was shown. | Backend fixture contracts **PASS**; UI/provider **BLOCKED / NOT RUN**. |
| Promotions, custom offers, exceptional catalog/financial actions — `PROMO-001..005`, `CUSTOM-001..013`, `PLATFORM-003/004` | **NOT RUN** in this focused Phase 6 acceptance pass. Existing controls remain governed by prior evidence and default-off approvals. | **NOT RUN**. | **NOT RUN**. | O-PROMO/O-ECON/O-CATALOG/U5/U7 boundaries remain; no activation or economic rule was introduced. Business Recommendations remains **DEFERRED** by owner priority. | **DEFERRED / NOT RUN**; not a Phase 6 pass claim. |

## Test evidence

Final current-source focused backend reruns, executed sequentially against the documented persistent disposable environment:

| Group | Result |
|---|---:|
| Auth, platform permissions, product mutations, inventory provenance, PostgreSQL RLS | **90 passed** |
| Plan catalog/limits, subscription lifecycle, Credits/usage, Stripe SDK and test-mode contract | **107 passed, 1 skipped** |
| Typed imports, extraction/review/promotion, dashboard, notification inbox | **98 passed** |
| Forecast, pricing, MPI, RAG/storage, marketing image generation/jobs/gallery | **226 passed** |
| Connectors, competitor discovery/enrichment, source review, prices/history, workers | **259 passed** |
| **Total final focused backend reruns** | **780 passed, 1 skipped, 0 failed** |

The single skip is the real Stripe sandbox end-to-end case: no test account keypair was configured. The browser's Stripe path is contract-fixture evidence only. Earlier attempts exposed test-harness issues (missing service actor variables, signup fixtures assuming the old direct-creation contract, Migration 103 test cleanup dependencies, and an MPI readiness wait); those fixtures were corrected and affected groups reran successfully. No production application behavior was changed by those corrections.

Other verification:

- Fresh schema: dedicated `keel_verification` recreated and all **103** migrations applied.
- Populated upgrade: disposable post-102 company/owner/plan/product state survived migration 103; rerun applied **0** migrations; `ceopro_app` remained non-superuser and `NOBYPASSRLS`.
- Frontend: **137 passed, 0 failed, 0 skipped**; ESLint passed; Vite production build passed with **2,977 modules**.
- Full current-source FastAPI started; `/health/ready` returned HTTP **200**, PostgreSQL and Redis checks true. Startup warned that Groq and Tavily were unconfigured.
- Current-source Vite and FastAPI served the browser acceptance; no stale port 15173 process was used for subscription acceptance. The subscription harness starts its own Vite and intercepts only Stripe HTTPS hostnames locally.
- C: free space checked at **28.7 GB** before final suites/builds. Persistent containers and volumes were retained; task servers were stopped.

## Verified production corrections

No application production defect was demonstrated in the Phase 6 regressions, so no business logic was changed. Verified local corrections were limited to test reproducibility and acceptance coverage:

- Mounted the real onboarding router in the integration-test app; isolated the legacy-token fixture from Redis invalidation state.
- Updated signup fixtures to perform pending-registration email verification before login.
- Corrected worker test service identities and scraper restricted-role configuration for current M98/M103 contracts.
- Fixed synthetic test teardown to respect Migration 103 outbox FKs; reset only the designated synthetic notification inbox before seeding.
- Reused the configured Chromium executable in forecast verification; corrected subscription browser origin/HTTPS fixture behavior; waited for the real MPI enabled state; added authenticated product/inventory and pricing browser workflows.

## Remaining release gates and fresh-clone findings

- Live Stripe, Shopify, WooCommerce, live competitor/search/scrape, live LLM/embedding, and image-generation-provider certification need approved credentials and controlled provider environments. Do not infer these from fixtures.
- `AUTH-004`, `AUTH-013`, U1–U5/U7, O-PRICE, O-MPI and the recorded provider/canonical import decisions remain unchanged. No unmapped right was activated.
- Platform operator browser invitation/management, full connector browser UI, marketing image gallery browser workflow, promotions/custom offers and exceptional platform financial operations were not run in this pass.
- Dedicated competitor image gallery, MPI persisted history, account-erasure policy for notification history, and platform/operator notification delivery remain known gaps as already recorded in the ledger.
- Fresh-environment prep found `reportlab` and `arabic_reshaper` declared by the repository but absent from the reusable venv; both were installed into that existing venv (no repository manifest change). `Initialize.ps1` sets process-scoped synthetic PostgreSQL/Redis/MinIO credentials. `Test-Backend.ps1` now supplies the restricted scraper URL and service actor IDs required by worker tests. No model weights were installed.

## Git and verdict

- Starting commit: `21472b4e3e14f4b7a9b222948150b694ace17801`.
- Local Phase 6 verification commit: `2b7f858acdee0e84a1544f6882ab341bf98bd347`; no application migration or production code change.
- Migrations remain exactly **103**; no migration file changed.
- Node reference, teammate `main`, and the Phase 1A worktree were not modified.

**Unified local integration acceptance: PASS for the exercised supported workflows and documented local environment, with the exact NOT RUN/BLOCKED items above.**

**Production release readiness: BLOCKED / CONDITIONAL** on owner policy decisions and live provider certification, plus the explicitly unverified UI/operator workflows. This is not production certification or deployment approval.
