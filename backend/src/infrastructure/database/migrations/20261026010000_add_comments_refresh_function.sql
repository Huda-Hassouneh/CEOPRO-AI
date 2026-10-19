-- Cross-tenant discovery for the scheduled comments refresh (market_scraper/enrichment_worker.py). Same pattern
-- as list_tenants_with_due_enrichment(): competitor_enrichment is FORCE ROW LEVEL SECURITY, so the restricted app
-- role cannot list tenants itself; this SECURITY DEFINER function returns ONLY tenant ids and the real work then
-- runs on an RLS-scoped connection.
--
-- A tenant is listed when a tracked competitor's COMMENTS were last attempted before the cutoff and either
-- succeeded, or still has stored YouTube comments (a later failed attempt must not stop the refresh while there
-- is something worth keeping fresh). Comments are kept 30 days, so a weekly refresh keeps them continuous.
CREATE OR REPLACE FUNCTION list_tenants_with_due_comments_refresh(max_age_days INT)
RETURNS TABLE(tenant_id UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT DISTINCT ce.tenant_id
    FROM competitor_enrichment ce
    JOIN tenant_competitors tc ON tc.tenant_id = ce.tenant_id AND tc.global_competitor_id = ce.global_competitor_id
    WHERE ce.facet = 'COMMENTS' AND tc.is_tracked = TRUE
      AND ce.last_attempt_at < NOW() - make_interval(days => max_age_days)
      AND (ce.status IN ('SUCCEEDED', 'PARTIAL')
           OR EXISTS (SELECT 1 FROM reviews r WHERE r.tenant_id = ce.tenant_id AND r.competitor_id = ce.global_competitor_id
                      AND r.subject_type = 'COMPETITOR' AND r.source_platform = 'YouTube'));
$$;

REVOKE ALL ON FUNCTION list_tenants_with_due_comments_refresh(INT) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION list_tenants_with_due_comments_refresh(INT) TO ceopro_app;
    END IF;
END $$;
