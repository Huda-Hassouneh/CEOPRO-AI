-- The Render API connects as ceopro_ai_prod_user, while local deployments
-- may connect as ceopro_app. Allow both runtime roles to use the same
-- email/user-context-scoped login policies. Neither role receives BYPASSRLS.

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
        AND EXISTS (
          SELECT 1
          FROM public.users AS login_user
          WHERE login_user.user_id = login_membership.user_id
            AND lower(login_user.email) =
              lower(NULLIF(current_setting('app.auth_email', true), ''))
        )
    )
  );

GRANT EXECUTE ON FUNCTION public.auth_login_memberships(uuid)
  TO ceopro_ai_prod_user;
