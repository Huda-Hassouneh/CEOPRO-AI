-- CEOPRO AI - Fix background-worker connections always resolving NO
-- tenant context, so every RLS-protected read/write they attempt
-- silently returns zero rows on every tenant.
--
-- Root cause of Market Intelligence reading Total Competitors: 0 (and
-- every downstream metric/table on that page) despite a real, successful
-- product upload and a real discovery-requested event actually being
-- published: get_current_tenant() (last touched by
-- 20260827060000_fix_get_current_tenant_recursion.sql) requires
-- app.current_user_id to be an ACTIVE tenant_users member of
-- app.current_tenant_id before it resolves to anything but NULL - correct
-- and necessary for a real end-user session. But market_scraper/
-- data_access.py::get_tenant_connection() and src/ai/forecasting/
-- consumer.py's pooled connections were both DESIGNED (see backend/
-- .env.example's own comment on SCRAPER_ACTOR_USER_ID/
-- AI_SERVICE_ACTOR_USER_ID: "User/service-principal UUID that is an
-- active tenant member; required by RLS") to open as a fixed
-- service-principal UUID - the nil UUID, 00000000-0000-0000-0000-
-- 000000000000, both env vars' shared documented default - acting on
-- behalf of whichever tenant a background job is currently processing.
-- Nothing ever actually inserted a tenant_users row granting that UUID
-- membership in any tenant, so get_current_tenant() has always silently
-- returned NULL for every one of these connections, on every tenant,
-- since this design was introduced. Every RLS-protected read/write a
-- background worker ever attempted returned zero rows - discovery finds
-- "zero candidates" for a tenant with a real, freshly-uploaded product
-- (discover_domain_level_competitors_for_tenant even raised outright:
-- "tenant_id not found" - its own companies lookup came back empty),
-- forecasting sees "no products" - never surfacing as an error, since an
-- empty result is a perfectly valid outcome from the calling code's own
-- point of view. Reproduced directly by calling
-- market_scraper.discovery_worker.discover_for_tenant() against a real,
-- freshly-signed-up tenant with one real uploaded product.
--
-- The obvious-looking fix - INSERT a real tenant_users row for this UUID,
-- for every tenant - was deliberately rejected: routers/settings.py's
-- list_team_members()/the 'owner'-count check in invite_team_member(),
-- and any seat-limit check, all read tenant_users with no filter
-- excluding a system principal. A real membership row would show up as
-- a fake "team member" in every tenant's own Settings > Team page, be
-- removable there (silently re-breaking this fix), and would double-
-- count against the 'owner' role and any seat limit - a real regression
-- in an unrelated feature this task explicitly must not touch.
--
-- The correct fix is here, in get_current_tenant() itself: recognize
-- this one specific, hardcoded nil-UUID service principal as always a
-- valid actor for whichever tenant_id the connection's own transaction
-- already has SET LOCAL app.current_tenant_id to. It still takes exactly
-- one tenant's context per transaction (the same SET LOCAL mechanism
-- db_pool.py's pooling safety already depends on - see that module's own
-- docstring), so cross-tenant isolation between real tenants is
-- completely unaffected; this only removes the "and a REAL human is
-- still an active member" requirement for the one recognized system
-- identity background workers use, never for any real user_id. Keeps
-- the SECURITY DEFINER/search_path hardening the recursion-fix migration
-- added - this only adds one early-return branch to that same function,
-- nothing else about it changes.
CREATE OR REPLACE FUNCTION get_current_tenant()
RETURNS UUID AS $$
DECLARE
    tenant_str TEXT;
    user_str TEXT;
    tenant_uuid UUID;
    user_uuid UUID;
    service_actor_id CONSTANT UUID := '00000000-0000-0000-0000-000000000000';
BEGIN
    tenant_str := current_setting('app.current_tenant_id', true);
    IF tenant_str IS NULL OR tenant_str = '' THEN
        RETURN NULL;
    END IF;
    tenant_uuid := tenant_str::uuid;

    user_str := current_setting('app.current_user_id', true);
    IF user_str IS NULL OR user_str = '' THEN
        RETURN NULL;
    END IF;
    user_uuid := user_str::uuid;

    -- The fixed background-worker service principal - never a real login,
    -- never a tenant_users row - is trusted for whatever single tenant
    -- its own connection is already transaction-scoped to.
    IF user_uuid = service_actor_id THEN
        RETURN tenant_uuid;
    END IF;

    -- A tenant context is only valid if the current user is still an ACTIVE
    -- member of that tenant. This is what makes tenant_users.removed_at mean
    -- anything: without this check, revoking membership updated a timestamp
    -- that no policy ever read, and a removed user kept full access until
    -- their session expired.
    IF NOT EXISTS (
        SELECT 1 FROM tenant_users
        WHERE tenant_users.tenant_id = tenant_uuid
          AND tenant_users.user_id = user_uuid
          AND tenant_users.removed_at IS NULL
    ) THEN
        RETURN NULL;
    END IF;

    RETURN tenant_uuid;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp;
