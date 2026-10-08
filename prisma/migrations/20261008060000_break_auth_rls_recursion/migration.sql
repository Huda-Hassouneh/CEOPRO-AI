-- The baseline users SELECT policy checks tenant_users. Therefore the
-- tenant_users login policy must not query users, or PostgreSQL detects
-- recursive RLS evaluation while looking up a user by email.
-- Apply these policies to both the Render runtime role and ceopro_app.

DROP POLICY IF EXISTS users_auth_email_lookup ON public.users;
CREATE POLICY users_auth_email_lookup
  ON public.users
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user
  USING (
    lower(email) = lower(NULLIF(current_setting('app.auth_email', true), ''))
  );

DROP POLICY IF EXISTS tenant_users_auth_login_lookup ON public.tenant_users;
CREATE POLICY tenant_users_auth_login_lookup
  ON public.tenant_users
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user
  USING (
    user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    AND removed_at IS NULL
    AND platform_status = 'active'
  );

DROP POLICY IF EXISTS companies_auth_login_lookup ON public.companies;
CREATE POLICY companies_auth_login_lookup
  ON public.companies
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app, ceopro_ai_prod_user
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
    )
  );

GRANT EXECUTE ON FUNCTION public.auth_login_memberships(uuid)
  TO ceopro_app, ceopro_ai_prod_user;
