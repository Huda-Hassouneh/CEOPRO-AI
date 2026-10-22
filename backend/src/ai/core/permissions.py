"""
KEEL - what each team role may do through the REST API.

The assistant already limits what each role can read (rag/access.py: staff see products and stock
only; accountants add sales and costs; owners, admins and managers see everything). The REST
endpoints behind the screens did not apply the same limits, so a staff member could call them
directly and read sales, costs and the full sales export, or change the catalog, although the
product describes that role as read-only. These dependencies close that gap with the same role
table, read fresh from the database on every request so a role change applies at once.
"""
from fastapi import Depends, HTTPException, Request

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.rag import access

# Roles that may look but not change anything (settings.roles.staff.description: "Read-only access").
READ_ONLY_ROLES = frozenset({"staff"})
_READ_METHODS = ("GET", "HEAD", "OPTIONS")
FORBIDDEN_DETAIL = "Your role doesn't allow this."


def _current_role(ctx: TenantContext):
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
                (ctx.tenant_id, ctx.user_id),
            )
            row = cursor.fetchone()
        conn.commit()
        return row[0] if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def forbid_read_only_writes(request: Request, ctx: TenantContext = Depends(get_tenant_context)) -> None:
    """For a router whose non-GET endpoints change company data: read-only roles get 403."""
    if request.method in _READ_METHODS:
        return
    if _current_role(ctx) in READ_ONLY_ROLES:
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)


def require_capabilities(*needed: str):
    """For an endpoint that returns data of the given kinds (access.SALES, access.COSTS, ...)."""
    def dependency(ctx: TenantContext = Depends(get_tenant_context)) -> None:
        if not access.for_role(_current_role(ctx)).allows(*needed):
            raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)

    return Depends(dependency)
