-- Platform overview needs cross-tenant aggregate counts, while ordinary
-- company and membership queries must remain tenant-isolated by RLS.
-- Keep this as a narrowly-scoped, read-only function instead of using the
-- bootstrap database identity. Render-managed PostgreSQL does not provide
-- superuser access, so this role deliberately does not use BYPASSRLS. Its
-- only cross-tenant access is the two explicit SELECT policies below.
DO $$
DECLARE
  member_name text;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles
    WHERE rolname = 'ceopro_platform_overview_reader'
  ) THEN
    CREATE ROLE ceopro_platform_overview_reader
      WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
      NOBYPASSRLS NOREPLICATION;
  ELSE
    ALTER ROLE ceopro_platform_overview_reader
      WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
      NOBYPASSRLS NOREPLICATION;
  END IF;

  -- Remove stale grants left by earlier attempts or manual setup. Keep only
  -- the current migration identity temporarily, because it may need that
  -- membership to replace/transfer ownership of the function on a retry.
  FOR member_name IN
    SELECT member_role.rolname
    FROM pg_catalog.pg_auth_members AS membership
    JOIN pg_catalog.pg_roles AS granted_role
      ON granted_role.oid = membership.roleid
    JOIN pg_catalog.pg_roles AS member_role
      ON member_role.oid = membership.member
    WHERE granted_role.rolname = 'ceopro_platform_overview_reader'
      AND member_role.rolname <> current_user
  LOOP
    EXECUTE format(
      'REVOKE ceopro_platform_overview_reader FROM %I CASCADE',
      member_name
    );
  END LOOP;
END;
$$;

GRANT USAGE, CREATE ON SCHEMA public TO ceopro_platform_overview_reader;
GRANT SELECT ON public.companies, public.tenant_users
  TO ceopro_platform_overview_reader;

-- FORCE RLS remains enabled. Only this NOLOGIN role receives a permissive
-- cross-tenant read policy on these two tables; it has no write policy/grant.
DROP POLICY IF EXISTS platform_overview_reader_companies
  ON public.companies;
CREATE POLICY platform_overview_reader_companies
  ON public.companies AS PERMISSIVE FOR SELECT
  TO ceopro_platform_overview_reader
  USING (true);

DROP POLICY IF EXISTS platform_overview_reader_tenant_users
  ON public.tenant_users;
CREATE POLICY platform_overview_reader_tenant_users
  ON public.tenant_users AS PERMISSIVE FOR SELECT
  TO ceopro_platform_overview_reader
  USING (true);

CREATE OR REPLACE FUNCTION public.get_platform_admin_overview_counts(
  p_platform_tenant_id uuid,
  p_platform_user_id uuid,
  p_from timestamptz DEFAULT NULL,
  p_to timestamptz DEFAULT NULL
)
RETURNS TABLE (companies_count bigint, users_count bigint)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_platform_tenant_id IS NULL OR p_platform_user_id IS NULL THEN
    RAISE EXCEPTION 'Platform tenant and user are required.'
      USING ERRCODE = '42501';
  END IF;

  IF (p_from IS NULL) <> (p_to IS NULL) OR (p_from IS NOT NULL AND p_from >= p_to) THEN
    RAISE EXCEPTION 'A valid pair of overview date bounds is required.'
      USING ERRCODE = '22023';
  END IF;

  -- Re-check the caller's identity at the database boundary. The API route
  -- separately verifies platform.overview.read before it calls this function.
  IF NOT EXISTS (
    SELECT 1
    FROM public.companies AS platform_company
    JOIN public.tenant_users AS platform_membership
      ON platform_membership.tenant_id = platform_company.tenant_id
    WHERE platform_company.tenant_id = p_platform_tenant_id
      AND platform_company.business_type = 'platform'
      AND platform_company.deleted_at IS NULL
      AND platform_company.platform_status = 'active'
      AND platform_membership.user_id = p_platform_user_id
      AND platform_membership.role_key IN ('owner', 'admin')
      AND platform_membership.removed_at IS NULL
      AND platform_membership.platform_status = 'active'
  ) THEN
    RAISE EXCEPTION 'Active platform membership is required for overview counts.'
      USING ERRCODE = '42501';
  END IF;

  RETURN QUERY
  SELECT
    (
      SELECT count(*)
      FROM public.companies AS customer_company
      WHERE customer_company.tenant_id <> p_platform_tenant_id
        AND customer_company.business_type IS DISTINCT FROM 'platform'
        AND customer_company.deleted_at IS NULL
        AND (p_from IS NULL OR customer_company.created_at >= p_from)
        AND (p_to IS NULL OR customer_company.created_at < p_to)
    )::bigint,
    (
      SELECT count(*)
      FROM public.tenant_users AS customer_membership
      JOIN public.companies AS customer_company
        ON customer_company.tenant_id = customer_membership.tenant_id
      WHERE customer_membership.tenant_id <> p_platform_tenant_id
        AND customer_company.business_type IS DISTINCT FROM 'platform'
        AND customer_company.deleted_at IS NULL
        AND customer_membership.removed_at IS NULL
        AND (p_from IS NULL OR customer_membership.joined_at >= p_from)
        AND (p_to IS NULL OR customer_membership.joined_at < p_to)
    )::bigint;
END;
$$;

REVOKE ALL ON FUNCTION public.get_platform_admin_overview_counts(
  uuid, uuid, timestamptz, timestamptz
) FROM PUBLIC;

-- ALTER FUNCTION OWNER requires membership in the target role. Grant ordinary
-- membership only to the migration identity for the ownership transfer, then
-- remove it. ADMIN OPTION is not needed and is rejected by some managed PG
-- providers when the migration identity created the role.
-- The function owner itself remains NOLOGIN and is not granted to app roles.
DO $$
BEGIN
  EXECUTE format(
    'GRANT ceopro_platform_overview_reader TO %I',
    current_user
  );
END;
$$;

ALTER FUNCTION public.get_platform_admin_overview_counts(
  uuid, uuid, timestamptz, timestamptz
) OWNER TO ceopro_platform_overview_reader;

-- Grant execution after ownership transfer. Otherwise a runtime role that was
-- also the original function owner may lose its implicit owner access without
-- retaining an explicit EXECUTE ACL entry.
SET ROLE ceopro_platform_overview_reader;
GRANT EXECUTE ON FUNCTION public.get_platform_admin_overview_counts(
  uuid, uuid, timestamptz, timestamptz
) TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user;

COMMENT ON FUNCTION public.get_platform_admin_overview_counts(
  uuid, uuid, timestamptz, timestamptz
) IS 'Returns customer company and non-removed membership counts for a verified platform owner/admin; excludes the platform company and respects optional half-open time bounds.';
RESET ROLE;

-- PostgreSQL requires the new function owner to have CREATE on its schema at
-- the moment ownership changes. Remove that temporary schema privilege only
-- after the transfer has succeeded.
REVOKE CREATE ON SCHEMA public FROM ceopro_platform_overview_reader;

DO $$
BEGIN
  EXECUTE format(
    'REVOKE ceopro_platform_overview_reader FROM %I',
    current_user
  );
END;
$$;
