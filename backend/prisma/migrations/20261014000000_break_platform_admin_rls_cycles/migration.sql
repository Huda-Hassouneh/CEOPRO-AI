-- Repair the remaining policy expansion cycles without changing auth/tenant policies.
-- users -> tenant_users -> companies -> users, and tenant_users <-> companies.
-- The read-only NOLOGIN role already has dedicated, nonrecursive SELECT policies
-- on companies and tenant_users. Never grant that role to application accounts.
BEGIN;

DO $guard$
DECLARE runtime_role text;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles
    WHERE rolname = 'ceopro_platform_overview_reader'
      AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls
      AND NOT rolcreaterole AND NOT rolcreatedb AND NOT rolreplication AND NOT rolinherit
  ) THEN
    RAISE EXCEPTION 'Expected the restricted platform overview reader role';
  END IF;
  FOREACH runtime_role IN ARRAY ARRAY['ceopro_app', 'ceopro_ai_prod_user', 'ceopro_ai_test_user'] LOOP
    IF pg_catalog.pg_has_role(runtime_role, 'ceopro_platform_overview_reader', 'MEMBER')
      OR pg_catalog.pg_has_role('ceopro_platform_overview_reader', runtime_role, 'MEMBER') THEN
      RAISE EXCEPTION 'Runtime role % and the platform reader must not inherit each other', runtime_role;
    END IF;
  END LOOP;
  EXECUTE pg_catalog.format('GRANT ceopro_platform_overview_reader TO %I', current_user);
END;
$guard$;

GRANT USAGE, CREATE ON SCHEMA public TO ceopro_platform_overview_reader;

CREATE OR REPLACE FUNCTION public.platform_admin_can_read_customer_tenant(p_tenant_id uuid)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $function$
BEGIN
  IF public.is_verified_platform_admin_context() IS NOT TRUE THEN RETURN false; END IF;
  RETURN EXISTS (
    SELECT 1 FROM public.companies AS customer_company
    WHERE customer_company.tenant_id = p_tenant_id
      AND customer_company.business_type IS DISTINCT FROM 'platform'
      AND customer_company.deleted_at IS NULL
  );
END;
$function$;

CREATE OR REPLACE FUNCTION public.platform_admin_can_read_customer_user(p_user_id uuid)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $function$
BEGIN
  IF public.is_verified_platform_admin_context() IS NOT TRUE THEN RETURN false; END IF;
  RETURN EXISTS (
    SELECT 1 FROM public.tenant_users AS customer_membership
    JOIN public.companies AS customer_company
      ON customer_company.tenant_id = customer_membership.tenant_id
    WHERE customer_membership.user_id = p_user_id
      AND customer_membership.removed_at IS NULL
      AND customer_company.business_type IS DISTINCT FROM 'platform'
      AND customer_company.deleted_at IS NULL
  );
END;
$function$;

ALTER FUNCTION public.platform_admin_can_read_customer_tenant(uuid)
  OWNER TO ceopro_platform_overview_reader;
ALTER FUNCTION public.platform_admin_can_read_customer_user(uuid)
  OWNER TO ceopro_platform_overview_reader;

SET ROLE ceopro_platform_overview_reader;
REVOKE ALL ON FUNCTION public.platform_admin_can_read_customer_tenant(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_admin_can_read_customer_user(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.platform_admin_can_read_customer_tenant(uuid),
  public.platform_admin_can_read_customer_user(uuid)
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user;
RESET ROLE;

DROP POLICY IF EXISTS platform_admin_customer_memberships_read ON public.tenant_users;
CREATE POLICY platform_admin_customer_memberships_read
  ON public.tenant_users AS PERMISSIVE FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (removed_at IS NULL AND public.platform_admin_can_read_customer_tenant(tenant_id));

DROP POLICY IF EXISTS platform_admin_customer_users_read ON public.users;
CREATE POLICY platform_admin_customer_users_read
  ON public.users AS PERMISSIVE FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (public.platform_admin_can_read_customer_user(user_id));

REVOKE CREATE ON SCHEMA public FROM ceopro_platform_overview_reader;
DO $cleanup$
BEGIN
  EXECUTE pg_catalog.format('REVOKE ceopro_platform_overview_reader FROM %I', current_user);
END;
$cleanup$;
COMMIT;
