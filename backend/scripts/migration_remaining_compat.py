"""Installer-only handling of four immutable, reviewed function-owner migrations.

No SQL is rewritten. Line spans are meaningful only with the exact source hash.
Temporary grants surround those spans, never an arbitrary migration or callback.
"""

from dataclasses import dataclass
import hashlib

from psycopg2 import sql

from scripts.migration_103_compat import _memberships


@dataclass(frozen=True)
class Operation:
    first: int
    last: int
    function: str
    owner: str
    caller: str
    previous_body: str = ""
    body: str = ""


ISSUER = "ceopro_trial_issuer"
LOOKUP = "ceopro_billing_lookup"
WRITER = "ceopro_schedule_writer"
SETUP = "ceopro_billing_setup"
WEBHOOK = "ceopro_billing_webhook"
ACCOUNTING = "ceopro_credit_accounting"
TRIAL = "public.billing_setup_trial(text,boolean)"
BODY_141 = "b63a8739b13efb1edebc19459d93b3fa89fa7a53dead9fbec9b755032ae43b81"
BODY_142 = "4c9bd4ceceb5725bf201ee550044835b77a89e5b63d35df2c7245846d1fc21f3"
BODY_165 = "b1442167afa340bab3fab9173e142d98f52b5fff09bd8016c6843efcf1d66d1e"
MIGRATIONS = {
    "20261112000100_billing_setup_command_guards.sql": (
        "d051bc881dd30b538e5238879846958cebffd1aac21f996659c7a2161c68c07e",
        (Operation(3, 29, TRIAL, ISSUER, SETUP, BODY_141, BODY_142),)),
    "20261113000000_billing_reconciliation_roles.sql": (
        "3259aefc1155c0b227f1b8abfa54bbafa51879081ec2edfeaac5d2c35c9c53a7",
        (Operation(59, 61, "public.billing_provider_tenant(text,text)", LOOKUP, WEBHOOK),
         Operation(68, 70, "public.billing_provider_month_spend(text,text,timestamptz)", LOOKUP, ACCOUNTING),
         Operation(76, 78, "public.billing_expired_credit_tenants(integer)", LOOKUP, ACCOUNTING),
         Operation(209, 211, "public.billing_setup_schedule(text,text,text)", WRITER, SETUP))),
    "20261113000100_billing_context_guards.sql": (
        "e005e44a285047413c7d5ce3ecc674b5ee7f6a4b5aa727a8e45394fcc47b6bbe",
        (Operation(14, 16, "public.billing_accounting_principal(uuid,uuid)", WRITER, ACCOUNTING),)),
    "20261127000000_provider_backed_trials.sql": (
        "2094b613bd025cbd2230f98e12faa75ae515fa80cb35406e78ab0d2b3a0b9ded",
        (Operation(51, 69, TRIAL, ISSUER, SETUP, BODY_142, BODY_165),
         Operation(101, 103, "public.billing_reserve_trial_checkout(uuid,text,text)", ISSUER, SETUP),
         Operation(112, 114, "public.billing_release_trial_checkout(uuid)", ISSUER, SETUP),
         Operation(127, 129, "public.billing_expire_trial_checkout(uuid,text)", ISSUER, WEBHOOK),
         Operation(155, 157, "public.billing_confirm_trial_checkout(uuid,text,text,timestamptz,timestamptz)", ISSUER, WEBHOOK))),
}
OWNED_FUNCTIONS = {role: {op.function for _, ops in MIGRATIONS.values() for op in ops if op.owner == role}
                   for role in (ISSUER, LOOKUP, WRITER)}
RLS_TABLES = ("companies", "tenant_users", "billing_trials", "tenant_plan_assignments",
              "billing_subscriptions", "billing_checkout_attempts", "billing_customers",
              "billing_webhook_events", "usage_ledger", "tenant_credit_balances")


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _role(cur, name):
    cur.execute("SELECT oid,rolsuper,rolbypassrls,rolcanlogin,rolcreatedb,rolcreaterole,"
                "rolinherit,rolreplication FROM pg_roles WHERE rolname=%s", (name,))
    row = cur.fetchone()
    if row is None or row[1:] != (False, False, name in (SETUP, WEBHOOK, ACCOUNTING), False, False, False, False):
        raise RuntimeError("Reviewed migration role attributes are unsafe: " + name)
    oid = row[0]
    cur.execute(
        "SELECT EXISTS(SELECT FROM pg_auth_members WHERE member=%s) "
        "OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=%s AND member NOT IN "
        "((SELECT oid FROM pg_roles WHERE rolname=current_user),"
        " (SELECT datdba FROM pg_database WHERE datname=current_database()))) "
        "OR EXISTS(SELECT FROM pg_class WHERE relowner=%s) "
        "OR EXISTS(SELECT FROM pg_namespace WHERE nspowner=%s) "
        "OR EXISTS(SELECT FROM pg_database WHERE datdba=%s) "
        "OR has_schema_privilege(%s,'public','CREATE') "
        "OR has_database_privilege(%s,current_database(),'CREATE')",
        (oid, oid, oid, oid, oid, name, name))
    if cur.fetchone()[0]:
        raise RuntimeError("Reviewed migration role membership, ownership or DDL is unsafe: " + name)
    cur.execute("SELECT p.oid::regprocedure::text FROM pg_proc p WHERE proowner=%s", (oid,))
    # Normalize allowed signatures through regprocedure too (public is omitted
    # for visible functions).
    owned = {r[0] for r in cur.fetchall()}
    allowed = set()
    for signature in OWNED_FUNCTIONS.get(name, ()):
        cur.execute("SELECT to_regprocedure(%s)::text", (signature,))
        allowed.add(cur.fetchone()[0])
    if not owned <= allowed:
        raise RuntimeError("Reviewed migration role owns unexpected functions: " + name)
    return oid


def _function(cur, op, owner, *, acl=True, body=""):
    cur.execute("SELECT proowner,prosecdef,proconfig,proleakproof,prosrc FROM pg_proc "
                "WHERE oid=to_regprocedure(%s)", (op.function,))
    row = cur.fetchone()
    if row is None or row[:4] != (owner, True, ["search_path=pg_catalog, public, pg_temp"], False):
        raise RuntimeError("Reviewed function owner or definer protection is unsafe: " + op.function)
    if body and _hash(row[4]) != body:
        raise RuntimeError("Reviewed function body differs: " + op.function)
    if acl:
        cur.execute("SELECT oid FROM pg_roles WHERE rolname=%s", (op.caller,))
        caller = cur.fetchone()
        cur.execute("SELECT grantor,grantee,privilege_type,is_grantable FROM pg_proc p, "
                    "LATERAL aclexplode(COALESCE(proacl,acldefault('f',proowner))) a "
                    "WHERE p.oid=to_regprocedure(%s)", (op.function,))
        if caller is None or set(cur.fetchall()) != {(owner, owner, "EXECUTE", False),
                                                    (owner, caller[0], "EXECUTE", False)}:
            raise RuntimeError("Reviewed function execution ACL is unsafe: " + op.function)
    return _hash(row[4])


def _context(cur):
    cur.execute("SELECT current_user,session_user,current_setting('role'),current_setting('search_path')")
    return cur.fetchone()


def _schema_acl(cur):
    cur.execute("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
    return cur.fetchone()[0]


def _operation(cur, op, block, installer_oid, installer, superuser):
    owner_oid = _role(cur, op.owner)
    _role(cur, op.caller)
    old_body = _function(cur, op, owner_oid if op.previous_body else installer_oid,
                         acl=bool(op.previous_body), body=op.previous_body)
    original = _memberships(cur, owner_oid)
    schema_acl, context = _schema_acl(cur), _context(cur)
    cur.execute("SAVEPOINT reviewed_function_owner")
    try:
        changed = False
        if not superuser:
            cur.execute("SELECT pg_has_role(current_user,%s,'USAGE'),pg_has_role(current_user,%s,'SET')",
                        (owner_oid, owner_oid))
            inherit, can_set = cur.fetchone()
            if not inherit or (not op.previous_body and not can_set):
                # Replacement needs inheritance only; transfers also need SET.
                cur.execute(sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET {} GRANTED BY {}")
                            .format(sql.Identifier(op.owner), sql.Identifier(installer),
                                    sql.SQL("TRUE" if can_set or not op.previous_body else "FALSE"),
                                    sql.Identifier(installer)))
                changed = True
            if not op.previous_body:
                cur.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(op.owner)))
        cur.execute(block)  # Exact original replacement or OWNER/REVOKE/GRANT span.
        if not superuser and not op.previous_body:
            cur.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(op.owner)))
        if changed:
            previous = next((r for r in original if r[:2] == (installer_oid, installer_oid)), None)
            if previous is None:
                cur.execute(sql.SQL("REVOKE {} FROM {} GRANTED BY {}")
                            .format(sql.Identifier(op.owner), sql.Identifier(installer), sql.Identifier(installer)))
            else:
                cur.execute(sql.SQL("GRANT {} TO {} WITH ADMIN {}, INHERIT {}, SET {} GRANTED BY {}")
                            .format(sql.Identifier(op.owner), sql.Identifier(installer),
                                    *(sql.SQL("TRUE" if f else "FALSE") for f in previous[2:]),
                                    sql.Identifier(installer)))
        if (_memberships(cur, owner_oid), _schema_acl(cur), _context(cur)) != (original, schema_acl, context):
            raise RuntimeError("Reviewed migration temporary privileges/context were not restored")
        _role(cur, op.owner)
        _function(cur, op, owner_oid, body=op.body or old_body)
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT reviewed_function_owner")
        cur.execute("RELEASE SAVEPOINT reviewed_function_owner")
        raise
    cur.execute("RELEASE SAVEPOINT reviewed_function_owner")


def apply(cur, filename, source):
    spec = MIGRATIONS.get(filename)
    if spec is None or _hash(source) != spec[0]:
        raise RuntimeError("Migration source differs from the reviewed immutable SQL")
    if cur.connection.autocommit:
        raise RuntimeError("Reviewed migration compatibility requires a transaction")
    cur.execute("SELECT oid,rolname,rolsuper FROM pg_roles WHERE rolname=current_user")
    installer_oid, installer, superuser = cur.fetchone()
    if not superuser and cur.connection.server_version < 160000:
        raise RuntimeError("Reviewed non-superuser migrations require PostgreSQL 16 or newer")
    lines, offset = source.splitlines(keepends=True), 0
    for op in spec[1]:
        prefix = lines[offset:op.first - 1]
        if any(line.strip() and not line.lstrip().startswith("--") for line in prefix):
            cur.execute("".join(prefix))
        _operation(cur, op, "".join(lines[op.first - 1:op.last]), installer_oid, installer, superuser)
        offset = op.last
    tail = "".join(lines[offset:])
    if any(line.strip() and not line.lstrip().startswith("--") for line in tail.splitlines()):
        cur.execute(tail)
    for op in spec[1]:
        _function(cur, op, _role(cur, op.owner), body=op.body)
        _role(cur, op.caller)
    cur.execute("SELECT count(*),bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class "
                "WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)", (list(RLS_TABLES),))
    if cur.fetchone() != (len(RLS_TABLES), True):
        raise RuntimeError("Reviewed migration required FORCE RLS is not established")
