"""Transactional installer compatibility for the exact immutable migration 141."""

import hashlib

from psycopg2 import sql

from scripts.migration_103_compat import _memberships


FILENAME = "20261112000000_billing_setup_service.sql"
SOURCE_SHA256 = "c1a3fcc2dcfb0ab89338f17407619b4d223ffeaf4f5f82c4208f085c0b087826"
OWNER = "ceopro_trial_issuer"
SETUP = "ceopro_billing_setup"
FUNCTION = "public.billing_setup_trial(text,boolean)"
TRANSFER = (
    "ALTER FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) OWNER TO ceopro_trial_issuer;\n"
    "REVOKE ALL ON FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) FROM PUBLIC;\n"
    "GRANT EXECUTE ON FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) TO ceopro_billing_setup;"
)
RLS_TABLES = ["tenant_users", "billing_trials", "tenant_plan_assignments",
              "billing_subscriptions", "billing_checkout_attempts", "billing_customers"]


def _verify_roles(cur):
    roles = {}
    for name, login in ((OWNER, False), (SETUP, True)):
        cur.execute("SELECT oid,rolsuper,rolbypassrls,rolcanlogin,rolcreatedb,rolcreaterole,"
                    "rolinherit,rolreplication FROM pg_roles WHERE rolname=%s", (name,))
        row = cur.fetchone()
        if row is None or row[1:] != (False, False, login, False, False, False, False):
            raise RuntimeError("Migration 141 restricted role attributes are unsafe")
        oid = row[0]
        cur.execute(
            "SELECT EXISTS(SELECT FROM pg_auth_members WHERE member=%s) "
            "OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=%s "
            "AND member<>(SELECT oid FROM pg_roles WHERE rolname=current_user)) "
            "OR EXISTS(SELECT FROM pg_class WHERE relowner=%s) "
            "OR EXISTS(SELECT FROM pg_namespace WHERE nspowner=%s) "
            "OR EXISTS(SELECT FROM pg_database WHERE datdba=%s) "
            "OR has_schema_privilege(%s,'public','CREATE') "
            "OR has_database_privilege(%s,current_database(),'CREATE')",
            (oid, oid, oid, oid, oid, name, name),
        )
        if cur.fetchone()[0]:
            raise RuntimeError("Migration 141 role membership, ownership or DDL is unsafe")
        roles[name] = oid
    return roles


def _verify_result(cur):
    roles = _verify_roles(cur)
    cur.execute("SELECT proowner,prosecdef,proconfig FROM pg_proc WHERE oid=to_regprocedure(%s)",
                (FUNCTION,))
    if cur.fetchone() != (roles[OWNER], True, ["search_path=pg_catalog, public, pg_temp"]):
        raise RuntimeError("Migration 141 function owner or definer configuration is unsafe")
    cur.execute("SELECT grantee,privilege_type,is_grantable FROM pg_proc p, "
                "LATERAL aclexplode(COALESCE(proacl,acldefault('f',proowner))) a "
                "WHERE p.oid=to_regprocedure(%s)", (FUNCTION,))
    if set(cur.fetchall()) != {(roles[OWNER], "EXECUTE", False), (roles[SETUP], "EXECUTE", False)}:
        raise RuntimeError("Migration 141 function execution ACL is unsafe")
    cur.execute("SELECT count(*) FROM pg_proc WHERE proowner=ANY(%s)", (list(roles.values()),))
    if cur.fetchone()[0] != 1:
        raise RuntimeError("Migration 141 roles own unexpected functions")
    cur.execute("SELECT count(*),bool_and(relrowsecurity AND relforcerowsecurity) "
                "FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)",
                (RLS_TABLES,))
    if cur.fetchone() != (len(RLS_TABLES), True):
        raise RuntimeError("Migration 141 required FORCE RLS is not established")


def apply(cur, source):
    if hashlib.sha256(source.encode()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Migration 141 source differs from the reviewed immutable SQL")
    if cur.connection.autocommit:
        raise RuntimeError("Migration 141 compatibility requires a transaction")
    cur.execute("SELECT oid,rolname,rolsuper FROM pg_roles WHERE rolname=current_user")
    installer_oid, installer, superuser = cur.fetchone()
    if superuser:
        cur.execute(source)
        _verify_result(cur)
        return
    if cur.connection.server_version < 160000:
        raise RuntimeError("Non-superuser migration 141 requires PostgreSQL 16 or newer")
    before, after = source.split(TRANSFER)
    cur.execute(before)  # All original role checks, grants, policies and function body.
    owner_oid = _verify_roles(cur)[OWNER]
    original = _memberships(cur, owner_oid)
    cur.execute("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
    schema_acl = cur.fetchone()[0]
    cur.execute("SELECT pg_has_role(current_user,%s,'SET') "
                "AND pg_has_role(current_user,%s,'USAGE')", (owner_oid, owner_oid))
    authorized = cur.fetchone()[0]
    # OWNER TO also requires CREATE for the new owner. Keep it uncommitted and
    # limited to the transfer/ACL block; the original tail rejects retained DDL.
    cur.execute("GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer")
    if not authorized:
        cur.execute(sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET TRUE GRANTED BY {}")
                    .format(sql.Identifier(OWNER), sql.Identifier(installer), sql.Identifier(installer)))
    cur.execute(TRANSFER)
    cur.execute("REVOKE CREATE ON SCHEMA public FROM ceopro_trial_issuer")
    if not authorized:
        previous = next((r for r in original if r[:2] == (installer_oid, installer_oid)), None)
        if previous is None:
            cur.execute(sql.SQL("REVOKE {} FROM {} GRANTED BY {}")
                        .format(sql.Identifier(OWNER), sql.Identifier(installer), sql.Identifier(installer)))
        else:
            cur.execute(sql.SQL("GRANT {} TO {} WITH ADMIN {}, INHERIT {}, SET {} GRANTED BY {}")
                        .format(sql.Identifier(OWNER), sql.Identifier(installer),
                                *(sql.SQL("TRUE" if flag else "FALSE") for flag in previous[2:]),
                                sql.Identifier(installer)))
    if _memberships(cur, owner_oid) != original:
        raise RuntimeError("Migration 141 installer memberships were not restored")
    cur.execute("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
    if cur.fetchone()[0] != schema_acl:
        raise RuntimeError("Migration 141 schema permissions were not restored")
    cur.execute(after)  # Original promotion ACLs, policies and final DDL guards.
    _verify_result(cur)
