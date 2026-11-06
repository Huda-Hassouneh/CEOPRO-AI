"""Real PG17 installer tests; use a dedicated local 102-migration baseline.

Set KEEL_M103_TEST_ADMIN_DSN and KEEL_M103_TEST_INSTALLER_DSN to the same
loopback-only keel_m103_test database. Never point these at an existing app DB.
The installer must own that baseline and be CREATEROLE but not SUPERUSER.
"""

import os
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn
import pytest

from scripts import apply_migrations as runner
from scripts import migration_103_compat as compat


MIGRATION = runner.MIGRATIONS_DIR / compat.FILENAME
SOURCE = MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def settings():
    values = {name: os.getenv("KEEL_M103_TEST_" + name.upper() + "_DSN")
              for name in ("admin", "installer")}
    if not all(values.values()):
        pytest.skip("Dedicated local migration-103 test DSNs required")
    parsed = [parse_dsn(dsn) for dsn in values.values()]
    assert all(p["host"] == "127.0.0.1" and p["dbname"] == "keel_m103_test" for p in parsed)
    assert parsed[0]["port"] == parsed[1]["port"]
    for mode, dsn in values.items():
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            assert conn.server_version >= 170000
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone()[0] is (mode == "admin")
            cur.execute("SELECT count(*) FROM schema_migrations")
            assert cur.fetchone()[0] == 102
    return values


@pytest.fixture
def installer(settings):
    conn = psycopg2.connect(settings["installer"])
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def admin(settings):
    conn = psycopg2.connect(settings["admin"])
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _create_owner(cur):
    cur.execute(SOURCE.split(compat.ALTER)[0])


def test_original_sql_reproduces_neon_permission_failure(installer):
    with installer.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege) as error:
        cur.execute(SOURCE)
    assert "SUPERUSER attribute" in str(error.value)


@pytest.mark.parametrize("mode", ["admin", "installer"])
def test_real_migration_security_and_function_ownership(settings, mode):
    conn = psycopg2.connect(settings[mode])
    try:
        runner._apply_sql_file(conn, MIGRATION)
        with conn.cursor() as cur:
            oid = compat._verify_owner(cur)
            cur.execute("SELECT count(*),bool_and(prosecdef),bool_and(proconfig IS NOT NULL) "
                        "FROM pg_proc WHERE proowner=%s", (oid,))
            assert cur.fetchone() == (7, True, True)
            cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                        "WHERE oid='notification_outbox'::regclass")
            assert cur.fetchone() == (True, True)
            cur.execute("SELECT has_schema_privilege(%s,'public','CREATE'), "
                        "has_table_privilege('ceopro_app','notification_outbox','SELECT'), "
                        "pg_has_role('ceopro_app',%s,'MEMBER')", (compat.ROLE, oid))
            assert cur.fetchone() == (False, False, False)
            cur.execute("SELECT count(*) FROM pg_proc p, "
                        "LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a "
                        "WHERE p.proowner=%s AND a.grantee=0 AND a.privilege_type='EXECUTE'", (oid,))
            assert cur.fetchone()[0] == 0
            if mode == "installer":
                cur.execute("SELECT pg_has_role(current_user,%s,'SET')", (oid,))
                assert cur.fetchone()[0] is False
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("attribute", ["SUPERUSER", "BYPASSRLS", "LOGIN", "CREATEDB",
                                       "CREATEROLE", "INHERIT", "REPLICATION"])
def test_unsafe_existing_attributes_fail_closed(admin, attribute):
    with admin.cursor() as cur:
        _create_owner(cur)
        cur.execute(sql.SQL("ALTER ROLE {} {}").format(sql.Identifier(compat.ROLE), sql.SQL(attribute)))
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(RuntimeError, match="unsafe role attributes"):
        runner._apply_sql_file(admin, MIGRATION)


@pytest.mark.parametrize("options", ["INHERIT FALSE, SET TRUE", "INHERIT TRUE, SET FALSE"])
def test_membership_privilege_is_rejected_even_when_noinherit(admin, options):
    with admin.cursor() as cur:
        _create_owner(cur)
        cur.execute(sql.SQL("GRANT pg_read_all_data TO {} WITH " + options)
                    .format(sql.Identifier(compat.ROLE)))
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(RuntimeError, match="unexpected role membership"):
        runner._apply_sql_file(admin, MIGRATION)


@pytest.mark.parametrize("extra", ["schema", "table", "runtime_grantee"])
def test_unexpected_ownership_or_runtime_grants_fail_closed(admin, extra):
    with admin.cursor() as cur:
        _create_owner(cur)
        if extra == "schema":
            cur.execute("CREATE SCHEMA m103_unexpected AUTHORIZATION keel_notification_fn_owner")
        elif extra == "table":
            cur.execute("CREATE TABLE m103_unexpected(value int)")
            cur.execute("ALTER TABLE m103_unexpected OWNER TO keel_notification_fn_owner")
        else:
            cur.execute("GRANT keel_notification_fn_owner TO ceopro_app WITH INHERIT FALSE, SET TRUE")
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(RuntimeError, match="unexpected ownership or grantees"):
        runner._apply_sql_file(admin, MIGRATION)


def test_installer_without_admin_authority_is_not_bypassed(admin):
    with admin.cursor() as cur:
        _create_owner(cur)  # Created by postgres, not by the installer.
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        runner._apply_sql_file(admin, MIGRATION)


@pytest.mark.parametrize("can_set,inherit", [(False, False), (True, False), (True, True)])
def test_existing_installer_membership_options_are_preserved(installer, can_set, inherit):
    with installer.cursor() as cur:
        _create_owner(cur)
        cur.execute(sql.SQL("GRANT {} TO CURRENT_USER WITH ADMIN FALSE, INHERIT {}, SET {} "
                            "GRANTED BY CURRENT_USER")
                    .format(sql.Identifier(compat.ROLE), sql.SQL("TRUE" if inherit else "FALSE"),
                            sql.SQL("TRUE" if can_set else "FALSE")))
        oid = compat._verify_owner(cur)
        previous = compat._memberships(cur, oid)
    runner._apply_sql_file(installer, MIGRATION)
    with installer.cursor() as cur:
        assert compat._memberships(cur, oid) == previous


def test_failed_acl_establishment_is_rejected(admin):
    runner._apply_sql_file(admin, MIGRATION)
    with admin.cursor() as cur:
        cur.execute("GRANT EXECUTE ON FUNCTION public.mark_all_tenant_notifications_read(uuid) TO PUBLIC")
        with pytest.raises(RuntimeError, match="function security was not established"):
            compat._verify_result(cur)


def test_default_public_function_acl_is_rejected(admin):
    with admin.cursor() as cur:
        cur.execute(SOURCE.split("REVOKE ALL ON FUNCTION")[0])
        with pytest.raises(RuntimeError, match="function security was not established"):
            compat._verify_result(cur)


def test_transaction_and_source_guards(installer):
    with installer.cursor() as cur, pytest.raises(RuntimeError, match="immutable SQL"):
        compat.apply(cur, SOURCE + "\n-- unexpected change")
    installer.rollback()
    installer.autocommit = True
    with installer.cursor() as cur, pytest.raises(RuntimeError, match="requires a transaction"):
        compat.apply(cur, SOURCE)
    installer.autocommit = False
    with installer.cursor() as cur:
        cur.execute("SELECT to_regrole(%s)", (compat.ROLE,))
        assert cur.fetchone()[0] is None


def test_force_rls_keeps_two_tenant_notifications_separate(admin):
    runner._apply_sql_file(admin, MIGRATION)
    pairs = [(str(uuid.uuid4()), str(uuid.uuid4())) for _ in range(2)]
    with admin.cursor() as cur:
        for tenant, user in pairs:
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) "
                        "VALUES(%s,'Synthetic migration test','JO','JOD')", (tenant,))
            cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login')",
                        (user, user + "@example.com"))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
                        (tenant, user))
            cur.execute("INSERT INTO notification_outbox(tenant_id,recipient_user_id,event_key,event_kind,"
                        "category,severity,payload) VALUES(%s,%s,'test:103','import_failed','data','warning','{}')",
                        (tenant, user))
        cur.execute("SET LOCAL ROLE keel_notification_fn_owner")
        for tenant, user in pairs:
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true)", (tenant,))
            cur.execute("SELECT set_config('app.current_user_id',%s,true)", (user,))
            cur.execute("SELECT tenant_id::text FROM notification_outbox")
            assert cur.fetchall() == [(tenant,)]
        cur.execute("SELECT set_config('app.current_tenant_id','',true)")
        cur.execute("SELECT count(*) FROM notification_outbox")
        assert cur.fetchone()[0] == 0


def test_runner_rolls_back_owner_grants_tables_and_ledger(installer, monkeypatch, tmp_path):
    (tmp_path / compat.FILENAME).write_text(SOURCE, encoding="utf-8")
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
    original_apply = runner._apply_sql_file

    def fail_after_real_migration(conn, path):
        original_apply(conn, path)
        with conn.cursor() as cur:
            cur.execute("SELECT 1/0")

    monkeypatch.setattr(runner, "_apply_sql_file", fail_after_real_migration)
    with pytest.raises(psycopg2.errors.DivisionByZero):
        runner.run(installer)
    with installer.cursor() as cur:
        cur.execute("SELECT to_regrole(%s),to_regclass('notification_outbox')", (compat.ROLE,))
        assert cur.fetchone() == (None, None)
        cur.execute("SELECT count(*) FROM schema_migrations")
        assert cur.fetchone()[0] == 102


def test_committed_history_is_skipped_on_replay(settings, monkeypatch, tmp_path):
    # Clone only this test's guarded local baseline; no existing application DB.
    dbname = "keel_m103_history_" + uuid.uuid4().hex[:10]
    control = psycopg2.connect(make_dsn(settings["admin"], dbname="postgres"))
    control.autocommit = True
    conn = None
    try:
        with control.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {} WITH TEMPLATE keel_m103_test OWNER m103_installer")
                        .format(sql.Identifier(dbname)))
        conn = psycopg2.connect(make_dsn(settings["installer"], dbname=dbname))
        (tmp_path / compat.FILENAME).write_text(SOURCE, encoding="utf-8")
        monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
        assert runner.run(conn) == [compat.FILENAME]

        def unexpected_execution(*args):
            pytest.fail("An already committed migration must not execute again")

        monkeypatch.setattr(runner, "_apply_sql_file", unexpected_execution)
        assert runner.run(conn) == []
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            assert cur.fetchone()[0] == 103
    finally:
        if conn is not None:
            conn.close()
        with control.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(dbname)))
            cur.execute("DROP ROLE IF EXISTS keel_notification_fn_owner")
        control.close()
