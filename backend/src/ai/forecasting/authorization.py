"""Execution-time authorization for demand forecasts."""

from fastapi import HTTPException

from src.ai.core import usage


def require_forecast_authorization(conn, tenant_id: str, actor_user_id: str) -> None:
    """Recheck the initiating principal and current feature grant on the worker connection."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT keel_active_principal(%s, %s);", (actor_user_id, tenant_id))
        row = cursor.fetchone()
    if not row or row[0] is not True:
        raise HTTPException(status_code=403, detail="An active tenant membership is required to generate forecasts.")
    usage.require_entitlement(conn, tenant_id, usage.DEMAND_PREDICTION)
