-- The original migration granted EXECUTE before transferring function
-- ownership. If the migration identity was ceopro_ai_test_user, PostgreSQL
-- treated its access as the function owner's implicit privilege and removed
-- that access when ownership moved to ceopro_platform_overview_reader.
-- Regrant explicitly after the ownership transfer.

DO $$
BEGIN
  EXECUTE format(
    'GRANT ceopro_platform_overview_reader TO %I',
    current_user
  );
END;
$$;

SET ROLE ceopro_platform_overview_reader;

REVOKE ALL ON FUNCTION public.get_platform_admin_overview_counts(
  uuid, uuid, timestamptz, timestamptz
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_platform_admin_overview_counts(
  uuid, uuid, timestamptz, timestamptz
) TO ceopro_app, ceopro_ai_prod_user, ceopro_ai_test_user;

RESET ROLE;

DO $$
BEGIN
  EXECUTE format(
    'REVOKE ceopro_platform_overview_reader FROM %I',
    current_user
  );
END;
$$;
