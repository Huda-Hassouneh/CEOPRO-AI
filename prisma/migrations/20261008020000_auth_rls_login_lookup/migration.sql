-- Permit the application role to perform the minimum RLS-scoped lookups
-- needed by unauthenticated registration and login.
--
-- The email policy is only active when the backend sets app.auth_email in a
-- transaction. The membership policy is only active after the backend has
-- identified that user and sets app.current_user_id. Company visibility is
-- limited to active companies where that same user has an active membership.

DROP POLICY IF EXISTS users_auth_email_lookup ON public.users;
CREATE POLICY users_auth_email_lookup
  ON public.users
  AS PERMISSIVE
  FOR SELECT
  TO ceopro_app
  USING (
    lower(email) = lower(NULLIF(current_setting('app.auth_email', true), ''))
  );

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
    )
  );
