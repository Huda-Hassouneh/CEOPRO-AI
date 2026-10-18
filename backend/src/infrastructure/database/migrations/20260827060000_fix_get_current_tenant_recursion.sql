-- CEOPRO AI - Fix infinite recursion in get_current_tenant() when invoked by
-- a non-superuser role.
--
-- get_current_tenant() is the function every RLS policy in Final_schema.sql
-- calls to compute the isolated tenant_id. Its own body queries tenant_users
-- ("... IF NOT EXISTS (SELECT 1 FROM tenant_users WHERE ...)") to confirm the
-- caller is still an active member of the claimed tenant. tenant_users is
-- itself RLS-protected (FORCE ROW LEVEL SECURITY, policy
-- "isolation_tenant_users ON tenant_users FOR ALL USING (tenant_id =
-- get_current_tenant())").
--
-- Final_schema.sql declared get_current_tenant() as a plain (SECURITY
-- INVOKER, the default) function. Under a non-superuser role that has no
-- BYPASSRLS - i.e. the actual, intended runtime identity once anything
-- connects as ceopro_app instead of the superuser ceopro_admin - evaluating
-- the function's internal SELECT against tenant_users re-triggers
-- tenant_users' own RLS policy, which calls get_current_tenant() again,
-- which queries tenant_users again, forever. Confirmed directly: with
-- app.current_tenant_id/app.current_user_id set and connected as ceopro_app,
-- any query against any RLS-protected table crashes with
-- "psycopg2.errors.StatementTooComplex: stack depth limit exceeded" instead
-- of returning the correctly-scoped rows. This was invisible throughout the
-- session because every verification so far connected as ceopro_admin (a
-- superuser, which bypasses RLS - and every policy call - entirely), so the
-- recursive path was never actually executed until a real non-superuser
-- role exercised it end-to-end.
--
-- Fix: mark the function SECURITY DEFINER, so its internal query against
-- tenant_users runs as the function's owner (whoever applies this migration,
-- i.e. ceopro_admin) rather than as the calling role - a superuser, which
-- bypasses tenant_users' RLS instead of re-entering it, breaking the cycle.
-- This is the standard, documented Postgres pattern for a helper function
-- that itself needs to read an RLS-protected table on behalf of a policy.
-- SET search_path pins name resolution so a SECURITY DEFINER function can't
-- be tricked by a caller-controlled search_path into resolving an
-- attacker-planted object instead of the real tenant_users/pg_catalog ones -
-- standard hardening for any SECURITY DEFINER function, not optional here.
CREATE OR REPLACE FUNCTION get_current_tenant()
RETURNS UUID AS $$
DECLARE
    tenant_str TEXT;
    user_str TEXT;
    tenant_uuid UUID;
    user_uuid UUID;
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
