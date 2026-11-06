"""Real PostgreSQL 17 tests; only a dedicated loopback 141-migration baseline.

No existing application/cloud database is accepted. Full-sequence cases clone
this baseline, exercise actual restricted logins, and remove their own clones.
"""

import os
import secrets
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import cursor, make_dsn, parse_dsn
import pytest

from scripts import apply_migrations as runner
from scripts import migration_remaining_compat as compat
from scripts.migration_103_compat import _memberships


FILES = sorted(runner.MIGRATIONS_DIR.glob("*.sql"))
REVIEWED = [FILES[i - 1] for i in (142, 143, 144, 165)]


@pytest.fixture(scope="module")
def settings():
    values = {k: os.getenv("KEEL_MREMAINING_TEST_" + k.upper() + "_DSN") for k in ("admin", "installer")}
    if not all(values.values()):
        pytest.skip("Dedicated local remaining-migration test DSNs required")
    parsed = [parse_dsn(v) for v in values.values()]
    assert all(p["host"] == "127.0.0.1" and p["dbname"] == "keel_remaining_test" for p in parsed)
    assert parsed[0]["port"] == parsed[1]["port"]
    for mode, dsn in values.items():
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            assert conn.server_version >= 170000
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone()[0] is (mode == "admin")
            cur.execute("SELECT count(*) FROM schema_migrations")
            assert cur.fetchone()[0] == 141
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
def installer(settings):
    conn = psycopg2.connect(settings["installer"])
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _prepare(conn, number):
    for path in FILES[141:number - 1]:
        runner._apply_sql_file(conn, path)


def _body(cur, signature=compat.TRIAL):
    cur.execute("SELECT prosrc FROM pg_proc WHERE oid=to_regprocedure(%s)", (signature,))
    return cur.fetchone()[0]


@pytest.mark.parametrize("number", [142, 143, 144, 165])
def test_original_sql_reproduces_owner_permission_failures(installer, number):
    _prepare(installer, number)
    with installer.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege) as error:
        cur.execute(FILES[number - 1].read_text(encoding="utf-8"))
    assert ("must be owner" if number in (142, 165) else "SET ROLE") in str(error.value)


@pytest.mark.parametrize("number", [142, 143, 144, 165])
def test_reviewed_migrations_restore_privileges_and_preserve_sql(authority, number):
    _prepare(authority, number)
    runner._apply_sql_file(authority, FILES[number - 1])
    source = FILES[number - 1].read_text(encoding="utf-8")
    with authority.cursor() as cur:
        for op in compat.MIGRATIONS[FILES[number - 1].name][1]:
            oid = compat._role(cur, op.owner)
            compat._function(cur, op, oid, body=op.body)
            # Function body is literally the historical migration body.
            marker = ("CREATE OR REPLACE FUNCTION " if op.previous_body else "CREATE FUNCTION ")
            start = source.lower().index(marker.lower() + op.function.split("(")[0].lower())
            original_body = source[start:].split("AS $$", 1)[1].split("$$;", 1)[0]
            assert _body(cur, op.function) == original_body
            cur.execute("SELECT has_schema_privilege(%s,'public','CREATE')", (op.owner,))
            assert cur.fetchone() == (False,)
            cur.execute("SELECT bool_or(inherit_option OR set_option) FROM pg_auth_members WHERE roleid=%s", (oid,))
            assert cur.fetchone()[0] in (None, False)
        cur.execute("SELECT current_user=session_user")
        assert cur.fetchone() == (True,)


@pytest.mark.parametrize("path", REVIEWED, ids=lambda p: p.name)
def test_source_and_filename_allowlist(installer, path):
    source = path.read_text(encoding="utf-8")
    with installer.cursor() as cur:
        for filename, content in ((path.name, source + "\n-- altered"), ("unreviewed.sql", source)):
            with pytest.raises(RuntimeError, match="immutable SQL"):
                compat.apply(cur, filename, content)


def test_autocommit_is_rejected(installer):
    installer.autocommit = True
    with installer.cursor() as cur, pytest.raises(RuntimeError, match="requires a transaction"):
        compat.apply(cur, REVIEWED[0].name, REVIEWED[0].read_text(encoding="utf-8"))
    installer.autocommit = False


@pytest.mark.parametrize("inherit,can_set,admin", [(False, False, False), (True, False, False),
                                                  (False, True, False), (True, True, False)])
@pytest.mark.parametrize("number", [142, 143])
def test_existing_membership_options_are_exactly_restored(installer, inherit, can_set, admin, number):
    _prepare(installer, number)
    owner = compat.ISSUER if number == 142 else compat.LOOKUP
    with installer.cursor() as cur:
        if number == 143:
            source = FILES[142].read_text(encoding="utf-8")
            cur.execute(source.split("-- Receipt access")[0])
        cur.execute(sql.SQL("GRANT {} TO CURRENT_USER WITH ADMIN {},INHERIT {},SET {} GRANTED BY CURRENT_USER")
                    .format(sql.Identifier(owner), *(sql.SQL("TRUE" if f else "FALSE") for f in (admin, inherit, can_set))))
        cur.execute("SELECT oid FROM pg_roles WHERE rolname=%s", (owner,))
        oid = cur.fetchone()[0]
        original = _memberships(cur, oid)
        schema_acl, context = compat._schema_acl(cur), compat._context(cur)
    runner._apply_sql_file(installer, FILES[number - 1])
    with installer.cursor() as cur:
        assert _memberships(cur, oid) == original
        assert compat._context(cur) == context
        # Migration 143 legitimately adds schema USAGE for four new roles.
        if number == 142:
            assert compat._schema_acl(cur) == schema_acl


@pytest.mark.parametrize("mutation,match", [
    ("ALTER ROLE ceopro_trial_issuer BYPASSRLS", "attributes"),
    ("ALTER ROLE ceopro_trial_issuer SUPERUSER", "attributes"),
    ("ALTER ROLE ceopro_trial_issuer LOGIN", "attributes"),
    ("ALTER ROLE ceopro_trial_issuer CREATEDB", "attributes"),
    ("ALTER ROLE ceopro_trial_issuer CREATEROLE", "attributes"),
    ("ALTER ROLE ceopro_trial_issuer INHERIT", "attributes"),
    ("ALTER ROLE ceopro_trial_issuer REPLICATION", "attributes"),
    ("ALTER ROLE ceopro_billing_setup BYPASSRLS", "attributes"),
    ("GRANT ceopro_app TO ceopro_trial_issuer", "membership"),
    ("GRANT ceopro_trial_issuer TO ceopro_app", "membership"),
    ("GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer", "DDL"),
    ("CREATE TABLE unexpected_owned_table(n integer); ALTER TABLE unexpected_owned_table OWNER TO ceopro_trial_issuer", "ownership"),
    ("CREATE FUNCTION unexpected_owned_function() RETURNS integer LANGUAGE sql AS 'SELECT 1'; "
     "ALTER FUNCTION unexpected_owned_function() OWNER TO ceopro_trial_issuer", "unexpected functions"),
    ("GRANT EXECUTE ON FUNCTION billing_setup_trial(text,boolean) TO PUBLIC", "execution ACL"),
    ("GRANT EXECUTE ON FUNCTION billing_setup_trial(text,boolean) TO ceopro_app", "execution ACL"),
    ("GRANT EXECUTE ON FUNCTION billing_setup_trial(text,boolean) TO ceopro_billing_setup WITH GRANT OPTION", "execution ACL"),
    ("ALTER FUNCTION billing_setup_trial(text,boolean) RESET search_path", "definer"),
    ("ALTER FUNCTION billing_setup_trial(text,boolean) OWNER TO m103_installer", "owner"),
    ("ALTER TABLE billing_trials NO FORCE ROW LEVEL SECURITY", "FORCE RLS"),
    ("CREATE OR REPLACE FUNCTION billing_setup_trial(p_plan text,p_start boolean DEFAULT false) RETURNS jsonb LANGUAGE sql "
     "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS 'SELECT null::jsonb'", "body"),
])
def test_unsafe_preconditions_fail_closed(settings, mutation, match):
    conn = psycopg2.connect(settings["admin"])
    try:
        with conn.cursor() as cur:
            cur.execute(mutation)
            cur.execute("SET LOCAL ROLE m103_installer")
        with pytest.raises(RuntimeError, match=match):
            runner._apply_sql_file(conn, REVIEWED[0])
    finally:
        conn.rollback()
        conn.close()


def test_installer_requires_existing_admin_authority(settings):
    conn = psycopg2.connect(settings["admin"])
    try:
        with conn.cursor() as cur:
            cur.execute("REVOKE ceopro_trial_issuer FROM m103_installer CASCADE")
            cur.execute("SET LOCAL ROLE m103_installer")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            runner._apply_sql_file(conn, REVIEWED[0])
        with conn.cursor() as cur:
            cur.execute("SELECT pg_has_role(current_user,'ceopro_trial_issuer','USAGE')")
            assert cur.fetchone() == (False,)
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("number,operation", [(142, 0), (143, 0), (143, 3), (144, 0), (165, 0), (165, 4)])
def test_failure_inside_privilege_window_restores_savepoint_and_file(installer, number, operation):
    _prepare(installer, number)
    source = FILES[number - 1].read_text(encoding="utf-8")
    op = compat.MIGRATIONS[FILES[number - 1].name][1][operation]
    block = "".join(source.splitlines(keepends=True)[op.first - 1:op.last])

    class FailInWindow(cursor):
        def execute(self, query, parameters=None):
            result = super().execute(query, parameters)
            if query == block:
                super().execute("SELECT pg_has_role(current_user,%s,'USAGE')", (op.owner,))
                assert self.fetchone() == (True,)
                super().execute("SELECT has_schema_privilege(%s,'public','CREATE')", (op.owner,))
                assert self.fetchone() == (not bool(op.previous_body),)
                super().execute("SELECT 1/0")
            return result

    installer.cursor_factory = FailInWindow
    # Catch immediately after the helper's savepoint rollback, without relying
    # on a caller rollback to clear temporary grants.
    with pytest.raises(psycopg2.errors.DivisionByZero):
        runner._apply_sql_file(installer, FILES[number - 1])
    with installer.cursor() as cur:
        cur.execute("SELECT has_schema_privilege(%s,'public','CREATE'),"
                    "pg_has_role(current_user,%s,'USAGE'),pg_has_role(current_user,%s,'SET')", (op.owner,) * 3)
        assert cur.fetchone() == (False, False, False)
    installer.rollback()
    with installer.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_migrations")
        assert cur.fetchone() == (141,)
        assert compat._hash(_body(cur)) == compat.BODY_141


def test_runner_failure_does_not_record_migration(installer, monkeypatch, tmp_path):
    path = tmp_path / REVIEWED[0].name
    path.write_bytes(REVIEWED[0].read_bytes())
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
    original = runner._apply_sql_file

    def fail_after_apply(conn, path):
        original(conn, path)
        with conn.cursor() as cur:
            cur.execute("SELECT 1/0")

    monkeypatch.setattr(runner, "_apply_sql_file", fail_after_apply)
    with pytest.raises(psycopg2.errors.DivisionByZero):
        runner.run(installer)
    with installer.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_migrations")
        assert cur.fetchone() == (141,)
        assert compat._hash(_body(cur)) == compat.BODY_141


def _denied(cur, query, parameters=None):
    cur.execute("SAVEPOINT forbidden")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        cur.execute(query, parameters)
    cur.execute("ROLLBACK TO SAVEPOINT forbidden")


@pytest.mark.parametrize("mode", ["installer", "admin"])
def test_complete_remaining_sequence_replay_and_real_runtime(settings, monkeypatch, mode):
    dbname = "keel_remaining_history_" + uuid.uuid4().hex[:10]
    control = psycopg2.connect(make_dsn(settings["admin"], dbname="postgres"))
    control.autocommit = True
    conn = seed = None
    runtimes = []
    password = secrets.token_urlsafe(32)
    pairs = [(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())) for _ in range(2)]
    try:
        with control.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {} WITH TEMPLATE keel_remaining_test OWNER m103_installer")
                        .format(sql.Identifier(dbname)))
        seed = psycopg2.connect(make_dsn(settings["admin"], dbname=dbname))
        with seed.cursor() as cur:
            for tenant, user, product in pairs:
                cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) "
                            "VALUES(%s,'Synthetic migration sequence','JO','JOD')", (tenant,))
                cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login')",
                            (user, user + "@example.com"))
                cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant, user))
                cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) "
                            "VALUES(%s,%s,'{\"en\":\"Synthetic migration product\"}',7,'JOD')", (product, tenant))
                cur.execute("INSERT INTO invoices(tenant_id,invoice_number,total_amount,currency) "
                            "VALUES(%s,'synthetic-installer',7,'JOD')", (tenant,))
        seed.commit()
        conn = psycopg2.connect(make_dsn(settings[mode], dbname=dbname))
        assert runner.run(conn) == [p.name for p in FILES[141:]]
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            assert cur.fetchone() == (168,)
            for name in (compat.ISSUER, compat.LOOKUP, compat.WRITER, compat.SETUP, compat.WEBHOOK, compat.ACCOUNTING):
                oid = compat._role(cur, name)
                assert all(not r[3] and not r[4] for r in _memberships(cur, oid))
            for _, ops in compat.MIGRATIONS.values():
                for op in ops:
                    compat._function(cur, op, compat._role(cur, op.owner),
                                     body=compat.BODY_165 if op.function == compat.TRIAL else "")
            cur.execute("SELECT product_id::text,current_price,currency FROM products ORDER BY product_id")
            assert {(r[0], str(r[1]), r[2]) for r in cur.fetchall()} == {
                (p[2], '7.0000', 'JOD') for p in pairs}
            cur.execute("SELECT tenant_id::text,total_amount,currency FROM invoices")
            assert {(r[0], str(r[1]), r[2]) for r in cur.fetchall()} == {
                (p[0], '7.0000', 'JOD') for p in pairs}
            cur.execute("SELECT count(*),bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class "
                        "WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)",
                        (list(compat.RLS_TABLES) + ['products', 'invoices', 'billing_trial_checkouts'],))
            assert cur.fetchone() == (len(compat.RLS_TABLES) + 3, True)
            cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm')")
            assert {r[0] for r in cur.fetchall()} == {'vector', 'pg_trgm'}
            cur.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit,rolreplication "
                        "FROM pg_roles WHERE rolname='ceopro_image_worker'")
            assert cur.fetchone() == (False,) * 6
        conn.commit()
        monkeypatch.setattr(runner, "_apply_sql_file", lambda *args: pytest.fail("Committed migration replayed"))
        assert runner.run(conn) == []
        with seed.cursor() as cur:
            for role in ("ceopro_app", compat.SETUP, compat.WEBHOOK, compat.ACCOUNTING):
                cur.execute(sql.SQL("ALTER ROLE {} PASSWORD %s").format(sql.Identifier(role)), (password,))
        seed.commit()
        for role in ("ceopro_app", compat.SETUP, compat.WEBHOOK, compat.ACCOUNTING):
            runtime = psycopg2.connect(make_dsn(settings["installer"], dbname=dbname, user=role, password=password))
            runtimes.append(runtime)
            with runtime.cursor() as cur:
                cur.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit,rolreplication "
                            "FROM pg_roles WHERE rolname=current_user")
                # ceopro_app's historical INHERIT flag is unchanged; it has no
                # memberships. Dedicated billing logins are explicitly NOINHERIT.
                assert cur.fetchone() == (False, False, False, False, role == 'ceopro_app', False)
                cur.execute("SELECT count(*) FROM pg_auth_members WHERE member="
                            "(SELECT oid FROM pg_roles WHERE rolname=current_user)")
                assert cur.fetchone() == (0,)
                tenant, user, product = pairs[0]
                cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)", (tenant, user))
                if role == "ceopro_app":
                    for tenant, user, product in pairs:
                        cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)", (tenant, user))
                        cur.execute("SELECT product_id::text FROM products")
                        assert cur.fetchall() == [(product,)]
                        cur.execute("SELECT tenant_id::text,total_amount,currency FROM invoices")
                        assert cur.fetchall() == [(tenant, 7, 'JOD')]
                        other = next(p[2] for p in pairs if p[0] != tenant)
                        cur.execute("UPDATE products SET current_price=99 WHERE product_id=%s", (other,))
                        assert cur.rowcount == 0
                        cur.execute("UPDATE invoices SET total_amount=99 WHERE tenant_id<>%s", (tenant,))
                        assert cur.rowcount == 0
                    _denied(cur, "SELECT billing_setup_trial('missing',false)")
                    _denied(cur, "SELECT billing_provider_tenant('customer','missing')")
                elif role == compat.SETUP:
                    cur.execute("SELECT billing_setup_trial('missing',false)")
                    assert cur.fetchone()[0] == {"reason": "plan_has_no_trial"}
                    _denied(cur, "SELECT billing_setup_trial('missing',true)")
                    cur.execute("SELECT set_config('app.current_user_id',%s,true)", (pairs[1][1],))
                    _denied(cur, "SELECT billing_setup_trial('missing',false)")
                    _denied(cur, "DELETE FROM billing_subscriptions")
                elif role == compat.WEBHOOK:
                    cur.execute("SELECT billing_provider_tenant('customer','missing')")
                    assert cur.fetchone() == (None,)
                    _denied(cur, "SELECT billing_confirm_trial_checkout(%s,'missing','missing',now(),now()+interval '1 day')", (str(uuid.uuid4()),))
                else:
                    cur.execute("SELECT billing_accounting_principal(%s,%s)", (tenant, user))
                    assert cur.fetchone() == (True,)
                    cur.execute("SELECT billing_accounting_principal(%s,%s)", (pairs[1][0], pairs[1][1]))
                    assert cur.fetchone() == (False,)
                    _denied(cur, "UPDATE tenant_users SET role_key='owner'")
        with seed.cursor() as cur:
            cur.execute("SELECT (SELECT count(*) FROM billing_trials),(SELECT count(*) FROM tenant_plan_assignments),"
                        "(SELECT count(*) FROM billing_subscriptions),(SELECT count(*) FROM usage_ledger)")
            assert cur.fetchone() == (0, 0, 0, 0)
    finally:
        for connection in [*runtimes, seed, conn]:
            if connection is not None:
                connection.close()
        with control.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(dbname)))
            cur.execute("DROP ROLE IF EXISTS ceopro_billing_webhook,ceopro_credit_accounting,"
                        "ceopro_billing_lookup,ceopro_schedule_writer,ceopro_image_worker")
        control.close()
