-- Cross-tenant discovery for the scheduled competitor-enrichment sweep
-- (src/market_scraper/enrichment_worker.py). Same pattern and reasoning as
-- list_tenants_with_active_connectors() (20260912000000): tenant_competitors
-- and competitor_enrichment are FORCE ROW LEVEL SECURITY, so the restricted
-- ceopro_app role cannot list tenants itself; this SECURITY DEFINER function
-- returns ONLY tenant ids. The sweep then enqueues one tenant-scoped job per
-- id, and the real work runs on an RLS-scoped connection.
--
-- Deliberately broad (the per-competitor decision lives in Python/SQL of
-- enrich_tenant_competitors): a tenant is listed when it has a tracked
-- competitor whose PROFILE has never been attempted (covers competitors that
-- existed before enrichment shipped) or any facet whose scheduled retry is due.

CREATE OR REPLACE FUNCTION list_tenants_with_due_enrichment()
RETURNS TABLE(tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT tc.tenant_id
    FROM tenant_competitors tc
    WHERE tc.is_tracked = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM competitor_enrichment ce
          WHERE ce.tenant_id = tc.tenant_id AND ce.global_competitor_id = tc.global_competitor_id
            AND ce.facet = 'PROFILE'
      )
    UNION
    SELECT DISTINCT ce.tenant_id
    FROM competitor_enrichment ce
    WHERE ce.status IN ('FAILED', 'PARTIAL', 'PENDING')
      AND ce.next_retry_at IS NOT NULL AND ce.next_retry_at <= NOW();
$$;

REVOKE ALL ON FUNCTION list_tenants_with_due_enrichment() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION list_tenants_with_due_enrichment() TO ceopro_app;
    END IF;
END $$;
