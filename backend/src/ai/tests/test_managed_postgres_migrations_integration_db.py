"""Migrations on managed PostgreSQL (Neon): the migration role is not a superuser.

Neon gives the database owner CREATEROLE/CREATEDB/BYPASSRLS but never SUPERUSER,
so a migration that alters SUPERUSER/BYPASSRLS, transfers ownership to a role
it cannot SET ROLE to, or grants on a function it no longer owns either fails
or (for GRANT/REVOKE) is silently skipped. This test builds the whole schema
twice on a dedicated, disposable cluster - once as a Neon-shaped non-superuser
owner and once as a superuser - and requires the security catalog (roles,
memberships, function owners and grants, schema CREATE, FORCE RLS, policies,
table grants) to be identical, then checks tenant isolation of the notification
inbox on the non-superuser build.

Needs AI_TEST_MANAGED_PG_ADMIN_URL: a superuser URL for a cluster used only by
this test (roles are cluster-wide; the test drops and recreates the KEEL roles
there). It refuses to run on a cluster holding any other database.
"""
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

ADMIN_URL = os.getenv("AI_TEST_MANAGED_PG_ADMIN_URL")
APP_PASSWORD = os.getenv("APP_DB_PASSWORD")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_PASSWORD,
    reason="AI_TEST_MANAGED_PG_ADMIN_URL (a dedicated disposable cluster) and APP_DB_PASSWORD are required",
)

NEON_DB, SUPER_DB = "keel_mpg_neon", "keel_mpg_super"
OWNER, OWNER_PASSWORD = "mpg_migration_owner", "keel-mpg-owner-test-only"
KEEL_ROLES = ("ceopro_app", "ceopro_billing_setup", "ceopro_trial_issuer", "ceopro_billing_webhook",
              "ceopro_credit_accounting", "ceopro_billing_lookup", "ceopro_schedule_writer",
              "keel_notification_fn_owner")
MIGRATIONS = Path(__file__).resolve().parents[2] / "infrastructure" / "database" / "migrations"

SNAPSHOT = [
    """SELECT 'role', rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolcanlogin
       FROM pg_roles WHERE (rolname LIKE 'ceopro%%' OR rolname LIKE 'keel%%') AND rolname <> %(owner)s ORDER BY 2""",
    """SELECT 'member', r.rolname, m.rolname FROM pg_auth_members a
       JOIN pg_roles r ON r.oid = a.roleid JOIN pg_roles m ON m.oid = a.member
       WHERE (r.rolname LIKE 'ceopro%%' OR r.rolname LIKE 'keel%%' OR m.rolname LIKE 'ceopro%%' OR m.rolname LIKE 'keel%%')
         AND m.rolname NOT IN (%(owner)s, current_user) ORDER BY 2, 3""",
    """SELECT 'function', p.oid::regprocedure::text, pg_get_userbyid(p.proowner), p.prosecdef,
              array_to_string(p.proacl::text[], ',')
       FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
       WHERE n.nspname = 'public' AND (pg_get_userbyid(p.proowner) LIKE 'ceopro%%'
                                       OR pg_get_userbyid(p.proowner) LIKE 'keel%%') ORDER BY 2""",
    """SELECT 'ddl', rolname, has_schema_privilege(rolname, 'public', 'CREATE'),
              has_database_privilege(rolname, current_database(), 'CREATE')
       FROM pg_roles WHERE (rolname LIKE 'ceopro%%' OR rolname LIKE 'keel%%') AND rolname <> %(owner)s ORDER BY 2""",
    """SELECT 'rls', relname, relrowsecurity, relforcerowsecurity FROM pg_class c
       JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND relkind = 'r' ORDER BY 2""",
    """SELECT 'policy', tablename, policyname, permissive, roles::text, cmd, qual, with_check
       FROM pg_policies WHERE schemaname = 'public' ORDER BY 2, 3""",
    """SELECT 'grant', grantee, table_name, string_agg(privilege_type, ',' ORDER BY privilege_type)
       FROM information_schema.role_table_grants
       WHERE grantee LIKE 'ceopro%%' OR grantee LIKE 'keel%%' GROUP BY 2, 3 ORDER BY 2, 3""",
]


def _url(database, user=None, password=None):
    parsed = urlparse(ADMIN_URL)
    netloc = parsed.netloc
    if user:
        host = netloc.rsplit("@", 1)[-1]
        netloc = f"{user}:{password}@{host}"
    return urlunparse(parsed._replace(netloc=netloc, path=f"/{database}"))


def _autocommit(url):
    conn = psycopg2.connect(url)
    conn.autocommit = True
    return conn


def _snapshot(url):
    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        rows = []
        for query in SNAPSHOT:
            cur.execute(query, {"owner": OWNER})
            rows.extend(cur.fetchall())
        return rows


@pytest.fixture(scope="module")
def built():
    from scripts import apply_migrations

    admin = _autocommit(_url("postgres"))
    with admin.cursor() as cur:
        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        assert cur.fetchone()[0], "AI_TEST_MANAGED_PG_ADMIN_URL must be a superuser on a dedicated cluster"
        cur.execute("SELECT datname FROM pg_database WHERE datname NOT IN ('postgres', 'template0', 'template1', %s, %s)",
                    (NEON_DB, SUPER_DB))
        others = [row[0] for row in cur.fetchall()]
        if others:
            pytest.fail(f"refusing to reset cluster-wide roles: the cluster also holds {others}")
        for database in (NEON_DB, SUPER_DB):
            cur.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        for role in KEEL_ROLES + (OWNER, "mpg_neon_superuser"):
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone():
                cur.execute(f'DROP OWNED BY "{role}"')
                cur.execute(f'DROP ROLE "{role}"')
        # Neon's shape: neon_superuser has CREATEROLE/CREATEDB/REPLICATION/BYPASSRLS
        # but no SUPERUSER, and the database owner is a login member of it.
        cur.execute("CREATE ROLE mpg_neon_superuser NOLOGIN CREATEDB CREATEROLE REPLICATION BYPASSRLS")
        cur.execute("GRANT pg_read_all_data, pg_write_all_data, pg_signal_backend TO mpg_neon_superuser")
        cur.execute(f"CREATE ROLE {OWNER} LOGIN CREATEDB CREATEROLE BYPASSRLS IN ROLE mpg_neon_superuser "
                    "PASSWORD %s", (OWNER_PASSWORD,))
        cur.execute(f'CREATE DATABASE "{NEON_DB}" OWNER {OWNER}')
        cur.execute(f'CREATE DATABASE "{SUPER_DB}"')
    admin.close()
    for database in (NEON_DB, SUPER_DB):  # Neon offers these extensions to the owner.
        conn = _autocommit(_url(database))
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; "
                        "CREATE EXTENSION IF NOT EXISTS pgcrypto;")
        conn.close()

    neon_url = _url(NEON_DB, OWNER, OWNER_PASSWORD)
    conn = psycopg2.connect(neon_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            assert cur.fetchone()[0] is False
        neon_applied = apply_migrations.run(conn)
    finally:
        conn.close()
    conn = psycopg2.connect(_url(SUPER_DB))
    try:
        super_applied = apply_migrations.run(conn)
    finally:
        conn.close()
    return {"neon_url": neon_url, "super_url": _url(SUPER_DB),
            "neon_applied": neon_applied, "super_applied": super_applied}


def test_every_migration_applies_as_a_non_superuser_owner(built):
    expected = sorted(path.name for path in MIGRATIONS.glob("*.sql"))
    assert built["neon_applied"] == expected
    assert built["super_applied"] == expected


def test_security_catalog_matches_a_superuser_build(built):
    neon, superuser = _snapshot(built["neon_url"]), _snapshot(built["super_url"])
    assert [row for row in neon if row[0] == "policy"], "no RLS policies captured"
    assert neon == superuser


def test_function_owners_are_restricted_and_public_cannot_execute(built):
    with psycopg2.connect(built["neon_url"]) as conn, conn.cursor() as cur:
        cur.execute("""SELECT p.proname, pg_get_userbyid(p.proowner), r.rolsuper, r.rolbypassrls, r.rolcanlogin,
                              has_function_privilege('public', p.oid, 'EXECUTE')
                       FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
                       WHERE p.proname IN ('enqueue_tenant_notification', 'list_tenant_notifications',
                                           'billing_setup_trial', 'billing_provider_tenant')""")
        rows = {row[0]: row[1:] for row in cur.fetchall()}
        cur.execute("SELECT has_function_privilege('ceopro_app', 'public.list_tenant_notifications(uuid,integer,timestamptz,uuid,boolean)', 'EXECUTE')")
        assert cur.fetchone()[0] is True
    assert rows["enqueue_tenant_notification"] == ("keel_notification_fn_owner", False, False, False, False)
    assert rows["list_tenant_notifications"] == ("keel_notification_fn_owner", False, False, False, False)
    assert rows["billing_setup_trial"] == ("ceopro_trial_issuer", False, False, False, False)
    assert rows["billing_provider_tenant"] == ("ceopro_billing_lookup", False, False, False, False)


def test_migration_owner_keeps_no_membership_in_restricted_roles(built):
    with psycopg2.connect(built["neon_url"]) as conn, conn.cursor() as cur:
        cur.execute("""SELECT r.rolname FROM pg_auth_members a
                       JOIN pg_roles r ON r.oid = a.roleid JOIN pg_roles m ON m.oid = a.member
                       WHERE m.rolname = %s AND r.rolname = ANY(%s) AND (a.set_option OR a.inherit_option)""",
                    (OWNER, list(KEEL_ROLES)))
        assert cur.fetchall() == []


def test_notification_inbox_is_tenant_isolated_on_the_non_superuser_build(built):
    tenant_a, tenant_b, user_a, user_b = (str(uuid.uuid4()) for _ in range(4))
    with psycopg2.connect(built["neon_url"]) as conn, conn.cursor() as cur:
        for tenant, user, label in ((tenant_a, user_a, "a"), (tenant_b, user_b, "b")):
            cur.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
                        "VALUES (%s, %s, 'JO', 'JOD')", (tenant, f"MPG {label}"))
            cur.execute("INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'x')",
                        (user, f"mpg-{label}-{user[:8]}@example.com"))
            cur.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner')",
                        (tenant, user))

    parsed = urlparse(built["neon_url"])
    app = psycopg2.connect(urlunparse(parsed._replace(
        netloc=f"ceopro_app:{APP_PASSWORD}@{parsed.netloc.rsplit('@', 1)[-1]}")))
    context = "SELECT set_config('app.current_tenant_id', %s, true), set_config('app.current_user_id', %s, true)"
    list_call = "SELECT public.list_tenant_notifications(%s::uuid, 20, NULL, NULL, false)"
    try:
        with app.cursor() as cur:
            cur.execute(context, (tenant_a, user_a))
            cur.execute("SELECT public.enqueue_tenant_notification(%s, %s, 'restock:mpg-1', 'restock', 'stock', "
                        "'warning', '{}'::jsonb)", (tenant_a, user_a))
            cur.execute(list_call, (tenant_a,))
            assert len(cur.fetchone()[0]["items"]) == 1
        app.commit()

        with app.cursor() as cur:  # Tenant B sees nothing of tenant A's inbox.
            cur.execute(context, (tenant_b, user_b))
            cur.execute(list_call, (tenant_b,))
            assert cur.fetchone()[0]["items"] == []
        app.commit()

        with app.cursor() as cur:  # Asking for A's inbox from B's context is refused.
            cur.execute(context, (tenant_b, user_b))
            with pytest.raises(psycopg2.Error) as refused:
                cur.execute(list_call, (tenant_a,))
            assert refused.value.pgcode == "42501"
        app.rollback()

        with app.cursor() as cur:  # The application role cannot read the table directly.
            cur.execute(context, (tenant_a, user_a))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("SELECT * FROM notification_outbox")
        app.rollback()

        with app.cursor() as cur:  # Nor enqueue for another tenant's user.
            cur.execute(context, (tenant_b, user_b))
            with pytest.raises(psycopg2.Error) as cross:
                cur.execute("SELECT public.enqueue_tenant_notification(%s, %s, 'restock:mpg-2', 'restock', 'stock', "
                            "'warning', '{}'::jsonb)", (tenant_a, user_a))
            assert cross.value.pgcode == "42501"
        app.rollback()
    finally:
        app.close()
