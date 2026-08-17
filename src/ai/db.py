"""
CEOPRO AI - Shared tenant-context helper for src/ai/.

Every data_access.py query already filters WHERE tenant_id = %s explicitly -
this is about Postgres's own defense-in-depth layer, Row-Level Security,
which only actually restricts anything when (a) the connecting role isn't a
superuser - confirmed empirically that FORCE ROW LEVEL SECURITY has zero
effect on a superuser connection, which is what this app connected as before
migrations/20260808020000_add_app_role_and_force_rls.sql added a genuinely
non-superuser ceopro_app role - and (b) app.current_tenant_id is set on the
session before each query runs.

Call set_tenant_context() at the start of every unit of work (once per
request, once per consumed message), not once at connection-open time -
this codebase's connections are long-lived and multi-tenant over their
lifetime (e.g. forecasting/consumer.py holds one connection across many
Redis stream messages, each for a potentially different tenant), so the
tenant a connection is scoped to can change message to message.
"""


def set_tenant_context(conn, tenant_id: str) -> None:
    """
    Uses a plain session-level SET, not SET LOCAL, since this project's
    connections aren't pooled (each consumer/process holds its own
    long-lived connection, not borrowed from a shared pool) - a pooled setup
    would need SET LOCAL scoped to a transaction instead, to avoid leaking
    tenant context to whichever caller reuses the connection next.
    """
    with conn.cursor() as cursor:
        cursor.execute("SET app.current_tenant_id = %s;", (str(tenant_id),))
