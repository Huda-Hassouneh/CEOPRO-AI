"""
KEEL - plan modules as FastAPI dependencies.

    app.include_router(forecasting.router, dependencies=[requires(usage.DEMAND_PREDICTION)])

answers 402 (reason NOT_INCLUDED, or SUBSCRIPTION_INACTIVE) before the
endpoint runs when the company's plan doesn't include the module (the plan
catalog: Starter has no market intelligence, demand forecasting or
competitor tracking). Entitlements are cached per company for a short time,
so a plan change applies within ENTITLEMENT_CACHE_SECONDS.
"""
import os
import threading
import time

from fastapi import Depends

from src.ai import db
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context

CACHE_SECONDS = float(os.getenv("ENTITLEMENT_CACHE_SECONDS", "30"))
_cache: dict = {}
_lock = threading.Lock()


def _plan(tenant_id: str, user_id: str) -> dict:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(tenant_id)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    conn = db.app_role_connection(tenant_id, user_id)
    try:
        plan = usage.get_plan(conn, tenant_id)
        conn.commit()
    finally:
        conn.close()
    summary = {"status": plan["status"], "entitlements": set(plan["entitlements"])}
    with _lock:
        _cache[tenant_id] = (now, summary)
    return summary


def forget(tenant_id: str) -> None:
    """Drop the cached entitlements (after a plan change)."""
    with _lock:
        _cache.pop(str(tenant_id), None)


def requires(feature_code: str):
    def dependency(ctx: TenantContext = Depends(get_tenant_context)) -> None:
        plan = _plan(ctx.tenant_id, ctx.user_id)
        if plan["status"] not in usage.ACCESS_GRANTING_STATUSES:
            raise usage.PlanLimitReached("SUBSCRIPTION_INACTIVE", feature_code)
        if feature_code not in plan["entitlements"]:
            raise usage.PlanLimitReached("NOT_INCLUDED", feature_code)

    return Depends(dependency)
