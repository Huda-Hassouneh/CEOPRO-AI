# Features and development map

Start here when changing a customer workflow. Frontend paths below are relative
to `frontend/src/features/`; backend router paths are relative to
`backend/src/ai/routers/`. Routes are customer entry points, not permission
grants: Python checks tenant membership and entitlements on every protected action.

**Implemented** means a code path exists. **Provider-dependent** needs external
credentials, service access or model weights. **Partial acceptance** means only
bounded scenarios were verified; it is not a production-readiness certificate.
Use [Testing](TESTING.md) for isolated tests and English/Arabic browser checks.
The dated [customer acceptance](DEMO_PHASE2_ACCEPTANCE.md) and
[confirmed-defect fixes](DEMO_PHASE3_REMEDIATION.md) are supporting evidence,
not prerequisites for understanding this guide.

## Dashboard analytics

Shows sales trends, product performance, stock risks and forecast context at
`/dashboard`. It needs canonical sales, products, costs and inventory; an empty
tenant should show an honest empty state. Calendar windows and currency matter:
revenue is not profit, and mixed physical units are not one homogeneous quantity.

- Code: `dashboard/`; `dashboard.py`; services in `backend/src/ai/dashboard/`.
  PostgreSQL supplies metrics; forecast/market workers supply derived context.
- Status: implemented, bounded English/Arabic acceptance. No external provider
  is needed for basic metrics. Test `test_dashboard_metrics_integration_db.py`
  against known invoices and date windows, including another tenant's exclusion.

## Product management

Customers use `/products` or `/catalog` to maintain bilingual names, SKUs,
prices, currency and acquisition costs. Products support downstream imports,
forecasts and comparisons; deleting/archiving must not erase historical sales.

- Code: `products/`; `products.py`, `catalog.py`; PostgreSQL `products` and
  audit/version records. Some product actions queue normal forecast/discovery work.
- Status: implemented, bounded disposable-record CRUD acceptance. Test
  `test_catalog_integration_db.py` for capacity, archive/restore, staff permissions
  and tenant isolation. No live provider is needed for catalog CRUD.

## Inventory management

Product detail and demand screens show physical balances, reorder levels and
forecast-driven replenishment advice. Customers update stock directly or import
a reviewed snapshot. A closing snapshot must not be treated as an opening balance
and have historical sales deducted again. Negative stock input is rejected.

- Code: `products/`, `forecasting/`; `products.py`, `dashboard.py`;
  PostgreSQL `inventory` and forecast evidence; forecast worker for derived advice.
- Status: implemented, bounded balance/negative-input acceptance. Test
  `test_dashboard_inventory_integration_db.py` and disposable product updates;
  distinguish raw low stock from model-based restock recommendations.

## Data connections and document extraction

At `/connect-data`, customers upload supported business files, inspect parsing
issues and confirm reviewed structured imports. Catalog identifiers, dates,
currency and duplicate invoice identities must reconcile before canonical writes.
Knowledge documents have a separate upload/indexing flow.

- Code: `data-connections/`, `data-ingestion/`; `extraction.py`, `onboarding.py`;
  `backend/src/ai/extraction/`, durable source/import jobs and MinIO uploads.
  Extraction uses API background processing, not a ninth required worker.
- Status: implemented; format/OCR/provider-dependent coverage varies. Tesseract
  is required for its OCR path. Test `test_extraction_template_contract.py` and
  `test_extraction_ingestion_pipeline_integration_db.py`, including preview,
  confirm, unresolved identities and exact idempotent replay.

## Demand prediction

At `/demand`, historical daily sales and product context drive demand estimates
and stock planning. The pipeline uses XGBoost with baseline/cold-start behavior
when history is insufficient. An actual computed forecast is not proof of its
accuracy on a customer's future sales.

- Code: `forecasting/`; `forecasting.py`;
  [forecasting pipeline](../backend/src/ai/forecasting/README.md), Redis forecast
  stream and PostgreSQL forecasts/evidence/model versions; `forecast` worker.
- Status: implemented with bounded real computed results; broader accuracy
  acceptance remains open. Test history/window and selection regressions, then
  submit one disposable forecast job and verify completion/evidence, not just 202.

## Competitor management

At `/market`, customers maintain competitors, product mappings and dated price
observations. Manual observations are business inputs; a URL alone does not
prove that KEEL visited it or independently verified its price.

- Code: `market-intelligence/`; `competitors.py`, `competitor_enrichment.py`,
  `discovery.py`; `backend/src/market_scraper/` collection/classification code.
  PostgreSQL stores tenant competitors, prices and evidence. Prices, discovery
  and enrichment workers handle configured external collection.
- Status: implemented; live collection is provider/policy-dependent and only
  partially accepted. Test `test_competitor_v2_integration_db.py` and provenance
  regressions. Disposable catalog changes can refresh competitor classification;
  verify original metrics and derived overlap after cleanup.

## Market intelligence and customer perception

Market/trend/profile screens combine recorded competitor observations and review
evidence. Customers inspect source labels and customer sentiment rather than
inferring a conclusion from missing data. Low sample sizes must remain unknown.

- Code: `market-intelligence/`; `mpi.py`, `reviews.py`, `sentiment.py`;
  market analysis/perception packages and evidence tables. Analysis and enrichment
  workers consume configured collection results; sentiment may need local weights.
- Status: implemented paths, partial acceptance. Manual/collected provenance
  wording has regressions; broad live research, sentiment quality and all trend
  controls are unverified. Test empty/insufficient samples, supported subject
  types and source provenance before testing real review collection.

## Pricing recommendations

At `/pricing`, customers compare products and inspect a proposed price with
market/demand context and persisted history. The system needs actual comparison
coverage, costs and currency evidence; absent or stale evidence must be visible.
Generating a recommendation does not authorize applying a product-price change.

- Code: `pricing/`; `pricing.py`; `backend/src/ai/pricing/` and forecasting
  comparison modules; PostgreSQL recommendation/evidence history. Configured AI
  or market services may be involved; no separate pricing daemon is required.
- Status: implemented, bounded recommendation/history/idempotency acceptance.
  Test `test_apex_pricing_demand_context.py` and native recommendation tests;
  cover uncovered products, currencies, freshness and guarded application.

## AI workflows

### Assistant and knowledge base

At `/ai-advisor`, customers upload business policies and ask cited questions.
Uploaded files are stored/indexed into tenant-scoped document chunks; retrieval
combines available business data, summaries and document evidence. All-history
sales questions use the historical invoice context rather than silently
substituting a 90-day summary. Chat history and citation references persist.

- Code: `knowledge-base/`; `rag.py`; `backend/src/ai/rag/`; MinIO documents,
  PostgreSQL metadata/chunks/messages and optional vector search. Indexing runs
  through existing API/pipeline paths; no dedicated RAG worker is mandatory.
- Status: implemented, bounded real English/Arabic cited-answer acceptance.
  Groq needs credentials **and approved cost schedules**, valid rights and AI
  Credits. Semantic embeddings/reranking need optional libraries/weights;
  keyword fallback remains usable where supported. Test retrieval scope,
  follow-ups, citations, history and metering separately. See
  [provider setup](INTEGRATIONS.md#ai-and-market-providers).

### Marketing copy and images

At `/marketing`, customers choose product facts and a creative brief, generate
drafts, review assets and reopen saved campaigns. Factual assertions are reviewed
against supplied sources; unsupported origin/certification/medical claims are
repaired or rejected. Creative themes are not proof of product origin.

- Code: `marketing/`; `marketing.py`; `backend/src/ai/marketing/`;
  PostgreSQL campaigns/image jobs and MinIO assets; `images` worker polls jobs.
  Text/image providers, reference inputs and optional background-removal models
  have distinct prerequisites and accounting paths.
- Status: implemented, bounded real copy/image acceptance. A generic AI image
  is illustrative, not verified product photography. Publishing, bulk workflows
  and reference-photo fidelity are not fully accepted. Test
  `test_marketing_content_generator.py`, image-job persistence, grounding failure
  and credit settlement; only explicitly authorized tests may invoke providers.

## Smart alerts and notifications

Customers see stock/forecast alerts and manage notification preferences. Alerts
need actual stock or derived evidence; delivery needs a configured email channel.
The API starts its digest scheduler; there is no separate notification worker
in the eight-process inventory.

- Code: `alerts/`, `settings/`; `alerts.py`, `notifications.py`;
  `backend/src/ai/notification_digest.py`, notification preferences/delivery state.
- Status: implemented, partially accepted; full scheduled delivery and
  acknowledgement lifecycle remain unverified. Test preferences, authorization,
  deduplication and one captured Mailpit digest on disposable records.

## Billing and subscriptions

At `/billing`, customers inspect plans, trial boundaries, usage and Data/AI
Credits. Python owns entitlements and accounting; signed Stripe events supply
payment evidence. Checkout creation or a redirect is not paid access, and a
plan change must not reset an existing trial or Credits.

- Code: `billing/`, `onboarding/`; `billing.py`;
  `backend/src/ai/billing/`, restricted billing roles and financial tables.
  API billing maintenance reconciles stale reservations; Stripe TEST is optional.
- Status: implemented with scoped security/accounting regressions and historical
  lifecycle evidence, not certification of every payment scenario. Run the
  isolated billing tests in [Testing](TESTING.md); see
  [billing rules](SUBSCRIPTIONS_AND_CREDITS.md). Never use real payments as a smoke test.

## Shopify and WooCommerce

Customers connect their own authorized test store from `/connect-data` and
inspect verified source state and synchronization. Provider records first enter
durable staging; canonical stock/invoice promotion has separate review and
policy gates. A ready connector worker does not mean a store is connected.

- Code: `data-connections/`; `onboarding.py`, `provider_webhooks.py`;
  `backend/src/market_scraper/shopify_oauth.py`, `woocommerce.py`,
  `provider_store_sync.py`, credential vault, source jobs/checkpoints and
  provider identity/inventory provenance tables; `connectors` worker.
- Status: implemented adapters/lifecycle, provider-dependent and live-merchant
  acceptance unverified. Test native source isolation, checkpoints, signature
  validation and staged mapping with fixtures first. Follow
  [store setup](INTEGRATIONS.md#shopify-and-woocommerce) for real sandbox access.

## Reports and exports

At `/reports`, customers filter/read sales and financial summaries and download
CSV, JSON or PDF through supported export paths. Accurate totals require dated
invoice lines, quantities, currency and costs. Viewing a report and consuming an
export allowance are different actions; exact retries must not double-charge.

- Code: `reports/`; `reports.py`; PostgreSQL invoices/items/usage receipts;
  normal request path, no report worker.
- Status: implemented; full-history CSV/JSON totals and browser CSV download
  accepted in a bounded fixture. PDF, Arabic exports and every date/pagination
  control need further acceptance. Test `test_reports.py` and native financial
  summary/report tests with verified user fixtures and exact Decimal totals.

## Platform administration

Authorized Platform Owners/staff manage platform directories, plan metadata,
pricing configuration and audit views under `/platform`. This security scope is
separate from managing a customer workspace; hiding a page is insufficient authorization.

- Code: `platform-admin/`, `platform/`; `platform.py`, `operator.py`;
  `backend/src/ai/platform/`, guarded database commands and platform audit tables.
- Status: implemented, bounded role/security/UI evidence; full operator matrix
  and all commercial actions remain outside blanket acceptance. Test
  `backend/tests/billing/test_platform_owner_catalog_mutations_db.py` on its
  isolated fixtures and verify Tenant Owners/staff cannot invoke owner commands.

## Changing a feature

Trace page → feature API adapter → Python router → domain service → database
or worker before editing. Find existing tests beside that domain, use disposable
records, verify observable business results and tenant denial, then check English
desktop and Arabic mobile/RTL. Never treat HTTP 200, a model configuration flag
or a worker heartbeat as proof of factual correctness or provider success.
