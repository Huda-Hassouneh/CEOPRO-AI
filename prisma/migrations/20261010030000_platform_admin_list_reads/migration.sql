-- Allow authenticated platform owners/admins to read customer company and
-- membership rows in the owner portal. This does not grant BYPASSRLS and does
-- not change write policies. The current app context must identify an active
-- owner/admin membership in an active platform tenant.

GRANT USAGE, CREATE ON SCHEMA public TO ceopro_platform_overview_reader;

CREATE OR REPLACE FUNCTION public.is_verified_platform_admin_context()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  context_tenant_id uuid;
  context_user_id uuid;
BEGIN
  BEGIN
    context_tenant_id := NULLIF(
      current_setting('app.current_tenant_id', true), ''
    )::uuid;
    context_user_id := NULLIF(
      current_setting('app.current_user_id', true), ''
    )::uuid;
  EXCEPTION WHEN invalid_text_representation THEN
    RETURN false;
  END;

  IF context_tenant_id IS NULL OR context_user_id IS NULL THEN
    RETURN false;
  END IF;

  RETURN EXISTS (
    SELECT 1
    FROM public.companies AS platform_company
    JOIN public.tenant_users AS platform_membership
      ON platform_membership.tenant_id = platform_company.tenant_id
    WHERE platform_company.tenant_id = context_tenant_id
      AND platform_company.business_type = 'platform'
      AND platform_company.deleted_at IS NULL
      AND platform_company.platform_status = 'active'
      AND platform_membership.user_id = context_user_id
      AND platform_membership.role_key IN ('owner', 'admin')
      AND platform_membership.removed_at IS NULL
      AND platform_membership.platform_status = 'active'
  );
END;
$$;

-- Transfer this small verifier to the same NOLOGIN reader role used by the
-- overview-count function. Its existing SELECT policies let it verify the
-- platform membership without creating tenant_users RLS recursion.
DO $$
BEGIN
  EXECUTE format(
    'GRANT ceopro_platform_overview_reader TO %I',
    current_user
  );
END;
$$;

ALTER FUNCTION public.is_verified_platform_admin_context()
  OWNER TO ceopro_platform_overview_reader;

SET ROLE ceopro_platform_overview_reader;
REVOKE ALL ON FUNCTION public.is_verified_platform_admin_context() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_verified_platform_admin_context()
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user;
RESET ROLE;

-- A platform owner/admin may read customer companies. Their own platform
-- company remains available through the existing current-tenant policy.
DROP POLICY IF EXISTS platform_admin_customer_companies_read
  ON public.companies;
CREATE POLICY platform_admin_customer_companies_read
  ON public.companies
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (
    business_type IS DISTINCT FROM 'platform'
    AND deleted_at IS NULL
    AND public.is_verified_platform_admin_context()
  );

-- Limit the extra membership visibility to active customer tenants.
DROP POLICY IF EXISTS platform_admin_customer_memberships_read
  ON public.tenant_users;
CREATE POLICY platform_admin_customer_memberships_read
  ON public.tenant_users
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (
    removed_at IS NULL
    AND public.is_verified_platform_admin_context()
    AND EXISTS (
      SELECT 1
      FROM public.companies AS customer_company
      WHERE customer_company.tenant_id = tenant_users.tenant_id
        AND customer_company.business_type IS DISTINCT FROM 'platform'
        AND customer_company.deleted_at IS NULL
    )
  );

-- Prisma includes the related users row for each visible tenant membership.
-- Restrict this extra visibility to users with an active customer membership.
DROP POLICY IF EXISTS platform_admin_customer_users_read
  ON public.users;
CREATE POLICY platform_admin_customer_users_read
  ON public.users
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (
    public.is_verified_platform_admin_context()
    AND EXISTS (
      SELECT 1
      FROM public.tenant_users AS customer_membership
      JOIN public.companies AS customer_company
        ON customer_company.tenant_id = customer_membership.tenant_id
      WHERE customer_membership.user_id = users.user_id
        AND customer_membership.removed_at IS NULL
        AND customer_company.business_type IS DISTINCT FROM 'platform'
        AND customer_company.deleted_at IS NULL
    )
  );

-- The Companies list includes per-company product, competitor, and document
-- counts. Add read-only platform-admin policies for those related rows too.
DROP POLICY IF EXISTS platform_admin_customer_products_read
  ON public.products;
CREATE POLICY platform_admin_customer_products_read
  ON public.products
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (public.is_verified_platform_admin_context());

DROP POLICY IF EXISTS platform_admin_customer_competitors_read
  ON public.tenant_competitors;
CREATE POLICY platform_admin_customer_competitors_read
  ON public.tenant_competitors
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (public.is_verified_platform_admin_context());

DROP POLICY IF EXISTS platform_admin_customer_documents_read
  ON public.rag_documents_metadata;
CREATE POLICY platform_admin_customer_documents_read
  ON public.rag_documents_metadata
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user
  USING (public.is_verified_platform_admin_context());

REVOKE CREATE ON SCHEMA public FROM ceopro_platform_overview_reader;

DO $$
BEGIN
  EXECUTE format(
    'REVOKE ceopro_platform_overview_reader FROM %I',
    current_user
  );
END;
$$;
