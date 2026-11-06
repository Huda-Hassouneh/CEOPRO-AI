"""Installer-only compatibility for immutable migration 103 on PostgreSQL 17.

Keep applied SQL history intact. Verify the definer owner's security state
instead of issuing a superuser-only ALTER, and lend only the installer the
temporary SET/inheritance options needed for ownership and ACLs, in one transaction.
"""

import hashlib

from psycopg2 import sql


FILENAME = "20261031000000_add_durable_tenant_notifications.sql"
SOURCE_SHA256 = "1a3095178bd93ffb4dfe58abcfdf9c8678abb6f9faec254d2da3ba013a7defe3"
ROLE = "keel_notification_fn_owner"
ALTER = ("ALTER ROLE keel_notification_fn_owner\n"
         "    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;")


def _verify_owner(cur):
    cur.execute(
        "SELECT oid, rolsuper, rolbypassrls, rolcanlogin, rolcreatedb, "
        "rolcreaterole, rolinherit, rolreplication FROM pg_roles WHERE rolname=%s",
        (ROLE,),
    )
    row = cur.fetchone()
    if row is None or row[1:] != (False,) * 7:
        raise RuntimeError("Migration 103 definer owner has unsafe role attributes")
    # NOINHERIT alone does not prevent SET ROLE or delegated ADMIN privileges.
    # No outbound membership is necessary for this dedicated definer owner.
    cur.execute("SELECT 1 FROM pg_auth_members WHERE member=%s", (row[0],))
    if cur.fetchone():
        raise RuntimeError("Migration 103 definer owner has unexpected role membership")
    cur.execute(
        "SELECT EXISTS(SELECT FROM pg_class WHERE relowner=%s) "
        "OR EXISTS(SELECT FROM pg_namespace WHERE nspowner=%s) "
        "OR EXISTS(SELECT FROM pg_database WHERE datdba=%s) "
        "OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=%s "
        "AND member<>(SELECT oid FROM pg_roles WHERE rolname=current_user))",
        (row[0],) * 4,
    )
    if cur.fetchone()[0]:
        raise RuntimeError("Migration 103 definer owner has unexpected ownership or grantees")
    return row[0]


def _memberships(cur, oid):
    cur.execute(
        "SELECT grantor, member, admin_option, inherit_option, set_option "
        "FROM pg_auth_members WHERE roleid=%s ORDER BY grantor, member", (oid,),
    )
    return cur.fetchall()


def _verify_result(cur):
    oid = _verify_owner(cur)
    cur.execute(
        "SELECT count(*),bool_and(prosecdef),bool_or(EXISTS("
        "SELECT FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0 "
        "AND a.privilege_type='EXECUTE')) FROM pg_proc p WHERE proowner=%s", (oid,),
    )
    if cur.fetchone() != (7, True, False):
        raise RuntimeError("Migration 103 definer function security was not established")
    cur.execute(
        "SELECT relrowsecurity AND relforcerowsecurity, "
        "NOT has_schema_privilege(%s,'public','CREATE') "
        "FROM pg_class WHERE oid='public.notification_outbox'::regclass", (ROLE,),
    )
    if cur.fetchone() != (True, True):
        raise RuntimeError("Migration 103 RLS or schema restrictions were not established")


def apply(cur, source):
    if hashlib.sha256(source.encode()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Migration 103 source differs from the reviewed immutable SQL")
    if cur.connection.autocommit:
        raise RuntimeError("Migration 103 compatibility requires a transaction")
    before, after = source.split(ALTER)
    cur.execute(before)  # Original CREATE ROLE ... IF NOT EXISTS, unchanged.
    oid = _verify_owner(cur)
    cur.execute("SELECT oid, rolname, rolsuper FROM pg_roles WHERE rolname=current_user")
    installer_oid, installer, superuser = cur.fetchone()
    if superuser:
        # Preserve the original local-superuser execution path exactly.
        cur.execute(ALTER + after)
        _verify_result(cur)
        return
    if cur.connection.server_version < 160000:
        raise RuntimeError("Non-superuser migration 103 requires PostgreSQL 16 or newer")
    original = _memberships(cur, oid)
    cur.execute("SELECT pg_has_role(current_user,%s,'SET') "
                "AND pg_has_role(current_user,%s,'USAGE')", (oid, oid))
    already_authorized = cur.fetchone()[0]
    if not already_authorized:
        # No elevated role is granted to the definer owner or to a runtime role.
        # PostgreSQL still requires the installer's existing ADMIN authority.
        # SET permits OWNER TO; inheritance permits the following REVOKE/GRANT
        # statements after ownership has moved. Neither option may remain added.
        cur.execute(sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET TRUE GRANTED BY {}")
                    .format(sql.Identifier(ROLE), sql.Identifier(installer), sql.Identifier(installer)))
    cur.execute(after)  # All table, RLS, function, trigger and ACL SQL unchanged.
    if not already_authorized:
        previous = next((r for r in original if r[:2] == (installer_oid, installer_oid)), None)
        if previous is None:
            cur.execute(sql.SQL("REVOKE {} FROM {} GRANTED BY {}")
                        .format(sql.Identifier(ROLE), sql.Identifier(installer), sql.Identifier(installer)))
        else:
            cur.execute(sql.SQL("GRANT {} TO {} WITH ADMIN {}, INHERIT {}, SET {} GRANTED BY {}")
                        .format(sql.Identifier(ROLE), sql.Identifier(installer),
                                *(sql.SQL("TRUE" if flag else "FALSE") for flag in previous[2:]),
                                sql.Identifier(installer)))
    if _memberships(cur, oid) != original:
        raise RuntimeError("Migration 103 installer memberships were not restored")
    _verify_result(cur)
