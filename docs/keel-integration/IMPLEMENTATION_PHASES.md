> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

# Executable dependency-ordered implementation phases

Status: all implementation phases NOT STARTED. Phase 0 adds documentation only; 0V is a required verification task, not permission to apply new production fixes. Every slice below is independently reviewable. Exact proposed new paths are scopes, **not files already created**. When existing path assumptions fail, revise scope/ADR before editing rather than silently adding a new subsystem. All future added/modified/renamed/deleted files, including dependencies/tests/config/docs, require ledger rows.

Execution order: `0V → 1A → 1B → 2A → 2B → 2C → 2D → 3A → 3B → 4A → 4B → 4C → 5A → 5B → 6`. 3A does not depend on promo economics; sequential ordering keeps each run bounded and avoids overlapping shared-file edits. 5A/5B can be designed before provider certification, but release depends on real eligible market/review inputs. No parallel source work is authorized.

## Phase 0V — Verify frozen post-Task-6 base

Capability scope: SOURCE-001; all Task 6 repairs. **Prerequisites:** No production edits; requires clean post-Task-6 commit/full diff and independent verification.

**Modify only, where needed:**

- `None`

**Proposed additions:**

- `None`

**Migration:** None. See proposed schema details below; no SQL has been applied.

**Acceptance:** Run guarded native combined suite, runtime-role password login, exact report/assignment/invoice races; populated migration up/repeat and rollback/disable review; preserve 56 non-DB baseline and 90 frontend tests. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Do not start overlapping implementation until post-Task-6 clean commit/source delta and database baseline are recorded.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 1A — Shared active principal and platform boundary

Capability scope: AUTH-001..013; PLATFORM-001. **Prerequisites:** 0V; AUTH-001 and AUTH-002 approved.

**Modify only, where needed:**

- `backend/src/ai/core/security.py`
- `backend/src/ai/routers/auth.py`
- `backend/src/ai/routers/settings.py`
- `backend/src/ai/db.py`
- `frontend/src/features/auth/api/authContracts.js`
- `frontend/src/features/auth/permissions/rolePermissions.js`

**Proposed additions:**

- `backend/src/ai/core/authorization.py`
- `backend/tests/keel_integration/test_authorization.py`
- `backend/tests/keel_integration/test_auth_rls.py`

**Migration:** 20261025000100_integration_principal_permissions.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** 401/403/tenant-hidden 404; revoked/suspended membership old JWT; owner concurrency; invitation/reset/verification one-use/expiry; bootstrap no recursion; preserve login/workspace/session contract. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable new operator routes; keep compatible Python token path; do not revoke/migrate all existing identities without approved cutover.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 1B — Explicit feature crosswalk and atomic usage

Capability scope: ENT-001..011; CREDIT-001..006. **Prerequisites:** 1A; ENT-001 and ACCOUNTING-001 approved.

**Modify only, where needed:**

- `backend/src/ai/core/usage.py`
- `backend/src/ai/core/entitlements.py`
- `backend/src/ai/billing/credits.py`
- `backend/src/ai/core/storage_ledger.py`
- `backend/src/ai/billing/maintenance.py`
- `frontend/src/features/billing/api/billingApi.js`
- `backend/src/market_scraper/enqueue.py`

**Proposed additions:**

- `backend/src/ai/core/operation_receipts.py`
- `backend/tests/keel_integration/test_usage_receipts.py`
- `backend/tests/keel_integration/test_capacity_concurrency.py`
- `backend/tests/keel_integration/test_execution_authorization.py`

**Migration:** 20261025000200_explicit_grants_and_operation_receipts.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** Every code absence/zero/NULL/disabled/status tested; 12 native HTTP clients compete for last product/source/seat/count; same-key actor/params/period binding; cancel while queued; once-only releases; provider cap/unknown price and ledger invariants unchanged. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable newly introduced actions; preserve historical counter/credit receipts; no reverting Task 6 key format or deleting ledger entries.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 2A — Catalog and effective transition semantics

Capability scope: SUB-001..014; PLATFORM-003. **Prerequisites:** 1B; CATALOG-001 and TRANSITION-001 approved.

**Modify only, where needed:**

- `backend/src/ai/billing/service.py`
- `backend/src/ai/billing/store.py`
- `backend/src/ai/billing/webhooks.py`
- `backend/src/ai/billing/catalog_sync.py`
- `backend/src/ai/routers/billing.py`
- `frontend/src/features/billing/api/billingApi.js`
- `frontend/src/features/billing/pages/PlansSubscriptionPage.jsx`

**Proposed additions:**

- `backend/src/ai/billing/transitions.py`
- `backend/tests/keel_integration/test_transitions.py`
- `frontend/tests/billingTransitions.test.mjs`

**Migration:** 20261025000300_catalog_versions_and_transition_intents.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** Effective-grant vector numeric/Boolean/custom/cadence mixed; lower price more rights; period change; proration/SCA; signed duplicate/reordered events; preserve historic private/current price mapping. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable new change-plan variants; retain current provider subscription/assignment; reconcile incomplete schedule intents instead of deleting them.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 2B — Managed promotions

Capability scope: PROMO-001..005. **Prerequisites:** 2A; PROMO-001 approved.

**Modify only, where needed:**

- `backend/src/ai/billing/stripe_api.py`
- `backend/src/ai/billing/service.py`
- `backend/src/ai/billing/webhooks.py`
- `backend/src/ai/routers/billing.py`
- `frontend/src/features/billing/api/billingApi.js`
- `frontend/src/features/billing/pages/PlansSubscriptionPage.jsx`

**Proposed additions:**

- `backend/src/ai/billing/promotions.py`
- `backend/src/ai/billing/promotion_store.py`
- `frontend/src/features/billing/components/PromoCodeField.jsx`
- `backend/tests/keel_integration/test_promotions.py`
- `frontend/tests/promoCodes.test.mjs`

**Migration:** 20261025000400_managed_promotions.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** Code create/update/disable, plan/date/currency/term restriction, tenant/person reuse choice, max last-redemption race, expired/abandoned session, duplicate paid webhook, custom discount stacking, sanitized error feedback. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable managed promo entry/create; preserve existing Stripe coupon/discount history and reserved/confirmed redemption rows; reconciliation frees only approved abandoned reservations.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 2C — Quote economics and immutable offer lifecycle

Capability scope: CUSTOM-001..013. **Prerequisites:** 2A/2B; CUSTOM-001/CUSTOM-002/AUTH-002 approved.

**Modify only, where needed:**

- `backend/src/ai/billing/admin.py`
- `backend/src/ai/billing/store.py`
- `backend/src/ai/billing/stripe_api.py`
- `backend/src/ai/billing/webhooks.py`
- `backend/src/ai/routers/billing.py`
- `frontend/src/features/billing/api/billingApi.js`

**Proposed additions:**

- `backend/src/ai/billing/quotes.py`
- `backend/src/ai/billing/quote_store.py`
- `backend/src/ai/billing/quote_pricing.py`
- `backend/src/ai/billing/quote_schemas.py`
- `backend/tests/keel_integration/test_quote_pricing.py`
- `backend/tests/keel_integration/test_quote_lifecycle.py`
- `frontend/src/features/billing/components/CustomPlanBuilder.jsx`
- `frontend/src/features/billing/pages/CustomPlanOfferPage.jsx`
- `frontend/tests/customPlanFlow.test.mjs`

**Migration:** 20261025000500_quote_revisions_and_provider_intents.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** Decimal golden vectors vendor/usage/infrastructure/margins/ratio/fee/up-rounding; frozen FX; missing rates fail; stale approve/accept; privileged below-floor reason; quote acceptance grants no entitlement; provider success/DB fail recovers once. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Hide new quotes/checkout; preserve accepted quote terms/provider price mappings and existing manual contracts; disable intake, do not erase audit/history.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 2D — Platform dashboards and offer notification delivery

Capability scope: PLATFORM-002..005; CUSTOM-009/CUSTOM-012; PROMO-005. **Prerequisites:** 1A/2B/2C; AUTH-002 and catalog/private visibility approved.

**Modify only, where needed:**

- `backend/src/ai/main.py`
- `backend/src/ai/core/notifications.py`
- `frontend/src/app/router/index.jsx`
- `frontend/src/shared/config/businessNavigation.js`
- `frontend/src/assets/locales/en.json`
- `frontend/src/assets/locales/ar.json`

**Proposed additions:**

- `backend/src/ai/routers/platform_admin.py`
- `backend/src/ai/billing/platform_service.py`
- `backend/src/ai/billing/notification_outbox.py`
- `backend/src/market_scraper/integration_notification_worker.py`
- `frontend/src/features/platform-admin/api/platformApi.js`
- `frontend/src/features/platform-admin/pages/PlatformBillingPage.jsx`
- `frontend/src/features/platform-admin/pages/PlatformCompaniesPage.jsx`
- `frontend/src/features/platform-admin/pages/PlatformUsersPage.jsx`
- `frontend/src/features/platform-admin/pages/PlatformQuotesPage.jsx`
- `backend/tests/keel_integration/test_platform_permissions.py`
- `frontend/tests/platformBilling.test.mjs`

**Migration:** 20261025000600_operator_notification_outbox.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** API/UI permissions across customer/admin/accountant/operator; immutable audit; counts/detail tenant scope; no cost exposure; quote ready notification transaction/retry/idempotency; browser loading/empty/error/conflict states. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable new platform routes/outbox intake; safely drain/retry authorized notification rows; no privilege changes from frontend-only flags.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 3A — Canonical product identity and typed import review

Capability scope: IMPORT-001..012. **Prerequisites:** 1B; IMPORT-001/ACCOUNTING-001 approved.

**Modify only, where needed:**

- `backend/src/ai/routers/extraction.py`
- `backend/src/ai/extraction/template_contract.py`
- `backend/src/ai/extraction/ingestion_pipeline.py`
- `backend/src/ai/extraction/promotion.py`
- `backend/src/ai/routers/products.py`
- `backend/src/ai/sales/quick_sale.py`
- `frontend/src/features/data-ingestion/api/ingestionApi.js`
- `frontend/src/features/data-connections/api/dataConnectionsApi.js`

**Proposed additions:**

- `backend/src/ai/extraction/product_identity.py`
- `backend/src/ai/extraction/structured_imports.py`
- `backend/src/ai/extraction/import_review.py`
- `backend/src/ai/extraction/import_jobs.py`
- `backend/tests/keel_integration/test_import_identity.py`
- `backend/tests/keel_integration/test_structured_imports.py`
- `backend/tests/keel_integration/test_import_restart.py`
- `frontend/src/features/data-connections/components/ImportReview.jsx`
- `frontend/tests/importReview.test.mjs`

**Migration:** 20261025000700_product_identity_import_drafts_lineage.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** ID vs SKU/name/barcode disagreements and cross tenant; strict templates/MIME/size; invoice/inventory preview review immutable revision confirm; duplicate occurrence identity; preserved sales+invoice mirror; partial/quarantined/resumed 1000/50000-row import and quota/storage effects. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable new import kinds and async intake; retain old compatible sales path; fence/resume durable jobs, preserve canonical writes and lineage; no automatic deletion of imported history.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 3B — Generic connector durability and promotion

Capability scope: CONNECT-001..006. **Prerequisites:** 3A; IMPORT-001 auto-vs-review rule approved.

**Modify only, where needed:**

- `backend/src/ai/routers/onboarding.py`
- `backend/src/market_scraper/connector_worker.py`
- `backend/src/market_scraper/connector_sync.py`
- `backend/src/market_scraper/api_connector_sync.py`
- `backend/src/market_scraper/data_access.py`
- `frontend/src/features/data-connections/components/ConnectSystemForm.jsx`
- `frontend/src/features/data-connections/pages/ConnectDataPage.jsx`

**Proposed additions:**

- `backend/tests/keel_integration/test_connector_promotion.py`
- `backend/tests/keel_integration/test_connector_fencing.py`

**Migration:** 20261025000800_connector_claims_and_canonical_state.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** DB/API verify+vault+field map preserved; staged vs committed explicit; two pollers/lease; member revoked and subscription cancelled between enqueue/run; disconnect/reconnect mid-fetch; failure isolates other source type. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable new auto-promotion/claims and return to approved staging-only mode; retain pending row review and checkpoint evidence; do not claim existing staged rows canonical.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 4A — Shared persistent store lifecycle and canonical adapter

Capability scope: STORE-001..008. **Prerequisites:** 3B; ENT-001 and IMPORT-001 approved.

**Modify only, where needed:**

- `backend/src/ai/main.py`
- `backend/src/market_scraper/connector_worker.py`
- `frontend/src/features/data-connections/api/dataConnectionsApi.js`
- `frontend/src/features/data-connections/pages/ConnectDataPage.jsx`
- `frontend/src/features/data-connections/components/ConnectionStatusBadge.jsx`

**Proposed additions:**

- `backend/src/ai/routers/store_connections.py`
- `backend/src/ai/stores/service.py`
- `backend/src/ai/stores/repository.py`
- `backend/src/ai/stores/schemas.py`
- `backend/src/market_scraper/store_sync.py`
- `backend/src/market_scraper/connectors/transport.py`
- `backend/src/market_scraper/connectors/contracts.py`
- `backend/tests/keel_integration/test_store_lifecycle.py`
- `backend/tests/keel_integration/test_store_accounting.py`
- `frontend/tests/storeConnections.test.mjs`

**Migration:** 20261025000900_store_connections_external_links.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** Claim/fetch/reauthorize/fenced commit; token encryption; active owner/admin/capacity; once-only product/inventory/sale/invoice mirrors; stale lease/reconnect/version race; bounded retries/progress. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable store collector keys and intake; fence leases, preserve link/history and vault keys; safe disconnect revokes secrets and leaves approved business history.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 4B — WooCommerce dedicated adapter

Capability scope: WOO-001..006. **Prerequisites:** 4A; IMPORT-001 approved.

**Modify only, where needed:**

- `backend/src/ai/stores/service.py`
- `backend/src/market_scraper/store_sync.py`
- `frontend/src/features/data-connections/pages/ConnectDataPage.jsx`

**Proposed additions:**

- `backend/src/market_scraper/connectors/woocommerce.py`
- `backend/src/market_scraper/connectors/orders.py`
- `backend/src/market_scraper/connectors/inventory.py`
- `frontend/src/features/data-connections/components/WooCommerceConnectionForm.jsx`
- `backend/tests/keel_integration/test_woocommerce_contract.py`
- `backend/tests/keel_integration/test_woocommerce_cross_layer.py`

**Migration:** No separate schema beyond 4A unless approved schema delta is documented before edit. See proposed schema details below; no SQL has been applied.

**Acceptance:** Public HTTPS/DNS pinning/redirect guard; bad key/scope; products/variations/stock; equal timestamps/page repetition/rate limits; refunds and tax/shipping reconciliation; fixture/native tests then authorized Woo sandbox E2E. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Keep provider disabled until live certification; fence jobs, retain cursor/lineage; unsupported amount-only refunds require operator review.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 4C — Shopify OAuth GraphQL webhook privacy

Capability scope: SHOP-001..008. **Prerequisites:** 4A; PRIVACY-001 and test-order/history scope rules approved.

**Modify only, where needed:**

- `backend/src/ai/main.py`
- `backend/src/ai/stores/service.py`
- `backend/src/market_scraper/store_sync.py`
- `frontend/src/features/data-connections/pages/ConnectDataPage.jsx`

**Proposed additions:**

- `backend/src/ai/routers/shopify_public.py`
- `backend/src/ai/stores/shopify_oauth.py`
- `backend/src/ai/stores/shopify_events.py`
- `backend/src/market_scraper/connectors/shopify.py`
- `frontend/src/features/data-connections/components/ShopifyConnectionForm.jsx`
- `backend/tests/keel_integration/test_shopify_security.py`
- `backend/tests/keel_integration/test_shopify_privacy.py`
- `backend/tests/keel_integration/test_shopify_cross_layer.py`

**Migration:** 20261025001000_shopify_oauth_events_privacy.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** Invalid HMAC/state/duplicate keys/time; one-use ticket; scopes/shop binding; refresh races; nested GraphQL pagination/429; order edits/test/refunds; replay/uninstall/delete; privacy report/redact/exclusion; authorized development-store E2E. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable installs/collector intake; keep signed uninstall/privacy processing available as required; fence jobs and protect privacy exclusions, no retroactive deletion outside approved scope.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 5A — Pricing orchestration with retained algorithm

Capability scope: PRICE-001..008. **Prerequisites:** 1B/3A; PRICE-001/ACCOUNTING-001 approved; approved market inputs available.

**Modify only, where needed:**

- `backend/src/ai/routers/pricing.py`
- `backend/src/ai/pricing/pipeline.py`
- `backend/src/ai/pricing/data_access.py`
- `backend/src/ai/pricing/evidence.py`
- `frontend/src/features/pricing/api/pricingApi.js`
- `frontend/src/features/pricing/components/PriceRecommendationModal.jsx`
- `frontend/src/features/pricing/hooks/usePriceRecommendation.js`

**Proposed additions:**

- `backend/src/ai/pricing/requests.py`
- `backend/tests/keel_integration/test_pricing_access_replay.py`
- `backend/tests/keel_integration/test_pricing_evidence.py`
- `frontend/tests/pricingEvidence.test.mjs`

**Migration:** 20261025001100_pricing_operation_result_links.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** Single/bulk/alias gate; missing product/data/cost/FX; approved freshness and latest-invalid case; numeric and guardrail edges; UNKNOWN/FACT native constraint; request replay changed params; failure quota/credit settlement; unchanged inference goldens and modal contracts. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable new generation if safety test fails, retain persisted history/read UI; preserve algorithm; no automatic product price update.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 5B — MPI three-scope reliable lifecycle and dashboard

Capability scope: MPI-001..010. **Prerequisites:** 1B/3A; MPI-001 and ENT-001 approved; scored eligible reviews available.

**Modify only, where needed:**

- `backend/src/ai/routers/mpi.py`
- `backend/src/ai/mpi/data_access.py`
- `backend/src/ai/mpi/pipeline.py`
- `backend/src/ai/mpi/evidence.py`
- `backend/src/ai/routers/reviews.py`
- `backend/src/ai/sentiment/pipeline.py`
- `frontend/src/features/market-intelligence/pages/IndustryMarketTrendsPage.jsx`

**Proposed additions:**

- `backend/src/ai/mpi/service.py`
- `backend/src/ai/mpi/schemas.py`
- `frontend/src/features/market-intelligence/api/mpiApi.js`
- `frontend/src/features/market-intelligence/components/MarketPerceptionPanel.jsx`
- `backend/tests/keel_integration/test_mpi_scope_access.py`
- `backend/tests/keel_integration/test_mpi_lifecycle.py`
- `frontend/tests/mpiScopes.test.mjs`

**Migration:** 20261025001200_mpi_evidence_read_state.sql. See proposed schema details below; no SQL has been applied.

**Acceptance:** All three subject IDs/ownership; global competitor mapping; 0/1/4/5 reviews plus configurable min; future/duplicate/unsafe eligible count; classifier failure; evidence shape; read vs refresh no double charge; unchanged weighted scorer; three-scope UI states. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** Disable refresh if needed while preserving evidence reads and existing market sentiment views; never synthesize zero for missing MPI.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Phase 6 — Integrated regression and deployment rehearsal

Capability scope: ALL 125 capability IDs plus all 21 feature crosswalk rows. **Prerequisites:** All prior slices and owner decisions; no open required P0/P1.

**Modify only, where needed:**

- `No unrelated source scope; any discovered repair gets a separately bounded phase/ledger entry`

**Proposed additions:**

- `backend/tests/keel_integration/test_end_to_end.py`
- `frontend/tests/browser/keel-integration.mjs`

**Migration:** Only approved phase migrations; no new destructive cleanup by default. See proposed schema details below; no SQL has been applied.

**Acceptance:** Full original backend/model/worker/frontend suite; native RLS/login/concurrency; Stripe TEST lifecycle; Shopify/Woo sandbox; populated upgrade/repeat; browser customer/operator journeys; inventory/revenue/credits reconciled; ledger and API contract diff exact. Applicable existing regressions plus exact AT IDs from ACCEPTANCE_TEST_SPEC.csv must pass. Skips/unknowns are not completion.

**Disable/recovery:** No automatic deploy. Staging backup/disable/recovery drill, operational alerts and explicit owner go/no-go; retain all unresolved blockers as BLOCKED.

**Completion gate:** freeze phase-base/current commit; log exact command, conditions and results; reconcile committed/staged/unstaged/untracked path/action sets and ledger; no unreviewed files, failed applicable checks or unapproved policy. Return precise handoff if blocked.

## Proposed additive migration details

Migration filenames are reserved plan proposals after supplied latest `20261024000000`; confirm no collision against approved main before creating them. Exact DDL/RLS is implementation work and must first reconcile pg_catalog against supplied schema/migrations.

| Proposed migration | Data/constraint scope | Backfill and grants |
|---|---|---|
| 20261025000100_integration_principal_permissions.sql | Explicit platform operator memberships and permissions on existing users; tenant activation checks/indexes; audit | Owner-approved operator bootstrap only; tenant owner not elevated; ceopro_app cannot mutate grants; narrowly scoped operator functions fixed search_path |
| 20261025000200_explicit_grants_and_operation_receipts.sql | Explicit grant semantics and aliases; durable tenant/actor/feature/period/key/fingerprint operation receipts; state/amount/result/refund uniqueness | Tenant effective-rights before/after report; no values without ENT-001; RLS/FORCE RLS and constrained worker execution; preserve Task 6 report table |
| 20261025000300_catalog_versions_and_transition_intents.sql | Versioned approved catalog/contract grants, immutable historical price identity and transition intent/schedule linkage | Never overwrite historic Stripe price/assignment; current tenant vectors snapshot; typed approval/effective date |
| 20261025000400_managed_promotions.sql | Managed promo, allowed plan/term/currency links, provider coupon mapping, reservations/redemptions with expiry and unique session/event | No automatic import of arbitrary coupon data; bounded counts/reservation transitions under row locks; operator writes/customer safe read |
| 20261025000500_quote_revisions_and_provider_intents.sql | Quote, immutable revision/features/cost/FX snapshot, approval/offer/acceptance/provider intent and contract history links | Tenant-private RLS, costs operator-only; no copying quote acceptance into active assignment; preserve manual approved contracts |
| 20261025000600_operator_notification_outbox.sql | Durable quote notification event/attempt/receipt, actor and recipient linkage, delivery uniqueness | Quote state+outbox same transaction; restricted consumer privileges; no raw secrets/cost metadata to customer |
| 20261025000700_product_identity_import_drafts_lineage.sql | Tenant SKU index/aliases, import kind/draft/revision/row decisions, canonical external identity/revision links, job heartbeat/lease/retry and inventory source linkage | Report duplicate/colliding SKUs before uniqueness; preserve existing IDs/barcodes/mirrors; all target rows same tenant; stock/invoice totals reconcile |
| 20261025000800_connector_claims_and_canonical_state.sql | Durable generic source lease/version/checkpoint and staged/review/promoted status | Existing sources default to their prior safe behavior until approved; worker discovery limited to allowed collector keys; cleanup fences old leases |
| 20261025000900_store_connections_external_links.sql | Store connection source FK+tenant/provider/shop identity, encrypted vault reference/version, lease/progress; external product/variant/order/item/sale/invoice/stock lineage | Unique tenant/source/external identity and revision; cross-table tenant composite FK checks; dedicated least-privilege discovery/consumer functions |
| 20261025001000_shopify_oauth_events_privacy.sql | Nonce/state hashes/expiry/consumption, token version metadata, delivery IDs, privacy jobs/reports/exclusions, inventory locations | Short-lived state; no tokens in plaintext; raw signed event data minimized per PRIVACY-001; all erasure effects audited/scoped |
| 20261025001100_pricing_operation_result_links.sql | Request receipt → existing outcome/evidence with params/policy version and typed status/error | Preserve historical results; no destructive recompute; indexes by tenant/product/as_of; RLS/FORCE RLS |
| 20261025001200_mpi_evidence_read_state.sql | Optional evidence-backed subject read snapshot/refresh state, eligible review IDs/model revision/status/confidence | No second score authority; pointer to immutable evidence; COMPETITOR global-ID semantics; nonfuture/safety indexes if approved |

Do not add a table if an existing Python table can express the same invariant without a competing authority. Document that refinement as an ADR/schema delta before editing. All new grants/roles/policies need up/down or safe-disable proof, runtime-role tests and populated migration lock-time evidence.

## Commands for each implementation slice

Run from a **new clean integration branch based on approved post-Task-6 commit**, never this supplied dirty archive. Use existing migration runner `cd backend; python -m scripts.apply_migrations` only with validated dedicated test DSN/role configured locally; guarded native runner `python -m scripts.integration_review --database --junitxml <evidence-path>`. Add each new integration test module to the guarded collection, and fail if it was not collected. For targeted pure/service tests use `python -m pytest -q <approved test paths>`; full backend regression is documented as `python -m pytest -q src/` once model dependencies and isolated DB/Redis are ready. Frontend `npm ci`, `npm test`, `npm run build`, browser `npm run test:browser` with isolated test API/resources.

Freeze phase base in SOURCE_BASELINES.md. Reconcile `git diff --name-status <base> HEAD`, staged/worktree `git diff --name-status <base>` plus `git ls-files --others --exclude-standard`; verify operation type, both rename endpoints, reason/capability/test evidence, not only counts. No files hidden by ignored patterns may escape deliberate source review. Keep build caches out of deliverable commits. A skip, provider fake or missing PostgreSQL server cannot turn a required release test green.


## Phase 0R refinement

See [PHASE0R_README.md](PHASE0R_README.md), [SOURCE_SNAPSHOT_RECONCILIATION.md](SOURCE_SNAPSHOT_RECONCILIATION.md), [SCHEMA_VERIFICATION.md](SCHEMA_VERIFICATION.md) and [DOMAIN_READINESS.md](DOMAIN_READINESS.md). Exact capability source roots, real schema lineage and thirteen concrete owner questions have been refined; no implementation or approval occurred. Earlier 56-pass/94-skip backend and 90-pass frontend/build logs are prior Phase 0 evidence, not rerun Phase 0R acceptance. SOURCE-001 and VERIFY-001 remain blocked. Raw lexical DB evidence is nonauthoritative.
