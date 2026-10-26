# Current integration inventory update - 2026-10-26

Authoritative current evidence: [Phase6 acceptance](PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md) and [remaining checkpoint](REMAINING_INTEGRATION_CHECKPOINT.md). The older inventory below is historical; its absent SKU/history/source reconciliation and unverified Stripe statements are not the current milestone state. Billing/onboarding completion is inherited from a00669d and its reports, not rerun here.

- VERIFIED: original bilingual catalog/form/archive/restore/GTIN/history; durable manual upload and structured invoice/stock review/post; source catalog review/create/link; original provider accounting and explicit selected stock; current-history pricing/MPI integration.
- VERIFIED with controlled upstream: secure Shopify/Woo adapters, fenced worker, incremental order checkpoints, signed intake and reversible privacy holds; actual merchant E2E remains UNRUN.
- VERIFIED, disposable-only: default-off Tenant Owner opt-in per source/category and existing-service canonical retry. Automatic invoices remain policy blocked in API/SQL. Stock requires existing explicit source/field/location approval; no silent priority/aggregation.
- PRESERVED: existing Python product pages, models, billing/auth/credit/receipt authorities, forecast/sentiment/pricing mathematics, RAG/storage and directly affected consumers (237 tests).
- DEFERRED: Business Recommendations, per existing owner priority. No new entitlement alias or engine.
- POLICY BLOCKED / NOT CERTIFIED: irreversible privacy erasure/retention, automatic invoice rules, universal collisions/stock priority, unspecified PRICE/MPI numerical policy, real merchant/provider and production rollout requirements.
- Current totals:366 unique native/backend tests and201 frontend tests passed, zero failures/skips; post-ff42 native and13 frontend passed as overlapping subsets;137 fresh/123+14 upgrade/repeat0 migrations verified. Actual controlled-source Chrome/Python/PG catalog/invoice/stock/reload/opt-in/English/Arabic journey passed. No production certification claimed.

---

## Historical inventory retained below

# KEEL feature inventory and practical verification

This inventory follows actual Phase 6 evidence. Route existence alone is not acceptance. See PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md for scenario-level results, exact counts and PASS/BLOCKED/NOT RUN labels.

## Architecture and authority

KEEL gives a business tenant workspaces for products, sales, stock observations and market evidence, then serves dashboard and advisory workflows. Users can belong to several workspaces. React/Vite presents customer and platform experiences. FastAPI owns identity checks, business rules, billing and AI orchestration. PostgreSQL is canonical storage with FORCE RLS and the restricted ceopro_app application role; schema migrations use the schema-owner connection. Redis supports streams, caching and rate limits. MinIO/S3-compatible storage keeps uploads and generated files.

Canonical file sales are staged/reviewed before authorized promotion. Shopify/WooCommerce records remain typed provider staging unless approved posting semantics apply. Provider stock observations are not canonical movements. Knowledge Base documents are retrieval sources, not sales. Python owns Stripe/subscription/entitlement, Credit and usage authority. The Node reference is read-only, not a second runtime.

The merged code preserves upstream Python competitor discovery/enrichment, provenance, monitoring, market intelligence, campaign/image assets and workers alongside integration work for authentication/platform authority, billing/credits, canonical imports/dashboard, product/manual-stock security, forecasting/pricing/MPI/RAG and tenant notifications. This classification follows the merge evidence and unified ledger.

## Customer feature inventory

| Capability / acceptance IDs | UI and Python entry points | Data, workers and provider | Verified status and restrictions |
|---|---|---|---|
| Authentication/workspaces: AUTH-001..013 | /login, registration, invitation, workspace selector; backend/src/ai/routers/auth.py, core/security.py | users/memberships; Redis session/rate services; SMTP for actual email | Phase 6 session/workspace journeys and denial passed; Phase 7 auth/platform browser 26 assertions passed. AUTH-004 issuer/audience and AUTH-013 Node identity cutover remain release decisions. |
| Tenant team/platform: AUTH-002, PLATFORM-001..005 | /settings/team, /platform; routers/settings.py, routers/platform.py | membership/platform tables, SMTP invitations | Phase 7 Owner/Admin lifecycle, invitation acceptance, search/page, role separation, tenant denial, Arabic RTL passed. Exceptional finance/catalog actions and operator notifications remain gated/partial. |
| Stripe: SUB-001..014 | /billing; routers/billing.py, billing services | Stripe test key/webhook secret for provider sandbox | Phase 6 107 backend passed, one live-only case skipped; local signed contract browser flow passed. Live Stripe/SCA/webhook certification is blocked. |
| Entitlements, usage and Credits: ENT-001..011, CREDIT-001..006 | Billing/usage views; core/entitlements.py, core/usage.py, billing/credits.py | Subscription, reservation, receipt and ledger records; worker revalidation per existing contract | Approved local behavior passed. U1–U5/U7 gate units, mappings, grants, conversions, adjustment and historical rights. No unmapped aliases are activated. |
| Products/manual stock: related IMPORT-003, IMPORT-006, ENT-005/006 | /products; routers/products.py | Canonical products/manual inventory; source observations separate | Phase 6 CRUD/decimal stock, staff denial, tenant/RLS checks passed. SKU policy, stock history/reconciliation and U5 mappings remain gated. |
| File import/review: IMPORT-001..012 | /connect-data; routers/extraction.py and typed review/promotion services | Staging and canonical sales; parser/MinIO configuration | Phase 6 CSV upload→review→canonical posting→dashboard passed English/Arabic; XLSX/PDF parser contracts passed. Remaining format edge/refund/invoice semantics are documented in Phase 6. |
| Dashboard: IMPORT-012, SUB-011 and related dashboard cases | /dashboard; routers/dashboard.py | Canonical invoices/items; no separate worker | Imported figures, periods/charts and no mirror double count passed. FX/mixed-currency and dashboard_analytics U5 remain unresolved; existing access preserved. |
| Shopify/WooCommerce: CONNECT-001..006, STORE-001..008, SHOP-001..008, WOO-001..006 | /connect-data; routers/onboarding.py and provider sync modules | OAuth/store keys, typed staging/review, connector worker | Native controlled-provider staging/worker tests passed. Phase 7 browser smoke validated input forms only (9 assertions in 3 scenarios, no credentials submitted. Full connect/sync browser and live merchant certification remain NOT RUN/BLOCKED. |
| Competitor/Market Intelligence | /market and competitor pages; routers/competitors.py, discovery.py, competitor_enrichment.py, src/market_scraper | Search/scrape/enrichment providers, Redis streams and market supervisor | Phase 6 fixture-backed English/Arabic browsers and worker tests passed. Live provider certification blocked; no arbitrary crawl. Image URL association exists; dedicated gallery is a UI gap. |
| Demand Prediction: forecast/ENT-008/009/010 boundaries | /forecasting; routers/forecasting.py, src/ai/forecasting | Canonical sales, Redis consumer, existing baseline forecaster | Phase 6 generation, persistence, entitlement and English/Arabic browser passed. Accuracy not certified. |
| Pricing Recommendations: PRICE-001..008 | /pricing; routers/pricing.py and existing pipeline | Product/cost and matched market evidence | Phase 6 backend/browser contract passed with controlled evidence; no automatic price change. ai_pricing U5 and O-PRICE decisions remain. |
| Market Perception: MPI-001..010 | Market Perception page; routers/mpi.py and existing sentiment pipeline | Eligible reviews and existing scorer/worker | Phase 6 supported scopes and low-sample states passed native/browser in English/Arabic. Keep market_intelligence gate; do not activate market_perception alias. Historical analysis storage is absent; O-MPI remains open. |
| RAG/Knowledge Base: IMPORT-002; ENT-007/008/010 boundaries | Knowledge Base/Assistant; routers/rag.py, src/ai/rag | MinIO, document/chunk/vector state; optional LLM/embedding provider | Phase 6 upload/index/retrieval/history/citation/tenant contracts passed. Live model answer certification unavailable. |
| Marketing campaigns/images: Python feature | /marketing; routers/marketing.py, src/ai/marketing, image_worker.py | Campaign LLM, optional image provider, MinIO and image worker | Phase 6 backend job/storage fixtures passed. Phase 7 real options API and Arabic mobile route smoke passed; no generation called. Gallery browser flow remains blocked without approved provider test config. |
| Notifications/Smart Alerts: PLATFORM-005 plus Migration 103 evidence | Inbox and alerts; routers/notifications.py and routers/alerts.py | Durable tenant_notifications/outbox plus current reads/preferences/digests; digest in API process | Phase 6 persisted read/dismiss/dedup/tenant isolation passed. Basic inbox utility is non-metered; system_alerts stays unmapped; platform delivery remains separate/partial. |
| Promotions/custom offers/catalog exceptions: PROMO-001..005, CUSTOM-001..013, PLATFORM-003/004 | Existing restricted services/routes | Approval and finance/catalog controls | Phase 6 workflows NOT RUN; remain gated/default-off. Do not mark complete. |
| Business Recommendations | No customer-facing integration | Existing deterministic Python insights engine | DEFERRED by owner priority; no new UI, entitlement or persistence. |

Other Python-only pages/APIs include reviews, reports, opportunity/news views and scraping analysis. Inspect backend/src/ai/routers and local /docs, but do not treat API presence as full acceptance.

## Practical test paths

- Environment and setup: tools/keel-verification/README.md and PHASE7_DEVELOPER_GUIDE.md.
- Authenticated feature journeys: Test-Browser.ps1 and scripts under frontend/tests/browser; Phase 6 report identifies exactly which ran.
- Platform lifecycle/search: backend/scripts/auth_browser_verification.py with local SMTP and a dedicated allowed keel_billing_test_* DB.
- Shopify/Woo UI validation without network: tools/keel-verification/Test-HandoffBrowser.ps1. Full store testing needs a safe test merchant/OAuth configuration.
- Marketing gallery: frontend/tests/browser/marketing-images.mjs requires model/image service and MinIO; it can make external calls. Phase 7 did not invoke it.
- Backend: Test-Backend.ps1 with a focused test path. Frontend: Test-Frontend.ps1. Avoid unbounded reruns.