-- Break the tenant_users -> RLS policy -> get_current_tenant() recursion.
-- Membership authorization must be checked by the authenticated application
-- middleware before it runs a tenant-scoped transaction.
CREATE OR REPLACE FUNCTION public.get_current_tenant()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path TO public, pg_temp
AS $$
  SELECT CASE
    WHEN NULLIF(current_setting('app.current_user_id', true), '') IS NULL
      THEN NULL::uuid
    ELSE NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
  END;
$$;
