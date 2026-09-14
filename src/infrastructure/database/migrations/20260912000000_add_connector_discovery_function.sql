-- CEOPRO AI - Cross-tenant connector discovery for the new scheduled
-- connector worker (src/market_scraper/connector_worker.py).
--
-- data_sources has RLS FORCE'd (Final_schema.sql) - even the ceopro_app
-- role that owns the row cannot see across tenants without either the
-- superuser connection (deliberately never used by market_scraper's own
-- services - see docker-compose.yml's own comment on SCRAPER_DATABASE_URL)
-- or a SECURITY DEFINER function explicitly granted to it, the exact
-- precedent already established by recover_stale_market_jobs()/
-- enforce_market_retention() (20260829030000_harden_market_collection_
-- production.sql) for this identical "restricted role needs one
-- deliberate cross-tenant admin operation" situation.
--
-- Deliberately broad, not a precise "is this row actually due right now"
-- filter: returns every tenant with ANY active, ALLOWED row for the given
-- collector_key(s), full stop. The authoritative due-or-not decision per
-- source still lives entirely in Python (connector_sync.py::
-- is_due_for_sync(), reused identically by api_connector_sync.py) - this
-- function only avoids the worker needing to iterate every tenant in the
-- system on every loop tick when most have no connector configured at
-- all. A tenant with a connector that isn't actually due yet still costs
-- one wasted connection open/close per loop tick, never a missed sync -
-- correctness is intentionally kept in one place (Python), not
-- duplicated as time-math inside SQL.

CREATE OR REPLACE FUNCTION list_tenants_with_active_connectors(collector_keys TEXT[])
RETURNS TABLE(tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT ds.tenant_id
    FROM data_sources ds
    WHERE ds.collector_key = ANY(collector_keys)
      AND ds.is_active = TRUE
      AND ds.policy_status = 'ALLOWED';
$$;

REVOKE ALL ON FUNCTION list_tenants_with_active_connectors(TEXT[]) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION list_tenants_with_active_connectors(TEXT[]) TO ceopro_app;
    END IF;
END $$;
