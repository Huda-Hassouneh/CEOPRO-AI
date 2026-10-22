from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ai import db
from src.ai.core import permissions, usage
from src.ai.core.entitlements import requires
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.rag import access
from src.ai.dashboard import activity as dashboard_activity
from src.ai.dashboard import competitor_activity as dashboard_competitor_activity
from src.ai.dashboard import competitor_pricing as dashboard_competitor_pricing
from src.ai.dashboard import competitors as dashboard_competitors
from src.ai.dashboard import expansion_opportunities as dashboard_expansion_opportunities
from src.ai.dashboard import forecast as dashboard_forecast
from src.ai.dashboard import forecast_detail as dashboard_forecast_detail
from src.ai.dashboard import forecast_movers as dashboard_forecast_movers
from src.ai.dashboard import inventory as dashboard_inventory
from src.ai.dashboard import inventory_recommendations as dashboard_inventory_recommendations
from src.ai.dashboard import market_overview as dashboard_market_overview
from src.ai.dashboard import command_center as dashboard_command_center
from src.ai.dashboard import metrics as dashboard_metrics
from src.ai.dashboard import product_intelligence as dashboard_product_intelligence
from src.ai.dashboard import price_competitiveness as dashboard_price_competitiveness
from src.ai.dashboard import recommendations as dashboard_recommendations
from src.ai.dashboard import search as dashboard_search
from src.ai.forecasting import refresh as forecasting_refresh
from src.ai.forecasting import generation as forecasting_generation
from src.ai.forecasting.authorization import require_forecast_authorization
from src.ai.routers.products import get_product

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/sales-trend", dependencies=[permissions.require_capabilities(access.SALES)])
def dashboard_sales_trend_endpoint(
    window_days: int = Query(default=dashboard_metrics.DEFAULT_WINDOW_DAYS, ge=1, le=365),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """Daily revenue/units for the Sales Overview chart - same window and
    sources as /dashboard/metrics (see dashboard/metrics.py::get_sales_trend)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_metrics.get_sales_trend(conn, ctx.tenant_id, window_days=window_days)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/metrics", dependencies=[permissions.require_capabilities(access.SALES)])
def dashboard_metrics_endpoint(
    window_days: int = Query(default=dashboard_metrics.DEFAULT_WINDOW_DAYS, ge=1, le=365),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The dashboard's top metric cards (Revenue, Sales/units, Growth,
    Competitors Tracked) - pure aggregation over invoices/invoice_items/
    tenant_competitors, no new model and no change to any existing
    model's own input/output shape. See dashboard/metrics.py's own
    docstring for exactly how each number is defined - none of these are
    self-evidently unambiguous, so the definitions live there, not just
    in this endpoint's response.

    Deliberately excludes Inventory Status: the `inventory` table isn't
    populated by any real ingestion/sales path yet, so returning a number
    for it here would be fabricating data, not aggregating it.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_metrics.get_dashboard_metrics(conn, ctx.tenant_id, window_days=window_days)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/recommendations")
def dashboard_recommendations_endpoint(
    limit: int = Query(default=dashboard_recommendations.DEFAULT_LIMIT, ge=1, le=20),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The dashboard's Top Recommendations feed - a single unified engine
    across pricing, sentiment, sales, and demand (not just marketing),
    surfacing the top actionable business alerts. Wraps the existing
    insights.generate_insights_for_tenant() (already merges all of those
    signals for the chatbot) and relabels its output for the dashboard;
    no new detection logic, no changed signature.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_recommendations.get_top_recommendations(conn, ctx.tenant_id, limit=limit)
        conn.commit()
        return {"recommendations": result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/forecast", dependencies=[requires(usage.DEMAND_PREDICTION)])
def dashboard_forecast_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The dashboard's Forecast KPI card - total predicted units across all
    products, replacing the mockup's daily line/bar chart since
    forecasting/pipeline.py::run_forecast() only ever produces a single
    integer (expected_demand) per product per call and that signature is
    not changing. Sums the most recent persisted forecast per product;
    products with no forecast yet simply don't contribute, rather than
    being counted as a fabricated zero.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_forecast.get_forecast_summary(conn, ctx.tenant_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/competitor-pricing")
def dashboard_competitor_pricing_endpoint(
    limit: int = Query(default=dashboard_competitor_pricing.DEFAULT_LIMIT, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The dashboard's Competitor Price Positioning bar chart, replacing the
    mockup's Market Share pie chart - this platform tracks competitor
    PRICES, not overall market share, so a price-positioning comparison
    is the honest data to show instead. Per product: your price vs. the
    market average of its mapped competitors' most recent scraped
    prices, capped to the biggest gaps so the chart stays readable.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_competitor_pricing.get_competitor_price_positioning(conn, ctx.tenant_id, limit=limit)
        conn.commit()
        return {"products": result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/competitors")
def dashboard_competitors_endpoint(
    separate_weak_leads: bool = False,
    min_confidence: Optional[float] = Query(None, ge=0, le=100),
    max_distance_km: Optional[float] = Query(None, ge=0),
    limit: Optional[int] = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The dashboard's Competitor Directory - the frontend's final backend
    contract for the competitor UI, grouped by tier (see dashboard/
    competitors.py's own docstring for exactly why the two groups carry
    different fields): STRATEGIC competitors (>= the classification
    threshold's product overlap) with their exact overlap percentage,
    RELEVANT competitors (a real, in-region, tracked competitor below
    that bar) with a per-product price comparison instead. Excludes
    CANDIDATE (manufacturer, or out of region) entirely - those were
    never confirmed as real competitors in the first place.

    Ordered by confidence_score within each group. Optional query params
    (all backward compatible - omitting them returns the original shape):
    separate_weak_leads (split Low-confidence, no-shared-product rows into
    "possible"), min_confidence, max_distance_km, limit/offset (per group).
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_competitors.get_competitor_directory(
            conn, ctx.tenant_id, separate_weak_leads=separate_weak_leads, min_confidence=min_confidence,
            max_distance_km=max_distance_km, limit=limit, offset=offset,
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/market-overview")
def dashboard_market_overview_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The Industry Trends / Market Intelligence Overview page's three
    market-wide aggregates - price_trend, sentiment, category_activity -
    each a real rollup of a signal already computed per-competitor
    elsewhere (see dashboard/market_overview.py's own docstring for
    exactly what each one is and, just as importantly, what it
    deliberately is NOT: no weighted year-over-year index, no seasonal
    decomposition, no market-share % - those need data this platform
    doesn't collect).
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_market_overview.get_market_overview(conn, ctx.tenant_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/expansion-opportunities")
def dashboard_expansion_opportunities_endpoint(
    limit: int = Query(default=dashboard_expansion_opportunities.DEFAULT_MAX_RESULTS, ge=1, le=10),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    Market Intelligence's "Expansion Opportunities" cards - real category
    gaps (a product category several tracked competitors carry that this
    tenant's own catalog does not), reusing insights/category_gap.py's
    existing detection. See dashboard/expansion_opportunities.py's own
    docstring - an empty list is a real, honest absence, never padded
    with invented opportunities.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_expansion_opportunities.get_expansion_opportunities(conn, ctx.tenant_id, max_results=limit)
        conn.commit()
        return {"opportunities": result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/activity")
def dashboard_activity_endpoint(
    limit: int = Query(default=dashboard_activity.DEFAULT_LIMIT, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The dashboard's Recent Activity feed - real timestamped events the
    platform already writes (file uploads, competitors tracked, forecasts
    generated, products added), not a new audit log. See dashboard/
    activity.py's own docstring.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_activity.get_recent_activity(conn, ctx.tenant_id, limit=limit)
        conn.commit()
        return {"activity": result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/competitor-activity")
def dashboard_competitor_activity_endpoint(
    limit: int = Query(default=dashboard_competitor_activity.DEFAULT_LIMIT, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The dashboard's Recent Competitor Changes/Activity feed - real,
    detected price changes only (see dashboard/competitor_activity.py's
    own docstring on why "new product launched"/"marketing campaign
    detected" are deliberately not fabricated here).
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_competitor_activity.get_recent_competitor_price_changes(conn, ctx.tenant_id, limit=limit)
        conn.commit()
        return {"changes": result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/price-competitiveness")
def dashboard_price_competitiveness_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The dashboard's Price Competitiveness headline score (1-10) - reuses
    market_scraper/scoring.py's existing scoring function, averaged
    across all products with a real competitor price observation. See
    dashboard/price_competitiveness.py's own docstring.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_price_competitiveness.get_price_competitiveness(conn, ctx.tenant_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inventory")
def dashboard_inventory_endpoint(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The dashboard's Inventory Status card - reads the real `inventory`
    table honestly: has_data=False (never a fabricated percentage) for a
    tenant with no inventory rows yet. See dashboard/inventory.py's own
    docstring for why this was previously out of scope entirely.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_inventory.get_inventory_status(conn, ctx.tenant_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/search")
def dashboard_search_endpoint(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=dashboard_search.DEFAULT_LIMIT, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The top-bar unified search - real products and tracked competitors
    only. See dashboard/search.py's own docstring on why "insights" are
    deliberately not included.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_search.search(conn, ctx.tenant_id, q, limit=limit)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/forecast-movers", dependencies=[requires(usage.DEMAND_PREDICTION)])
def dashboard_forecast_movers_endpoint(
    limit: int = Query(default=dashboard_forecast_movers.DEFAULT_LIMIT, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The Demand Prediction overview's "Top Products by Predicted Demand
    Increase/Decrease" tables and increasing/decreasing/stable counts.
    See dashboard/forecast_movers.py's own docstring for exactly what
    "change" means here (predicted 30-day demand vs. real current stock).
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_forecast_movers.get_forecast_movers(conn, ctx.tenant_id, limit=limit)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inventory-recommendations", dependencies=[requires(usage.DEMAND_PREDICTION)])
def dashboard_inventory_recommendations_endpoint(
    limit: int = Query(default=dashboard_inventory_recommendations.DEFAULT_LIMIT, ge=1, le=100),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The "Priority Inventory Actions"/"Inventory Recommendations" tables -
    a transparent, rule-based Restock Now/Reduce Order/Monitor action per
    product, from real predicted demand vs. real current stock. See
    dashboard/inventory_recommendations.py's own docstring - never an
    invented "AI reasoning" narrative.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_inventory_recommendations.get_inventory_recommendations(conn, ctx.tenant_id, limit=limit)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/products/{product_id}/forecast", dependencies=[requires(usage.DEMAND_PREDICTION)])
def dashboard_generate_product_forecast_endpoint(product_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Synchronously generates a real forecast for one product, mirroring
    routers/pricing.py's POST /pricing/recommend (on-demand HTTP trigger
    around an existing pipeline function, not a new detection engine).

    forecasting/pipeline.py::run_forecast() has always been fully built
    and correct, but the only thing that ever called it was
    forecasting/consumer.py's ForecastRequestConsumer - a Redis-stream
    worker that is never started by this app (no `__main__` entrypoint
    is invoked, no service definition exists for it in docker-compose.yml
    or render.yaml) and that nothing in this codebase ever publishes to
    (`ceopro:stream:demand_forecast_requested` is created by
    infrastructure/init_broker.py at deploy time and never written to
    afterward). A product could therefore never get its first forecast in
    any environment - not a tenant/data bug, a missing on-demand trigger.
    This endpoint is that trigger. Returns run_forecast()'s own real,
    honest result unmodified, including its "UNKNOWN" status with a plain
    explanation when the product has no historical sales data yet - never
    a fabricated forecast.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if get_product(conn, ctx.tenant_id, str(product_id)) is None:
            raise HTTPException(status_code=404, detail="Product not found")
        check = lambda: require_forecast_authorization(conn, ctx.tenant_id, ctx.user_id)
        check()
        result = _generate_or_reuse_forecast(conn, ctx.tenant_id, str(product_id), check)
        conn.commit()
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/products/{product_id}/forecast", dependencies=[requires(usage.DEMAND_PREDICTION)])
def dashboard_product_forecast_endpoint(product_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    The product detail page's forecast section - real current stock,
    latest forecast (with its real confidence interval), real average
    daily demand, and the real history of every forecast run for this
    product. See dashboard/forecast_detail.py's own docstring for what's
    deliberately NOT here (no seasonality heatmap, no causal narrative).
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_forecast_detail.get_product_forecast_detail(conn, ctx.tenant_id, str(product_id))
        conn.commit()
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _generate_or_reuse_forecast(conn, tenant_id: str, product_id: str, authorization_check=None) -> dict:
    """Compatibility wrapper for the shared generation/idempotency service."""
    return forecasting_generation.generate_or_reuse_forecast(conn, tenant_id, product_id, authorization_check=authorization_check)


@router.get("/products/{product_id}/intelligence", dependencies=[requires(usage.DEMAND_PREDICTION)])
def dashboard_product_intelligence_endpoint(product_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """The product page: sales, demand forecast, stock advice, competitor
    prices (this product's competitors and the company's others), reviews
    and data-backed signals - dashboard/product_intelligence.py."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_product_intelligence.build_product_intelligence(conn, ctx.tenant_id, str(product_id))
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    finally:
        conn.close()


@router.get("/command-center", dependencies=[requires(usage.DEMAND_PREDICTION)])
def dashboard_command_center_endpoint(
    window_days: int = Query(default=30, ge=7, le=365),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """The Command Center (dashboard/command_center.py)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        return dashboard_command_center.get_command_center(conn, ctx.tenant_id, window_days)
    finally:
        conn.close()
