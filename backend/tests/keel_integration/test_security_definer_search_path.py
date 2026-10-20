"""Native checks for authentication SECURITY DEFINER search-path hardening."""
import os
import uuid

import pytest
from scripts.billing_verification import is_test_database_name, validate_test_environment

pytestmark = pytest.mark.skipif(
    os.getenv("BILLING_DATABASE_TESTS") != "1",
    reason="BLOCKED: isolated native PostgreSQL 17 not enabled",
)


FUNCTIONS = {
    "auth_email_verified": ("uuid",),
    "auth_join_tenant": ("uuid", "uuid", "character varying", "bigint"),
    "auth_lookup_user_by_email": ("text",),
    "auth_mark_email_verified": ("uuid",),
}


def connect():
    import psycopg2

    assert os.getenv("PHASE1A_ISOLATED_DATABASE") == "YES"
    assert not os.getenv("BILLING_TEST_ENGINE")
    url = validate_test_environment(dict(os.environ), database=True)
    conn = psycopg2.connect(
        url,
        connect_timeout=5,
        gssencmode="disable",
        sslmode="disable",
    )
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_setting('server_version_num')::integer"
        )
        database, version = cursor.fetchone()
        assert is_test_database_name(database)
        assert 170000 <= version < 180000
    conn.commit()
    return conn


def test_auth_definer_catalog_has_restricted_search_paths_and_privileges():
    conn = connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.proname,
                       oidvectortypes(p.proargtypes),
                       pg_get_userbyid(p.proowner),
                       p.prosecdef,
                       p.proconfig,
                       has_function_privilege('ceopro_app', p.oid, 'EXECUTE'),
                       EXISTS (
                           SELECT 1
                           FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
                           WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                       )
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname = ANY(%s)
                ORDER BY p.proname
                """,
                (list(FUNCTIONS),),
            )
            rows = cursor.fetchall()

        assert len(rows) == len(FUNCTIONS)
        for name, arguments, owner, security_definer, config, app_execute, public_execute in rows:
            assert tuple(arguments.split(", ")) == FUNCTIONS[name]
            assert owner == "keel_billing_test_admin"
            assert security_definer is True
            assert "search_path=pg_catalog, public, pg_temp" in config
            assert app_execute is True
            assert public_execute is False
    finally:
        conn.close()


def test_auth_definer_functions_ignore_caller_temporary_table_shadows():
    conn = connect()
    marker = uuid.uuid4().hex
    email = f"shadow-{marker}@example.test"
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.users
                    (user_id, email, password_hash, full_name, email_verified_at)
                VALUES (%s, %s, 'real-hash', 'Real User', NULL)
                """,
                (str(user_id), email),
            )
            cursor.execute(
                """
                INSERT INTO public.companies
                    (tenant_id, business_name, country_code, primary_currency)
                VALUES (%s, %s, 'JO', 'JOD')
                """,
                (str(tenant_id), f"Shadow test {marker}"),
            )
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute("SET ROLE ceopro_app")
            cursor.execute(
                """
                CREATE TEMP TABLE users (
                    user_id uuid,
                    email text,
                    password_hash text,
                    full_name varchar,
                    preferred_language varchar,
                    email_verified_at timestamptz,
                    updated_at timestamptz
                )
                """
            )
            cursor.execute(
                """
                CREATE TEMP TABLE tenant_users (
                    tenant_id uuid,
                    user_id uuid,
                    role_key varchar,
                    removed_at timestamptz,
                    joined_at timestamptz,
                    UNIQUE (tenant_id, user_id)
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO pg_temp.users
                    (user_id, email, password_hash, full_name, preferred_language, email_verified_at)
                VALUES (%s, %s, 'shadow-hash', 'Shadow User', 'xx', NULL)
                """,
                (str(user_id), email),
            )
            cursor.execute("SELECT password_hash, full_name FROM public.auth_lookup_user_by_email(%s)", (email,))
            assert cursor.fetchone() == ("real-hash", "Real User")
            cursor.execute("SELECT public.auth_email_verified(%s)", (str(user_id),))
            assert cursor.fetchone()[0] is False

            cursor.execute("SELECT public.auth_mark_email_verified(%s)", (str(user_id),))
            cursor.execute(
                "SELECT email_verified_at IS NOT NULL FROM pg_temp.users WHERE user_id=%s",
                (str(user_id),),
            )
            assert cursor.fetchone()[0] is False

            cursor.execute(
                "SELECT public.auth_join_tenant(%s, %s, 'staff', 5)",
                (str(tenant_id), str(user_id)),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "SELECT count(*) FROM pg_temp.tenant_users WHERE tenant_id=%s AND user_id=%s",
                (str(tenant_id), str(user_id)),
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute("RESET ROLE")
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT email_verified_at IS NOT NULL FROM public.users WHERE user_id=%s",
                (str(user_id),),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "SELECT count(*) FROM public.tenant_users WHERE tenant_id=%s AND user_id=%s",
                (str(tenant_id), str(user_id)),
            )
            assert cursor.fetchone()[0] == 1
    finally:
        conn.rollback()
        with conn.cursor() as cursor:
            cursor.execute("RESET ROLE")
            cursor.execute("DELETE FROM public.tenant_users WHERE tenant_id=%s", (str(tenant_id),))
            cursor.execute("DELETE FROM public.companies WHERE tenant_id=%s", (str(tenant_id),))
            cursor.execute("DELETE FROM public.users WHERE user_id=%s", (str(user_id),))
        conn.commit()
        conn.close()
