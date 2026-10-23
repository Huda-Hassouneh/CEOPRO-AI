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
from datetime import datetime, timezone

from fastapi import Depends

from src.ai import db
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context

CACHE_SECONDS = float(os.getenv("ENTITLEMENT_CACHE_SECONDS", "30"))
_cache: dict = {}
_lock = threading.Lock()


def _versions(conn, tenant_id: str) -> tuple[int, int]:
    """Return tenant and catalog generations through the caller's RLS role."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE((
                       SELECT version FROM entitlement_version_state
                       WHERE tenant_id = %s
                   ), 0),
                   catalog.version
            FROM entitlement_catalog_version AS catalog
            WHERE catalog.singleton = TRUE;
            """,
            (tenant_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Entitlement version state is unavailable")
    return int(row[0]), int(row[1])


def _trial_cache_expired(summary: dict, now: datetime) -> bool:
    expires_at = summary.get("trial_ends_at")
    return expires_at is not None and now >= expires_at


def _plan(tenant_id: str, user_id: str) -> dict:
    now = time.monotonic()
    # Version verification is intentionally performed on every authorization
    # request. A database failure must not fall back to a process-local value.
    conn = db.app_role_connection(tenant_id, user_id)
    try:
        versions = _versions(conn, tenant_id)
        with _lock:
            hit = _cache.get(tenant_id)
        if (
            hit
            and hit[1] == versions
            and now - hit[0] < CACHE_SECONDS
            and not _trial_cache_expired(hit[2], datetime.now(timezone.utc))
        ):
            conn.commit()
            return hit[2]
        plan = usage.get_plan(conn, tenant_id)
        conn.commit()
    finally:
        conn.close()
    summary = {
        "status": plan["status"],
        "entitlements": set(plan["entitlements"]),
        "trial_ends_at": (
            plan.get("trial_ends_at")
            if plan.get("status") == "trialing" and plan.get("source") == "trial"
            else None
        ),
    }
    with _lock:
        _cache[tenant_id] = (now, versions, summary)
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
