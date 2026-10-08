-- Grants the AI service needs on the shared Render database, beyond what the
-- AI team user already has (SELECT/INSERT/UPDATE on 16 tables, INSERT on
-- audit_logs). For the database owner to review and apply - NOT a migration,
-- and never run by scripts/apply_migrations.py.
--
--   psql "<owner connection>" -v ai_user=<AI team user> -f render_ai_user_grants_request.sql
--
-- Row-level security still applies to every table below. Grouped by feature
-- so each block can be granted or left out on its own. Tables created by the
-- seven AI-only migrations (scraping_cost_ledger) must exist first - see
-- DATABASE_SETUP.md.

-- Shared: nearly every AI feature reads the tenant's company and products.
GRANT SELECT ON public.companies, public.products TO :"ai_user";

-- Staged imports: import_staging_rows has a BIGSERIAL key.
GRANT USAGE ON SEQUENCE public.import_staging_rows_staging_row_id_seq TO :"ai_user";

-- RAG: re-indexing a document replaces its chunks; summaries read sales and forecasts.
GRANT DELETE ON public.rag_document_chunks TO :"ai_user";
GRANT SELECT ON public.invoices, public.invoice_items, public.demand_forecasts TO :"ai_user";

-- Dashboard, insights and forecasting.
GRANT SELECT ON public.inventory, public.transactions TO :"ai_user";
GRANT INSERT ON public.demand_forecasts, public.model_versions TO :"ai_user";

-- Pricing.
GRANT SELECT ON public.currency_rates TO :"ai_user";
GRANT INSERT ON public.recommendation_outcomes TO :"ai_user";

-- Competitor discovery: saves the company's detected location / search scope.
GRANT UPDATE ON public.companies TO :"ai_user";

-- Market collection: search cache, quota, cost ledger, alerts.
GRANT SELECT, INSERT, UPDATE ON public.web_search_cache, public.search_quota_usage TO :"ai_user";
GRANT SELECT, INSERT ON public.scraping_cost_ledger, public.market_alert_events TO :"ai_user";
GRANT SELECT ON public.market_alert_rules TO :"ai_user";

-- Extraction: entity records, and promoting validated rows into the
-- tenant's products and sales.
GRANT INSERT ON public.extracted_entity, public.products, public.transactions TO :"ai_user";
GRANT SELECT, UPDATE ON public.news_record, public.social_mention TO :"ai_user";

-- Quick sale (POST /sales).
GRANT INSERT ON public.invoices, public.invoice_items TO :"ai_user";
