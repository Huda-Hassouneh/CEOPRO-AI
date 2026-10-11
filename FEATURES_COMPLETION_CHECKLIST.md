# CEOPRO-AI — Features Completion Checklist

**Scope:** First fifteen reviewed features — `dashboard_analytics`, `market_intelligence`, `market_perception`, `demand_prediction`, `inventory_intelligence`, `product_management`, `competitor_management`, `data_integration`, `connected_data_sources`, `document_extraction`, `document_storage_mb`, `rag_assistant`, `business_recommendations`, `system_alerts`, and `ai_pricing`.

Check each item only after verifying it end-to-end with real test data. Existing code is not proof that a background job runs successfully.

## Team Status Board

**Purpose:** This is the single authoritative place where teammates claim a feature and communicate whether it is **Not Started**, **Processing**, or **Solved**. The checkboxes in the sections below track individual verification tasks and remain separate from the feature-level status.

|   # | Feature                                                   | Status         | Owner | Last updated (YYYY-MM-DD) | Current focus / blocker |
| --: | --------------------------------------------------------- | -------------- | ----- | ------------------------- | ----------------------- |
|   1 | **Dashboard Analytics** (`dashboard_analytics`)           | ⚪ Not Started | —     | —                         | —                       |
|   2 | **Market Intelligence** (`market_intelligence`)           | ⚪ Not Started | —     | —                         | —                       |
|   3 | **Market Perception** (`market_perception`)               | ⚪ Not Started | —     | —                         | —                       |
|   4 | **Demand Prediction** (`demand_prediction`)               | ⚪ Not Started | —     | —                         | —                       |
|   5 | **Inventory Intelligence** (`inventory_intelligence`)     | ⚪ Not Started | —     | —                         | —                       |
|   6 | **Product Management** (`product_management`)             | ⚪ Not Started | —     | —                         | —                       |
|   7 | **Competitor Management** (`competitor_management`)       | ⚪ Not Started | —     | —                         | —                       |
|   8 | **Data Integration** (`data_integration`)                 | ⚪ Not Started | —     | —                         | —                       |
|   9 | **Connected Data Sources** (`connected_data_sources`)     | ⚪ Not Started | —     | —                         | —                       |
|  10 | **Document Extraction** (`document_extraction`)           | ⚪ Not Started | —     | —                         | —                       |
|  11 | **Document Storage** (`document_storage_mb`)              | ⚪ Not Started | —     | —                         | —                       |
|  12 | **RAG Assistant** (`rag_assistant`)                       | ⚪ Not Started | —     | —                         | —                       |
|  13 | **Business Recommendations** (`business_recommendations`) | ⚪ Not Started | —     | —                         | —                       |
|  14 | **Smart Alerts** (`system_alerts`)                        | ⚪ Not Started | —     | —                         | —                       |
|  15 | **AI Pricing Recommendations** (`ai_pricing`)             | ⚪ Not Started | —     | —                         | —                       |

**Status definitions**

- **⚪ Not Started** — Nobody has claimed the feature for the current completion effort. It does **not** mean the existing implementation is absent.
- **🟡 Processing** — A teammate has claimed the feature and is implementing, investigating, integrating, or testing it. If blocked, **keep Processing** and record the blocker in the last column.
- **🟢 Solved** — All checklist items for that feature have been checked after real end-to-end verification, including applicable authorization, calculations, data persistence, and tests. Code existing by itself is insufficient.

**How the team should use this file**

1. **Before starting:** Find the feature row, set the status to **🟡 Processing**, enter your name in **Owner**, today's date in **Last updated**, and the immediate next task in **Current focus / blocker**. Save and share/commit the change before beginning work.
2. **While working:** Check an item as `- [x]` only after verifying it. Update the row's date and current focus/blocker when meaningful progress is made. The owner coordinates any teammates contributing to the same feature.
3. **When finished:** Confirm every required item under the feature is checked, review the actual UI/API/database/AI E2E evidence, then change its status to **🟢 Solved**, update the date, and briefly note where the evidence/report can be found.
4. **If work is paused or a test fails:** Leave it **🟡 Processing**, identify the blocker and responsible teammate. If a solved feature regresses, move it back to **🟡 Processing**, reopen the affected checkbox, and record why.
5. **To transfer ownership:** Update **Owner**, **Last updated**, and the next-step note together; never overwrite another teammate's claim without coordination.

**Collaboration note:** Markdown does not provide automatic concurrent editing or status locking. Keep this file in a shared Git repository and use commits/PRs (or another shared document with edit history). Pull the latest changes before editing and resolve simultaneous edits instead of overwriting them.

**Initial setup:** All 15 statuses start as **⚪ Not Started / Unassigned** because no teammate claims were supplied. This is a coordination baseline, **not** an assessment that CEOPRO has no implemented functionality.

---

## 1. Dashboard Analytics (`dashboard_analytics`)

- [ ] Implement Invoice CSV/XLSX import into `invoices` (and `invoice_items` when item details are supplied).
- [ ] Implement Inventory CSV/XLSX import into `inventory`.
- [ ] Confirm existing sales extraction reliably populates `products` and `transactions`.
- [ ] Correct invoice reporting dates, currency handling, and duplicate-import prevention.
- [ ] Verify AI competitor discovery/tracking and review/sentiment data reach the dashboard.
- [ ] Verify demand-forecast data appears only with the correct entitlement.
- [ ] Enforce `dashboard_analytics` access and tenant isolation in the backend.
- [ ] Run full dashboard UI/API/database E2E tests, including empty and partial data states.

## 2. Market Intelligence (`market_intelligence`)

- [ ] Verify AI competitor discovery, product mappings, scraping, and price updates run successfully.
- [ ] Verify competitor score snapshots and market observations are populated and current.
- [ ] Verify review/sentiment and sales/forecast inputs used by market insights.
- [ ] Validate pricing, composite, and top-segment score calculations and missing-data handling.
- [ ] Verify competitor comparisons, expansion opportunities, and recent price changes against database records.
- [ ] Confirm AI Pricing and Market Perception sections respect their separate feature permissions.
- [ ] Enforce Growth/Enterprise entitlement and tenant isolation in backend APIs.
- [ ] Run Market Intelligence UI/API/database/AI E2E tests and verify PDF export.

## 3. Market Perception (`market_perception`)

- [ ] Confirm the AI team's plan and implementation for collecting **business-level** reviews.
- [ ] Confirm the AI team's plan and implementation for collecting **product-level** reviews.
- [ ] Verify competitor review collection and sentiment processing work end-to-end.
- [ ] Correct subject filtering and authorization for BUSINESS, PRODUCT, and COMPETITOR MPI requests.
- [ ] Enforce safe/allowed review filtering and tenant isolation consistently.
- [ ] Verify the hosted Gradio MPI contract, scores, confidence, and insufficient-review behavior.
- [ ] Decide plan assignment/pricing and enforce the `market_perception` entitlement.
- [ ] Run MPI E2E tests for all three levels, including missing-data and AI-failure cases.

## 4. Demand Prediction (`demand_prediction`)

- [ ] Verify imported historical sales in `transactions` are complete, correctly dated, deduplicated, and usable by the forecasting model.
- [ ] Connect a working forecast-generation trigger (on demand, scheduled job, or event/worker) and verify it actually runs.
- [ ] Agree and validate the AI ↔ backend forecast contract: target-day values vs 7/30-day totals, date ranges, units, and model version.
- [ ] Correct forecast aggregation to prevent double-counting overlaps or treating a single-day prediction as a whole-period total.
- [ ] Verify `demand_forecasts` contains sufficient 7-day/30-day coverage; show partial/unavailable results when coverage is incomplete.
- [ ] Validate AI errors, missing/negative predictions, low-history fallback, and stale forecasts without showing fabricated values.
- [ ] Persist and display confidence ranges and model-accuracy data only when supported by real AI/model records.
- [ ] Verify inventory context and recommendations use current `inventory` records; keep `inventory_intelligence` separately gated.
- [ ] Enforce Growth/Enterprise access, reject Starter, and verify backend tenant isolation.
- [ ] Run forecasting UI/API/database/AI E2E tests, including generation, 7/30-day totals, charts, details, and PDF export.

## 5. Inventory Intelligence (`inventory_intelligence`)

- [ ] Complete Inventory CSV/XLSX ingestion into `inventory` and verify stock accuracy and freshness.
- [ ] Agree on one authoritative AI/backend recommendation formula, data contract, and ownership for saved recommendations.
- [ ] Correct zero-stock handling so out-of-stock products receive appropriate restock recommendations.
- [ ] Correct multi-warehouse stock aggregation and avoid selecting an arbitrary warehouse record.
- [ ] Validate forecast horizon and completeness before using predicted demand in inventory decisions.
- [ ] Handle missing/stale inventory, safety stock, supplier constraints, and incomplete forecasts without misleading recommendations.
- [ ] Implement and connect a dedicated backend inventory recommendations API with tenant isolation and `inventory_intelligence` entitlement enforcement.
- [ ] Replace the frontend Coming Soon page with real recommendations; keep Inventory Intelligence separate from `demand_prediction` permissions.
- [ ] Decide plan assignment/pricing and verify subscription access rules.
- [ ] Run UI/API/database/AI E2E tests for sufficient, low, zero, missing, and multi-warehouse stock, recommendation math, authorization, and AI failures.

## 6. Product Management (`product_management`)

- [ ] Implement real product CRUD APIs (routes, controllers, services, and repositories) with validation and authorization.
- [ ] Replace frontend product API stubs and placeholder list, create, edit, and detail screens with working UI.
- [ ] Enforce `product_management` access and `tracked_products` limits for manual creation, imports, and concurrent requests.
- [ ] Establish stable product identifiers and reliable import matching to prevent duplicate products and incorrect merges.
- [ ] Prevent imports from silently overwriting owner-maintained product fields and deduplicate repeated sales imports.
- [ ] Verify price history captures appropriate initial prices, price changes, and currency changes without altering historical sales.
- [ ] Define and test product archiving/soft deletion while preserving transactions, forecasts, and related records.
- [ ] Connect accurate, current inventory data to product details, including multi-warehouse stock where applicable.
- [ ] Integrate Quick Sale with real persisted sales/invoices or disable false-success UI until implemented.
- [ ] Run product CRUD/import/limit/price-history UI, API, database, and E2E tests, including tenant isolation, Arabic/English, and downstream feature consistency.

## 7. Competitor Management (`competitor_management`)

- [ ] Connect the Add Competitor form to the real `POST /competitors` backend API and verify database persistence.
- [ ] Enforce `competitor_management` authorization and `tracked_competitors` plan/custom-plan limits for manual and AI-created competitors.
- [ ] Unify competitor identities across backend and AI discovery; prevent duplicates and cross-tenant identity leakage.
- [ ] Implement competitor edit, untrack, and reactivate workflows without losing historical observations.
- [ ] Correct product mappings, currency comparability, stale/blocked observations, and competitor price-difference calculations.
- [ ] Verify normal product imports trigger AI competitor discovery or document and implement the missing trigger.
- [ ] Apply plan/custom-plan monitoring cadence to approved `data_sources` and verify actual worker scheduling.
- [ ] Verify scraper source policies, collection jobs, retry/error handling, and freshness logs with approved sources.
- [ ] Fix static industry filters, inactive competitor controls, and Arabic/English UI translations.
- [ ] Test Growth (10) and Enterprise (50) tracking limits, concurrency, feature access, and tenant isolation.
- [ ] Run competitor UI/API/database E2E tests plus opt-in live AI discovery/scraper integration tests.

## 8. Data Integration (`data_integration`)

- [ ] Complete real provider authentication, connection verification, and recurring synchronization for supported external data sources.
- [ ] Connect backend `data_sources` registration/configuration to the correct AI connector workers, credentials, and approved sync schedules.
- [ ] Ensure synced connector records are validated, staged, and promoted into the correct business tables—not merely marked as processed.
- [ ] Fix frontend preview/stub actions that report success without successful connection, sync, or persistence.
- [ ] Show truthful source verification/sync statuses, persist source URLs/configuration correctly, and display freshness and failures.
- [ ] Implement real job details, staging review, retries, reconnection, disconnect, and safe credential handling.
- [ ] Enforce `data_integration`, `connected_data_sources` (Starter 1 / Growth 5 / Enterprise 20), and `document_extraction` limits server-side, including concurrency and custom plans.
- [ ] Prevent duplicates and inconsistent business records across repeated uploads, retries, and connector syncs.
- [ ] Complete Invoice and Inventory CSV/XLSX ingestion into their proper tables while preserving the existing sales ingestion flow.
- [ ] Verify tenant isolation/RLS, source ownership, upload validation, translations, connection health, and downstream metric freshness.
- [ ] Run full UI/API/database/worker E2E tests and separate opt-in real AI/provider connector tests; never count source registration as successful synchronization.

## 9. Connected Data Sources (`connected_data_sources`)

- [ ] Make active-source quota checks and source creation atomic to prevent concurrent registrations from exceeding limits.
- [ ] Align Node backend and AI source-registration paths so all active sources follow the same quota and tenant rules.
- [ ] Implement secure disable/reactivate (and disconnect where supported) actions, with correct slot release and historical-data preservation.
- [ ] Distinguish registered, active, verified, synchronized, and failed sources; never label unverified connections as successful.
- [ ] Fix frontend source-action success messages and show accurate used/remaining slots and connection states.
- [ ] Standardize which source types count toward the limit; exclude inactive manual-upload document sources as intended.
- [ ] Prevent unintended duplicate active registrations, including retries and simultaneous requests.
- [ ] Handle subscription upgrades, downgrades, and custom-plan limits when existing active connections exceed capacity.
- [ ] Verify Starter (1), Growth (5), Enterprise (20), disabled-feature, and tenant/RLS enforcement at both API and database levels.
- [ ] Run UI/API/database concurrency and lifecycle E2E tests, plus opt-in AI connector tests; distinguish source registration from verified synchronization.

## 10. Document Extraction (`document_extraction`)

- [ ] Align frontend file formats and the displayed upload-size limit with backend-supported CSV/XLSX/XLSM/PDF and the configured per-file maximum.
- [ ] Correct the downloadable sales template so its required headers match backend validation.
- [ ] Verify actual file contents/signatures, required fields, dates, currencies, and malformed-file rejection.
- [ ] Make extraction-quota checks, reservations, and charges concurrency-safe; verify KB rounding and billing-period resets.
- [ ] Make job creation and usage charging failure-safe and consistent across retries, timeouts, and rejected uploads.
- [ ] Define retained business-file storage policy and account for retained bytes correctly alongside RAG document storage.
- [ ] Verify the live hosted Gradio extraction contract, response validation, and meaningful AI failure handling.
- [ ] Verify staging, ingestion-job state transitions, worker completion, and actual `products`/`transactions` persistence.
- [ ] Prevent duplicate products and sales transactions during repeat uploads, retries, and concurrent imports.
- [ ] Replace job/staging UI previews with accurate progress and error states; test entitlements, tenant isolation/RLS, localization, and full UI/API/database/AI E2E flows.

## 11. Document Storage (`document_storage_mb`)

- [ ] Define which retained original documents count toward storage, including RAG uploads and any retained business files; exclude temporary or metadata-only uploads as intended.
- [ ] Verify byte-to-MB usage calculations and Starter (1,024 MB), Growth (10,240 MB), Enterprise (51,200 MB), and custom-plan capacity limits.
- [ ] Align Node PostgreSQL `BYTEA` storage, AI-managed MinIO objects, and quota ownership without double-counting or overlooking retained files.
- [ ] Make storage-capacity checks and document persistence atomic to block concurrent over-limit uploads.
- [ ] Implement secure document deletion and ensure capacity is reclaimed only when retained data is actually removed under the retention policy.
- [ ] Align frontend RAG file-size messaging and validation with the actual backend limit (previously 10 MiB displayed versus 2 MiB accepted).
- [ ] Handle failed uploads, AI-processing failures, retries, and partial writes without leaked storage or incorrect quota usage.
- [ ] Define subscription downgrade and full-storage behavior without silently deleting customer documents.
- [ ] Show accurate storage usage, document status, upload errors, and Arabic/English messaging; do not mark AI processing ready before completion.
- [ ] Run storage UI/API/database and concurrency E2E tests, with tenant isolation/RLS, upload/delete/reclaim scenarios, and separate opt-in MinIO/AI integration tests.

## 12. RAG Assistant (`rag_assistant`)

- [ ] Verify Knowledge Base uploads truly become AI-searchable; distinguish stored, processing, indexed/ready, and failed document states.
- [ ] Agree on and validate one authoritative RAG retrieval architecture and contract between hosted Gradio and the AI team's indexed PostgreSQL/MinIO pipeline.
- [ ] Fix frontend citations to show the correct document names, source passages, and document/chunk IDs; verify citation-detail retrieval.
- [ ] Make `rag_assistant` token usage accounting concurrency-safe; verify provider token metadata, missing totals, and billing-period resets.
- [ ] Align Knowledge Base upload-size and format validation with backend limits, and enforce `document_extraction`/`document_storage_mb` charges consistently.
- [ ] Address the latest-10-document retrieval restriction and verify searching the intended tenant-authorized document collection.
- [ ] Define and implement persisted conversation history if multi-turn chat is a supported requirement; verify session isolation and context handling.
- [ ] Implement/document authorized document deletion, reprocessing, and reindexing so removed or failed documents do not supply stale citations.
- [ ] Enforce tenant isolation for uploads, retrieval, chunks, citations, and chat; test insufficient evidence, prompt injection, AI errors, and retries.
- [ ] Run complete RAG UI/API/database/AI E2E tests with known-answer documents, citation accuracy, quotas, localization, and opt-in live hosted-AI verification.

## 13. Business Recommendations (`business_recommendations`)

- [ ] Decide standard/custom-plan availability and pricing for `business_recommendations` (currently absent from Starter, Growth, and Enterprise); enforce the boolean entitlement server-side.
- [ ] Expose a tenant-authorized Node recommendations API that integrates the existing AI `GET /dashboard/recommendations` contract, validates responses, and handles AI failures and timeouts.
- [ ] Replace placeholder/static frontend recommendations with real tenant-specific results, correct priority labels, empty/loading/error states, and working product navigation.
- [ ] Reconcile sales inputs from `invoices`/`invoice_items` versus imported `transactions` so recommendations use complete, nonduplicated and correctly dated quantities.
- [ ] Verify competitor price comparisons use current mapped products, comparable currencies/units, valid observations, and appropriate stale-data handling.
- [ ] Validate AI calculations and configurable thresholds for price gaps, consecutive 30-day sales change, weighted sentiment, forecast-versus-current-pace change, and 14-day competitor events.
- [ ] Expose trustworthy recommendation evidence: source records, observation periods, freshness, missing-data reasons, and explainable rule-based priority (not a success probability).
- [ ] Define ownership and persistence of recommendation IDs, refresh/deduplication, dismissals, accepted actions, and outcomes; keep them distinct from existing forecasting `recommendation_outcomes` unless explicitly integrated.
- [ ] Localize recommendation categories/messages and statuses for English/Arabic (including RTL) and display clear fallbacks when evidence is missing or a data source is unavailable.
- [ ] Run rule-level AI, Node API, subscription/tenant-RLS, PostgreSQL data-consistency, and real frontend E2E tests; include opt-in live AI integration, failure handling, and evidence/priority checks.

## 14. Smart Alerts (`system_alerts`)

- [ ] Define commercial availability (currently excluded from Starter/Growth/Enterprise), custom-plan access, and enforce the `system_alerts` boolean entitlement on tenant business-alert APIs and delivery while preserving essential billing/account notifications.
- [ ] Connect AI-created `market_alert_events` to the existing `tenant_notification_outbox`/worker so eligible recipients receive real competitor alerts in `tenant_notifications` and the customer notification bell.
- [ ] Implement tenant-authorized CRUD for `market_alert_rules` and configurable thresholds, including validation, active/inactive behavior, and tracked-competitor ownership.
- [ ] Wire Smart Alerts pages, cards, rules, and notification navigation to real backend data; remove placeholders and false-success actions, with accurate loading/empty/error states.
- [ ] Define and implement alert acknowledgment/resolution separately from notification read/archive state, preserving alert history and auditability.
- [ ] Make price-observation → event → outbox → recipient delivery idempotent under repeated scraper runs, concurrent events, retries, and worker restarts; prevent duplicate notification floods.
- [ ] Validate signed price-change formulas and `GT`/`GTE`/`LT`/`LTE` boundaries; guard zero old prices, mismatched currencies/units, stale or out-of-order observations, and untrusted source data.
- [ ] Enforce tenant and recipient authorization/RLS on alert rules, events, outbox, receipts, and deep links; verify restricted worker roles and protect confidential business data.
- [ ] Implement alert recipient/channel preferences, sensible noise controls and deduplication windows; define delivery latency/freshness targets and visible delivery-failure/retry behavior.
- [ ] Run rule-calculation, Node API, AI scraper, outbox/worker, frontend, subscription, concurrency, localization (English/Arabic/RTL), and tenant-isolation E2E tests; keep live source scraping opt-in and verify existing custom-plan offer notifications still work.

## 15. AI Pricing Recommendations (`ai_pricing`)

- [ ] Enforce `ai_pricing` entitlement and remaining recommendation allowance before each AI request; retain standard-plan exclusion and test custom-plan, disabled, suspended, and unauthorized access.
- [ ] Make quota reservation and usage charging concurrency-safe, with correct billing-period resets and fail-closed behavior when the tenant has no allocation.
- [ ] Define and test charges for `UNKNOWN` results, AI failures and timeouts; prevent double billing or duplicate evidence on retries, Generate/Refresh, and idempotent requests.
- [ ] Verify tenant-owned product prices/costs, active competitor mappings, and `ai_pricing` authorization/RLS across frontend, Node, AI, and database operations.
- [ ] Use appropriate latest reliable competitor observations; reject duplicate, stale, missing, incorrectly mapped, and noncomparable product/unit prices when calculating the market average.
- [ ] Validate currency conversions against fresh, correctly paired `currency_rates`, including JOD/USD comparisons and missing/outdated FX data.
- [ ] Independently verify AI raise/lower/hold/unknown decisions, average competitor prices, 5% competitiveness boundaries, and absent/zero market prices.
- [ ] Verify 15% price-movement cap, 10% markup-on-cost floor, explicit guardrail precedence, and accurate interpretation of heuristic confidence scores.
- [ ] Persist complete source evidence including selected competitor-price IDs; define history/refresh behavior and show recommendation credits, source provenance, and localized English/Arabic explanations in frontend.
- [ ] E2E-test the real Node → hosted Gradio `recommend` contract separately from AI FastAPI `/pricing/recommend`; cover quota/concurrency, errors/retries, persistence, UI, RLS, and opt-in live AI without automatically changing product prices.

---

**Completion rule:** Mark a feature complete only when its business data is available, calculations are correct, access controls are enforced, and its E2E tests pass.
