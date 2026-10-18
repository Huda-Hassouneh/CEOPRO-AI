-- Keep forced RLS enabled and expose only the authenticated account's active
-- memberships and their active companies during login. These policies use
-- the same transaction-local identity context the API sets after locating
-- the email-matched user. No elevated database role is required.

-- The earlier login migration introduced broader versions of these policies.
-- Recreate them here with the email-to-user check included.
DROP POLICY IF EXISTS tenant_users_auth_login_lookup ON public.tenant_users;
CREATE POLICY tenant_users_auth_login_lookup
  ON public.tenant_users
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app
  USING (
    user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    AND removed_at IS NULL
    AND platform_status = 'active'
    AND EXISTS (
      SELECT 1
      FROM public.users AS login_user
      WHERE login_user.user_id = tenant_users.user_id
        AND lower(login_user.email) =
          lower(NULLIF(current_setting('app.auth_email', true), ''))
    )
  );

DROP POLICY IF EXISTS companies_auth_login_lookup ON public.companies;
CREATE POLICY companies_auth_login_lookup
  ON public.companies
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app
  USING (
    deleted_at IS NULL
    AND platform_status = 'active'
    AND EXISTS (
      SELECT 1
      FROM public.tenant_users AS login_membership
      WHERE login_membership.tenant_id = companies.tenant_id
        AND login_membership.user_id =
          NULLIF(current_setting('app.current_user_id', true), '')::uuid
        AND login_membership.removed_at IS NULL
        AND login_membership.platform_status = 'active'
        AND EXISTS (
          SELECT 1
          FROM public.users AS login_user
          WHERE login_user.user_id = login_membership.user_id
            AND lower(login_user.email) =
              lower(NULLIF(current_setting('app.auth_email', true), ''))
        )
    )
  );

CREATE OR REPLACE FUNCTION public.auth_login_memberships(p_user_id uuid)
RETURNS TABLE (
  tenant_id uuid,
  role_key text,
  business_type text,
  business_name text,
  country_code text,
  primary_currency text
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $function$
  SELECT
    tu.tenant_id,
    tu.role_key::text,
    c.business_type::text,
    c.business_name::text,
    c.country_code::text,
    c.primary_currency::text
  FROM public.tenant_users AS tu
  JOIN public.companies AS c ON c.tenant_id = tu.tenant_id
  WHERE tu.user_id = p_user_id
    AND p_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    AND EXISTS (
      SELECT 1
      FROM public.users AS u
      WHERE u.user_id = p_user_id
        AND lower(u.email) = lower(NULLIF(current_setting('app.auth_email', true), ''))
    )
    AND tu.removed_at IS NULL
    AND tu.platform_status = 'active'
    AND c.deleted_at IS NULL
    AND c.platform_status = 'active'
  ORDER BY tu.joined_at ASC NULLS LAST;
$function$;

REVOKE ALL ON FUNCTION public.auth_login_memberships(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.auth_login_memberships(uuid) TO ceopro_app;
