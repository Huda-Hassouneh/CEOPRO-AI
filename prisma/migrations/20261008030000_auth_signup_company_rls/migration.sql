-- Signup creates a company before its first tenant membership exists.
-- Prisma uses INSERT ... RETURNING for create(), so the new company must be
-- visible to the same transaction by its pre-generated tenant/user context.
DROP POLICY IF EXISTS companies_auth_signup_insert ON public.companies;
CREATE POLICY companies_auth_signup_insert
  ON public.companies
  FOR INSERT
  TO ceopro_app
  WITH CHECK (
    get_current_tenant() IS NULL
    OR tenant_id = get_current_tenant()
  );

DROP POLICY IF EXISTS companies_auth_signup_returning ON public.companies;
CREATE POLICY companies_auth_signup_returning
  ON public.companies
  FOR SELECT
  TO ceopro_app
  USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    AND EXISTS (
      SELECT 1
      FROM public.users AS signup_user
      WHERE signup_user.user_id =
        NULLIF(current_setting('app.current_user_id', true), '')::uuid
    )
  );
