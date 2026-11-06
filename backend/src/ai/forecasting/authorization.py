"""Execution-time authorization for demand forecasts."""

from uuid import UUID

from fastapi import HTTPException

from src.ai.core import usage

SYSTEM_ACTOR_USER_ID = "00000000-0000-0000-0000-000000000000"


def require_forecast_authorization(conn, tenant_id: str, actor_user_id: str) -> None:
    """Recheck the initiating principal and current feature grant on the worker connection."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT keel_active_principal(%s, %s);", (actor_user_id, tenant_id))
        row = cursor.fetchone()
    if not row or row[0] is not True:
        raise HTTPException(status_code=403, detail="An active tenant membership is required to generate forecasts.")
    usage.require_entitlement(conn, tenant_id, usage.DEMAND_PREDICTION)


def require_forecast_service_authorization(conn, tenant_id: str, actor_user_id: str, product_id: str) -> None:
    """Authorize the Redis consumer's configured system identity, never an HTTP principal.

    get_current_tenant() already recognizes this built-in service actor for an
    active company. Require the actual restricted connection to carry that same
    actor and tenant; the event alone cannot establish execution authority.
    """
    try:
        tenant_id = str(UUID(str(tenant_id)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=403, detail="Invalid forecast service context.") from None
    if actor_user_id != SYSTEM_ACTOR_USER_ID:
        raise HTTPException(status_code=403, detail="Invalid forecast service actor.")
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT current_user, session_user, r.rolsuper, r.rolbypassrls, current_setting('row_security'),
                      nullif(current_setting('app.current_user_id', true), '')::uuid::text,
                      nullif(current_setting('app.current_tenant_id', true), '')::uuid::text,
                      public.get_current_tenant()::text
               FROM pg_roles r WHERE r.rolname = current_user;"""
        )
        context = cursor.fetchone()
    expected = ("ceopro_app", "ceopro_app", False, False, "on", SYSTEM_ACTOR_USER_ID, tenant_id, tenant_id)
    if context is None or tuple(context) != expected:
        raise HTTPException(status_code=403, detail="Invalid forecast service context.")
    usage.require_entitlement(conn, tenant_id, usage.DEMAND_PREDICTION)
    # A foreign/deleted product must not become an apparently successful
    # no-history forecast/UNKNOWN evidence record under the event tenant.
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM public.products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
            (tenant_id, product_id),
        )
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Product not found.")
