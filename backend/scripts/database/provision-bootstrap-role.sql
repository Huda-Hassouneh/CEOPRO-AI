\if :{?bootstrap_password}
\else
\echo 'Supply the bootstrap_password psql variable; no password is stored in this script.'
\quit 1
\endif

-- CEOPRO Bootstrap role provisioning for Render PostgreSQL.
-- Verified against backend(20261009-000747).zip and its bootstrap scripts.
-- Execute on the intended CEOPRO database as a role authorized to CREATE ROLE,
-- GRANT the listed privileges, and CREATE POLICY (normally the table owner).
--
-- IMPORTANT: Edit the password placeholder before executing; do not commit
-- a script containing a real password. Store the resulting connection URL
-- separately as BOOTSTRAP_DATABASE_URL. This role has NO BYPASSRLS.
--
-- In its current scripts, Prisma imports src/config/database.ts, which uses
-- DATABASE_URL. Change the bootstrap scripts to use a dedicated bootstrap
-- Prisma client or BOOTSTRAP_DATABASE_URL will not be used.


-- CEOPRO Render: narrowly scope the legacy, self-referencing onboarding INSERT policy.
-- Source: backend(20261009-000747).zip
--
-- Problem: baseline policy insert_tenant_users_onboarding applies TO PUBLIC and
-- has a subquery on tenant_users inside a policy ON tenant_users. Evaluating
-- this policy on an INSERT can raise PostgreSQL 42P17 (infinite recursion).
-- Bootstrap already has its own dedicated tenant_users policies, so exclude
-- ceopro_bootstrap from the legacy onboarding policy by restricting that policy
-- to the known application runtime roles. No table RLS state is changed.
--
-- Run as the owner of public.tenant_users or a sufficiently privileged role.
-- Run once on the intended Render CEOPRO database. Safe to run again.
-- The normal signup policy expression is *not* rewritten: it remains in place
-- for existing application roles; this is a focused bootstrap fix, not a
-- general rewrite of onboarding RLS.

BEGIN;

DO $ceopro_repair$
DECLARE
  app_roles_sql text;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ceopro_bootstrap'
  ) THEN
    RAISE EXCEPTION 'ceopro_bootstrap role is missing: run role provisioning first';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'tenant_users'
      AND policyname = 'insert_tenant_users_onboarding'
  ) THEN
    RAISE EXCEPTION 'Expected legacy onboarding policy is missing; inspect pg_policies before changing anything';
  END IF;

  -- Your latest migrations define these application identities. Only choose
  -- roles that actually exist in this database, to support different setups.
  SELECT string_agg(format('%I', rolname), ', ' ORDER BY rolname)
    INTO app_roles_sql
  FROM pg_catalog.pg_roles
  WHERE rolname IN (
    'ceopro_app',
    'ceopro_ai_prod_user',
    'ceopro_ai_test_user'
  );

  IF app_roles_sql IS NULL THEN
    RAISE EXCEPTION 'No known CEOPRO runtime roles found; refusing to change the onboarding policy';
  END IF;

  EXECUTE format(
    'ALTER POLICY insert_tenant_users_onboarding ON public.tenant_users TO %s',
    app_roles_sql
  );
END
$ceopro_repair$;

COMMIT;

-- Verify: the onboarding policy roles must NOT contain public or ceopro_bootstrap.
SELECT policyname, cmd, roles, with_check
FROM pg_catalog.pg_policies
WHERE schemaname = 'public'
  AND tablename = 'tenant_users'
  AND policyname IN (
    'insert_tenant_users_onboarding',
    'ceopro_bootstrap_tenant_users_allow',
    'ceopro_bootstrap_tenant_users_guard'
  )
ORDER BY policyname;

-- Separately: Connect using BOOTSTRAP_DATABASE_URL, then verify:
-- SELECT current_user;
-- It must return ceopro_bootstrap (NOT ceopro_app or ceopro_ai_prod_user).
-- The existing bootstrap scripts import src/config/database.js, which normally
-- reads DATABASE_URL, so setting BOOTSTRAP_DATABASE_URL alone is insufficient.

BEGIN;

-- Abort early if connected to a database lacking the required schema tables.
DO $preflight$
DECLARE
    missing_tables text;
BEGIN
    SELECT string_agg(t, ', ' ORDER BY t) INTO missing_tables
    FROM unnest(ARRAY[
      'users', 'companies', 'tenant_users', 'system_roles', 'features',
      'plans', 'plan_features', 'plan_price_versions', 'app_config',
      'subscription_usage', 'custom_plan_quote_features', 'vendor_rates'
    ]) AS t
    WHERE to_regclass(format('public.%I', t)) IS NULL;

    IF missing_tables IS NOT NULL THEN
       RAISE EXCEPTION 'CEOPRO bootstrap setup aborted: missing tables: %', missing_tables;
    END IF;
END
$preflight$;

DO $role_setup$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ceopro_bootstrap') THEN
        CREATE ROLE ceopro_bootstrap WITH LOGIN NOINHERIT
          NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'ceopro_bootstrap' AND (rolsuper OR rolbypassrls OR rolcreaterole)
    ) THEN
        RAISE EXCEPTION 'ceopro_bootstrap must not have SUPERUSER, BYPASSRLS, or CREATEROLE';
    END IF;
END
$role_setup$;

-- Replace the placeholder with a strong, newly generated password.
-- On rerun, this deliberately rotates the bootstrap password.
ALTER ROLE ceopro_bootstrap WITH LOGIN PASSWORD :'bootstrap_password';

-- Role creation is cluster-wide; CONNECT must be granted on the target DB.
DO $connection$
BEGIN
   EXECUTE format('GRANT CONNECT ON DATABASE %I TO ceopro_bootstrap', current_database());
END
$connection$;

GRANT USAGE ON SCHEMA public TO ceopro_bootstrap;

-- Tables actually written by current bootstrap:owner/admin/features/stripe/plans.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.users,
    public.companies,
    public.tenant_users,
    public.features,
    public.plans,
    public.plan_features,
    public.plan_price_versions,
    public.app_config,
    public.subscription_usage,
    public.custom_plan_quote_features,
    public.vendor_rates
TO ceopro_bootstrap;

-- Owner/admin role definitions should be controlled by migrations, not scripts.
GRANT SELECT ON TABLE public.system_roles TO ceopro_bootstrap;

-- No sequence grant currently needed: the relevant ID defaults are UUIDs.

-- USERS: global SELECT is necessary for existing-email lookup (owner/admin).
-- New users can be inserted before they have memberships.
-- Existing user UPDATE and DELETE are limited to active platform members.
DROP POLICY IF EXISTS ceopro_bootstrap_users_select ON public.users;
CREATE POLICY ceopro_bootstrap_users_select ON public.users
    AS PERMISSIVE FOR SELECT TO ceopro_bootstrap
    USING (true);

DROP POLICY IF EXISTS ceopro_bootstrap_users_insert ON public.users;
CREATE POLICY ceopro_bootstrap_users_insert ON public.users
    AS PERMISSIVE FOR INSERT TO ceopro_bootstrap
    WITH CHECK (true);

DROP POLICY IF EXISTS ceopro_bootstrap_users_update ON public.users;
CREATE POLICY ceopro_bootstrap_users_update ON public.users
    AS PERMISSIVE FOR UPDATE TO ceopro_bootstrap
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS ceopro_bootstrap_users_delete ON public.users;
CREATE POLICY ceopro_bootstrap_users_delete ON public.users
    AS PERMISSIVE FOR DELETE TO ceopro_bootstrap
    USING (true);

-- Restrictive guards still apply when PUBLIC permissive policies also exist.
DROP POLICY IF EXISTS ceopro_bootstrap_users_update_guard ON public.users;
CREATE POLICY ceopro_bootstrap_users_update_guard ON public.users
    AS RESTRICTIVE FOR UPDATE TO ceopro_bootstrap
    USING (
       EXISTS (
         SELECT 1 FROM public.tenant_users AS tu
         JOIN public.companies AS c ON c.tenant_id = tu.tenant_id
         WHERE tu.user_id = users.user_id
           AND tu.removed_at IS NULL
           AND c.business_type = 'platform'
           AND c.deleted_at IS NULL
       )
    )
    WITH CHECK (
       EXISTS (
         SELECT 1 FROM public.tenant_users AS tu
         JOIN public.companies AS c ON c.tenant_id = tu.tenant_id
         WHERE tu.user_id = users.user_id
           AND tu.removed_at IS NULL
           AND c.business_type = 'platform'
           AND c.deleted_at IS NULL
       )
    );

DROP POLICY IF EXISTS ceopro_bootstrap_users_delete_guard ON public.users;
CREATE POLICY ceopro_bootstrap_users_delete_guard ON public.users
    AS RESTRICTIVE FOR DELETE TO ceopro_bootstrap
    USING (
       EXISTS (
         SELECT 1 FROM public.tenant_users AS tu
         JOIN public.companies AS c ON c.tenant_id = tu.tenant_id
         WHERE tu.user_id = users.user_id
           AND tu.removed_at IS NULL
           AND c.business_type = 'platform'
           AND c.deleted_at IS NULL
       )
    );

-- COMPANIES: only platform-company records, never normal customer tenants.
DROP POLICY IF EXISTS ceopro_bootstrap_companies_allow ON public.companies;
CREATE POLICY ceopro_bootstrap_companies_allow ON public.companies
    AS PERMISSIVE FOR ALL TO ceopro_bootstrap
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS ceopro_bootstrap_companies_guard ON public.companies;
CREATE POLICY ceopro_bootstrap_companies_guard ON public.companies
    AS RESTRICTIVE FOR ALL TO ceopro_bootstrap
    USING (business_type = 'platform' AND deleted_at IS NULL)
    WITH CHECK (business_type = 'platform' AND deleted_at IS NULL);

-- TENANT_USERS: only membership records whose companies are platforms.
-- New/updated bootstrap memberships are constrained to owner/admin.
DROP POLICY IF EXISTS ceopro_bootstrap_tenant_users_allow ON public.tenant_users;
CREATE POLICY ceopro_bootstrap_tenant_users_allow ON public.tenant_users
    AS PERMISSIVE FOR ALL TO ceopro_bootstrap
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS ceopro_bootstrap_tenant_users_guard ON public.tenant_users;
CREATE POLICY ceopro_bootstrap_tenant_users_guard ON public.tenant_users
    AS RESTRICTIVE FOR ALL TO ceopro_bootstrap
    USING (
       EXISTS (
         SELECT 1 FROM public.companies AS c
         WHERE c.tenant_id = tenant_users.tenant_id
           AND c.business_type = 'platform'
           AND c.deleted_at IS NULL
       )
    )
    WITH CHECK (
       role_key IN ('owner', 'admin')
       AND EXISTS (
         SELECT 1 FROM public.companies AS c
         WHERE c.tenant_id = tenant_users.tenant_id
           AND c.business_type = 'platform'
           AND c.deleted_at IS NULL
       )
    );

-- The current schema normally leaves catalog/configuration tables without RLS.
-- If a deployed Render database has RLS enabled on any of them, add the
-- dedicated, non-PUBLIC bootstrap policy without changing RLS settings.
DO $catalog_policies$
DECLARE
    table_name text;
    policy_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'features', 'plans', 'plan_features', 'plan_price_versions',
        'app_config', 'subscription_usage', 'custom_plan_quote_features',
        'vendor_rates', 'system_roles'
    ] LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_class AS c
            JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = table_name AND c.relrowsecurity
        ) THEN
            policy_name := 'ceopro_bootstrap_catalog_access';
            EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', policy_name, table_name);
            IF table_name = 'system_roles' THEN
               EXECUTE format(
                 'CREATE POLICY %I ON public.%I AS PERMISSIVE FOR SELECT TO ceopro_bootstrap USING (true)',
                 policy_name, table_name
               );
            ELSE
               EXECUTE format(
                 'CREATE POLICY %I ON public.%I AS PERMISSIVE FOR ALL TO ceopro_bootstrap USING (true) WITH CHECK (true)',
                 policy_name, table_name
               );
            END IF;
        END IF;
    END LOOP;
END
$catalog_policies$;

COMMIT;

-- Verification: run as the administrator after provisioning.
SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolbypassrls
FROM pg_catalog.pg_roles WHERE rolname = 'ceopro_bootstrap';

SELECT schemaname, tablename, policyname, permissive, roles, cmd
FROM pg_catalog.pg_policies
WHERE schemaname = 'public'
  AND policyname LIKE 'ceopro_bootstrap_%'
ORDER BY tablename, policyname;

-- Next: update every bootstrap script to connect using BOOTSTRAP_DATABASE_URL.
-- The current scripts import a Prisma client that reads DATABASE_URL.
-- Keep the privileged URL inaccessible to normal backend/worker processes.
