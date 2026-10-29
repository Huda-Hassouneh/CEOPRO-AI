"""
Demand Prediction API.

GET  /forecasting/overview  - everything the Demand Prediction page shows
                              (forecasts, trends, stock advice, chart series),
                              and starts a background refresh when any product's
                              forecast is missing or older than its latest sale.
POST /forecasting/refresh   - recompute forecasts now (the page's "Refresh" button).
GET  /forecasting/status    - progress of the running refresh.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ai import db
from src.ai.core import usage, tenant_cache
from src.ai.core.entitlements import requires
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.forecasting import overview as forecast_overview
from src.ai.forecasting import refresh as forecast_refresh

logger = logging.getLogger("CEOPRO_AI_FORECASTING_API")

router = APIRouter(prefix="/forecasting", tags=["forecasting"])


def _refresh_payload(tenant_id: str, pending: int, started: bool) -> dict:
    status = forecast_refresh.refresh_status(tenant_id)
    return {**status, "pending_products": pending, "started": started}


@router.get("/overview", dependencies=[requires(usage.DEMAND_PREDICTION)])
def get_overview(
    product_id: Optional[UUID] = Query(default=None),
    auto_refresh: bool = Query(default=True),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    # Both read the company's whole sales history (~160 ms on 50,000 lines)
    # and change only when its data does: shared between visits until the
    # next write (core/tenant_cache.py). Refresh progress is never cached.
    key = str(product_id) if product_id else None
    pending, result = tenant_cache.cached_read("forecast_overview", ctx, key, lambda conn: (
        forecast_refresh.products_needing_forecast(conn, ctx.tenant_id),
        forecast_overview.build_overview(conn, ctx.tenant_id, key)))
    if product_id and not any(p["product_id"] == str(product_id) for p in result["products"]):
        raise HTTPException(status_code=404, detail="Product not found.")
    started = bool(pending) and auto_refresh and forecast_refresh.auto_refresh_enabled() and forecast_refresh.start_refresh(ctx.tenant_id, ctx.user_id, pending)
    result["refresh"] = _refresh_payload(ctx.tenant_id, len(pending), started)
    return result


@router.post("/refresh", dependencies=[requires(usage.DEMAND_PREDICTION)])
def refresh_forecasts(
    all_products: bool = Query(default=False, description="Re-forecast every product with sales, not only stale ones."),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        product_ids = forecast_refresh.products_needing_forecast(
            conn, ctx.tenant_id, stale_after_hours=0 if all_products else forecast_refresh.STALE_AFTER_HOURS,
        )
    finally:
        conn.close()
    started = bool(product_ids) and forecast_refresh.start_refresh(ctx.tenant_id, ctx.user_id, product_ids)
    return _refresh_payload(ctx.tenant_id, len(product_ids), started)


@router.get("/status", dependencies=[requires(usage.DEMAND_PREDICTION)])
def refresh_status(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    return forecast_refresh.refresh_status(ctx.tenant_id)
