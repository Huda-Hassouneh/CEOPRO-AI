-- Closes PENDING_ACTIONS.md #25: RLS as originally deployed provides zero
-- protection, not because a policy is missing or misconfigured, but because
-- the application's own configured database role (POSTGRES_USER=ceopro_admin
-- in docker-compose.yml) is the bootstrap superuser that the official
-- Postgres image creates. Superusers unconditionally bypass Row-Level
-- Security regardless of FORCE ROW LEVEL SECURITY - confirmed empirically
-- against the real docker-compose.yml configuration (see AI_PROGRESS.md,
-- 2026-08-08 entries). FORCE alone, without also moving the app off the
-- superuser role, would have no effect at all.
--
-- This migration does the two remaining pieces:
--   1. A genuinely separate, non-superuser role for day-to-day app traffic.
--      ceopro_admin remains the bootstrap/migration-running role.
--   2. FORCE ROW LEVEL SECURITY on every table init_schema.sql already
--      enables RLS on, so that role (or any other non-superuser role,
--      including the table owner) is actually restricted by the existing
--      tenant_isolation_*_policy policies instead of bypassing them.
--
-- Deliberately NOT done here (needs a decision, not a migration):
--   - No password is set for ceopro_app - CREATE ROLE ... LOGIN with no
--     password means it cannot authenticate until one is set out-of-band
--     (ALTER ROLE ceopro_app WITH PASSWORD '...'), the same way every other
--     credential in this repo is meant to be supplied via environment, never
--     committed. See .env.example's new CEOPRO_APP_PASSWORD entry.
--   - docker-compose.yml is not changed to make any service actually connect
--     as ceopro_app - no "app"/"backend" service exists yet for it to
--     configure (confirmed: docker-compose.yml defines no such service).
--     src/ai/forecasting/consumer.py (the one place in src/ai/ that opens
--     its own DB connection) has been updated separately to use this role
--     via src/ai/db.py, gated behind a new CEOPRO_APP_DATABASE_URL env var
--     falling back to DATABASE_URL so existing deployments/tests are
--     unaffected until that variable is actually set.
--   - campaigns/news_record/social_mention/extracted_entity (added the same
--     day as the original, still-broken RLS migration this supersedes) are
--     not covered - they're not RLS-enabled in init_schema.sql at all yet,
--     and per PENDING_ACTIONS.md #22 nothing applies this migrations/
--     folder to a database automatically regardless.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        CREATE ROLE ceopro_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

-- current_database() rather than a hardcoded name - the real deployment uses
-- ceopro_platform (per .env.example), but this migration is also what this
-- session's own tests apply against disposable, differently-named databases.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO ceopro_app', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO ceopro_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ceopro_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ceopro_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ceopro_app;

ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE products FORCE ROW LEVEL SECURITY;
ALTER TABLE product_price_history FORCE ROW LEVEL SECURITY;
ALTER TABLE transactions FORCE ROW LEVEL SECURITY;
ALTER TABLE inventory FORCE ROW LEVEL SECURITY;
ALTER TABLE competitors FORCE ROW LEVEL SECURITY;
ALTER TABLE competitor_prices FORCE ROW LEVEL SECURITY;
ALTER TABLE reviews FORCE ROW LEVEL SECURITY;
ALTER TABLE sentiment_results FORCE ROW LEVEL SECURITY;
ALTER TABLE demand_forecasts FORCE ROW LEVEL SECURITY;
ALTER TABLE evidence_records FORCE ROW LEVEL SECURITY;
ALTER TABLE recommendation_outcomes FORCE ROW LEVEL SECURITY;
ALTER TABLE rag_documents_metadata FORCE ROW LEVEL SECURITY;
ALTER TABLE rag_document_chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE import_staging_rows FORCE ROW LEVEL SECURITY;
ALTER TABLE data_sources FORCE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
