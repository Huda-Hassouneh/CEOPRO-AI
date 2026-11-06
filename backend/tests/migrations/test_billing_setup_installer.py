"""Real PG17 tests on a guarded, disposable 140-migration local baseline."""

import os
import secrets
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import cursor, make_dsn, parse_dsn
import pytest

from scripts import apply_migrations as runner
from scripts import migration_141_compat as compat
from scripts.migration_103_compat import _memberships


MIGRATION = runner.MIGRATIONS_DIR / compat.FILENAME
SOURCE = MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def settings():
    values = {key: os.getenv("KEEL_M141_TEST_" + key.upper() + "_DSN")
              for key in ("admin", "installer")}
    if not all(values.values()):
        pytest.skip("Dedicated local migration-141 test DSNs required")
    parsed = [parse_dsn(v) for v in values.values()]
    assert all(p["host"] == "127.0.0.1" and p["dbname"] == "keel_m141_test" for p in parsed)
    assert parsed[0]["port"] == parsed[1]["port"]
    for mode, dsn in values.items():
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            assert conn.server_version >= 170000
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone()[0] is (mode == "admin")
            cur.execute("SELECT count(*) FROM schema_migrations")
            assert cur.fetchone()[0] == 140
    return values


@pytest.fixture(params=["admin", "installer"])
def authority(settings, request):
    conn = psycopg2.connect(settings[request.param])
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


@pytest.fixture
def installer(settings):
    conn = psycopg2.connect(settings["installer"])
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _create_roles(cur):
    cur.execute(SOURCE.split("-- No password in migration history.")[0])


def test_original_sql_reproduces_set_role_failure(installer):
    with installer.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege) as error:
        cur.execute(SOURCE)
    assert "SET ROLE" in str(error.value) and compat.OWNER in str(error.value)


def test_original_transfer_also_requires_owner_schema_create(installer):
    with installer.cursor() as cur:
        cur.execute(SOURCE.split(compat.TRANSFER)[0])
        cur.execute("GRANT ceopro_trial_issuer TO CURRENT_USER WITH INHERIT TRUE, SET TRUE")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege) as error:
            cur.execute(compat.TRANSFER)
    assert "schema public" in str(error.value)


def test_successful_migration_preserves_security_and_function_body(authority):
    schema_acl = ("SELECT grantee::regrole::text,grantor::regrole::text,privilege_type,is_grantable "
                  "FROM pg_namespace n,LATERAL aclexplode(n.nspacl) "
                  "WHERE nspname='public'")
    with authority.cursor() as cur:
        cur.execute(schema_acl)
        original_acl = set(cur.fetchall())
    runner._apply_sql_file(authority, MIGRATION)
    with authority.cursor() as cur:
        compat._verify_result(cur)
        cur.execute(schema_acl)
        final_acl = set(cur.fetchall())
        assert original_acl <= final_acl
        additions = final_acl - original_acl
        assert len(additions) == 2
        assert {(r[0], r[2], r[3]) for r in additions} == {
            (compat.OWNER, "USAGE", False), (compat.SETUP, "USAGE", False)}
        cur.execute("SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure(%s)", (compat.FUNCTION,))
        assert cur.fetchone()[0] == SOURCE.split(" AS $$", 1)[1].split("$$;", 1)[0]
        for name in (compat.OWNER, compat.SETUP):
            cur.execute("SELECT has_table_privilege(%s,'billing_subscriptions','INSERT'),"
                        "has_table_privilege(%s,'usage_ledger','INSERT'),"
                        "has_table_privilege(%s,'tenant_credit_balances','UPDATE')", (name,) * 3)
            assert cur.fetchone() == (False, False, False)
        cur.execute("SELECT has_function_privilege('ceopro_app',%s,'EXECUTE'),"
                    "pg_has_role('ceopro_app','ceopro_trial_issuer','MEMBER')", (compat.FUNCTION,))
        assert cur.fetchone() == (False, False)
        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        if not cur.fetchone()[0]:
            cur.execute("SELECT pg_has_role(current_user,'ceopro_trial_issuer','SET'),"
                        "pg_has_role(current_user,'ceopro_trial_issuer','USAGE')")
            assert cur.fetchone() == (False, False)


@pytest.mark.parametrize("role", [compat.OWNER, compat.SETUP])
@pytest.mark.parametrize("attribute", ["SUPERUSER", "BYPASSRLS", "CREATEDB", "CREATEROLE", "INHERIT", "REPLICATION"])
def test_existing_privileged_roles_fail_closed(admin, role, attribute):
    with admin.cursor() as cur:
        _create_roles(cur)
        cur.execute(sql.SQL("ALTER ROLE {} {}").format(sql.Identifier(role), sql.SQL(attribute)))
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(psycopg2.errors.RaiseException, match="Unexpected billing setup role"):
        runner._apply_sql_file(admin, MIGRATION)


@pytest.mark.parametrize("role", [compat.OWNER, compat.SETUP])
def test_privileged_memberships_fail_closed(admin, role):
    with admin.cursor() as cur:
        _create_roles(cur)
        cur.execute(sql.SQL("GRANT pg_read_all_data TO {} WITH INHERIT FALSE, SET TRUE")
                    .format(sql.Identifier(role)))
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(psycopg2.errors.RaiseException, match="Unexpected billing setup role"):
        runner._apply_sql_file(admin, MIGRATION)


@pytest.mark.parametrize("unsafe", ["runtime_grantee", "schema_create"])
def test_unexpected_authority_fails_closed(admin, unsafe):
    with admin.cursor() as cur:
        _create_roles(cur)
        cur.execute("GRANT ceopro_trial_issuer,ceopro_billing_setup TO m103_installer "
                    "WITH ADMIN TRUE,INHERIT FALSE,SET FALSE")
        if unsafe == "runtime_grantee":
            cur.execute("GRANT ceopro_trial_issuer TO ceopro_app WITH INHERIT FALSE, SET TRUE")
        else:
            cur.execute("GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer")
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(RuntimeError, match="membership, ownership or DDL"):
        runner._apply_sql_file(admin, MIGRATION)


@pytest.mark.parametrize("can_set,inherit", [(False, False), (True, False), (True, True)])
def test_existing_installer_memberships_restored(installer, can_set, inherit):
    with installer.cursor() as cur:
        _create_roles(cur)
        cur.execute(sql.SQL("GRANT ceopro_trial_issuer TO CURRENT_USER WITH INHERIT {},SET {} "
                            "GRANTED BY CURRENT_USER")
                    .format(sql.SQL("TRUE" if inherit else "FALSE"), sql.SQL("TRUE" if can_set else "FALSE")))
        cur.execute("SELECT oid FROM pg_roles WHERE rolname='ceopro_trial_issuer'")
        oid = cur.fetchone()[0]
        original = _memberships(cur, oid)
    runner._apply_sql_file(installer, MIGRATION)
    with installer.cursor() as cur:
        assert _memberships(cur, oid) == original


def test_installer_without_role_admin_authority_is_rejected(admin):
    with admin.cursor() as cur:
        _create_roles(cur)
        cur.execute("SET LOCAL ROLE m103_installer")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        runner._apply_sql_file(admin, MIGRATION)


def test_missing_force_rls_and_incorrect_acl_are_rejected(admin):
    runner._apply_sql_file(admin, MIGRATION)
    with admin.cursor() as cur:
        cur.execute("GRANT EXECUTE ON FUNCTION billing_setup_trial(text,boolean) TO PUBLIC")
        with pytest.raises(RuntimeError, match="execution ACL"):
            compat._verify_result(cur)
        cur.execute("REVOKE EXECUTE ON FUNCTION billing_setup_trial(text,boolean) FROM PUBLIC")
        cur.execute("ALTER TABLE billing_trials NO FORCE ROW LEVEL SECURITY")
        with pytest.raises(RuntimeError, match="FORCE RLS"):
            compat._verify_result(cur)


def test_source_and_transaction_guards(installer):
    with installer.cursor() as cur, pytest.raises(RuntimeError, match="immutable SQL"):
        compat.apply(cur, SOURCE + "\n-- unexpected change")
    installer.rollback()
    installer.autocommit = True
    with installer.cursor() as cur, pytest.raises(RuntimeError, match="requires a transaction"):
        compat.apply(cur, SOURCE)
    installer.autocommit = False


def test_failure_during_temporary_permissions_rolls_back_everything(installer, monkeypatch, tmp_path):
    class FailAfterTransfer(cursor):
        def execute(self, query, parameters=None):
            result = super().execute(query, parameters)
            if query == compat.TRANSFER:
                super().execute("SELECT has_schema_privilege('ceopro_trial_issuer','public','CREATE'),"
                                "pg_has_role(current_user,'ceopro_trial_issuer','SET'),"
                                "pg_has_role(current_user,'ceopro_trial_issuer','USAGE')")
                assert self.fetchone() == (True, True, True)
                super().execute("SELECT 1/0")
            return result

    installer.cursor_factory = FailAfterTransfer
    (tmp_path / compat.FILENAME).write_text(SOURCE, encoding="utf-8")
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
    with installer.cursor() as cur:
        cur.execute("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
        original_acl = cur.fetchone()[0]
    with pytest.raises(psycopg2.errors.DivisionByZero):
        runner.run(installer)
    with installer.cursor() as cur:
        cur.execute("SELECT to_regrole('ceopro_trial_issuer'),to_regrole('ceopro_billing_setup'),"
                    "to_regprocedure('public.billing_setup_trial(text,boolean)')")
        assert cur.fetchone() == (None, None, None)
        cur.execute("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
        assert cur.fetchone()[0] == original_acl
        cur.execute("SELECT count(*) FROM schema_migrations")
        assert cur.fetchone()[0] == 140


def test_committed_replay_and_real_restricted_runtime(settings, monkeypatch, tmp_path):
    dbname = "keel_m141_history_" + uuid.uuid4().hex[:10]
    control = psycopg2.connect(make_dsn(settings["admin"], dbname="postgres"))
    control.autocommit = True
    conn = runtime = seed = None
    try:
        with control.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {} WITH TEMPLATE keel_m141_test OWNER m103_installer")
                        .format(sql.Identifier(dbname)))
        conn = psycopg2.connect(make_dsn(settings["installer"], dbname=dbname))
        (tmp_path / compat.FILENAME).write_text(SOURCE, encoding="utf-8")
        monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
        assert runner.run(conn) == [compat.FILENAME]
        monkeypatch.setattr(runner, "_apply_sql_file", lambda *args: pytest.fail("Committed migration replayed"))
        assert runner.run(conn) == []
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            assert cur.fetchone()[0] == 141
        password = secrets.token_urlsafe(32)
        pairs = [(str(uuid.uuid4()), str(uuid.uuid4())) for _ in range(2)]
        seed = psycopg2.connect(make_dsn(settings["admin"], dbname=dbname))
        with seed.cursor() as cur:
            cur.execute("ALTER ROLE ceopro_billing_setup PASSWORD %s", (password,))
            for tenant, user in pairs:
                cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) "
                            "VALUES(%s,'Synthetic installer test','JO','JOD')", (tenant,))
                cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login')",
                            (user, user + "@example.com"))
                cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
                            (tenant, user))
        seed.commit()
        runtime = psycopg2.connect(make_dsn(settings["installer"], dbname=dbname,
                                          user=compat.SETUP, password=password))
        with runtime.cursor() as cur:
            cur.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone() == (compat.SETUP, False, False)
            for tenant, user in pairs:
                cur.execute("SELECT set_config('app.current_tenant_id',%s,true),"
                            "set_config('app.current_user_id',%s,true)", (tenant, user))
                cur.execute("SELECT billing_setup_trial('m141_missing_plan',false)")
                assert cur.fetchone()[0] == {"reason": "plan_has_no_trial"}
            for tenant, actor in ((pairs[1][0], pairs[0][1]), (pairs[0][0], "")):
                cur.execute("SELECT set_config('app.current_tenant_id',%s,true),"
                            "set_config('app.current_user_id',%s,true)", (tenant, actor))
                cur.execute("SAVEPOINT denied")
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute("SELECT billing_setup_trial('m141_missing_plan',false)")
                cur.execute("ROLLBACK TO SAVEPOINT denied")
            cur.execute("SAVEPOINT forbidden")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM billing_subscriptions")
            cur.execute("ROLLBACK TO SAVEPOINT forbidden")
        with seed.cursor() as cur:
            cur.execute("SELECT (SELECT count(*) FROM billing_trials),"
                        "(SELECT count(*) FROM tenant_plan_assignments)")
            assert cur.fetchone() == (0, 0)
    finally:
        for connection in (runtime, seed, conn):
            if connection is not None:
                connection.close()
        with control.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(dbname)))
            cur.execute("DROP ROLE IF EXISTS ceopro_billing_setup,ceopro_trial_issuer")
        control.close()
