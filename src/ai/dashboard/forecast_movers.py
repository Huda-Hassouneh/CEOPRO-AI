"""
CEOPRO AI - Dashboard Forecast Movers (presentation layer, not a new
model, no new tables).

The mockup's "Top Products by Predicted Demand Increase/Decrease" and the
"Product Forecasts" overview counts (increasing/decreasing/stable).
"Change" here is real and matches the mockup's own numbers exactly:
(predicted 30-day demand - current stock) / current stock - i.e. how
much the most recent forecast for this product exceeds or falls short of
what's already on the shelf, not a forecast-vs-last-period trend (this
platform's forecasting runs don't currently persist a comparable "last
period" forecast to diff against, so that would be a different, not-yet-
real metric). A product needs BOTH a real inventory row AND a real
forecast to appear here at all - no stock, no forecast, or either one
missing means "not enough data yet", never a fabricated 0%/620 units.
"""
DEFAULT_LIMIT = 5

# +-20% is the same "don't nudge on noise" discipline pricing/
# recommendation.py's own COMPETITIVENESS_THRESHOLD_PCT applies - a small
# gap between predicted demand and current stock is normal forecast
# variance, not something worth flagging as "increasing"/"decreasing".
STABLE_BAND_PCT = 20.0


def _load_forecast_vs_stock(conn, tenant_id: str) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (df.product_id)
                df.product_id,
                COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS product_name,
                p.category->>'en' AS category,
                i.stock_quantity, df.expected_demand, df.forecast_target_date
            FROM demand_forecasts df
            JOIN products p ON p.tenant_id = df.tenant_id AND p.product_id = df.product_id
            JOIN inventory i ON i.tenant_id = df.tenant_id AND i.product_id = df.product_id
            WHERE df.tenant_id = %s AND p.deleted_at IS NULL AND i.stock_quantity > 0
            ORDER BY df.product_id, df.created_at DESC;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    movers = []
    for product_id, name, category, stock, expected_demand, target_date in rows:
        stock = int(stock)
        expected_demand = float(expected_demand)
        change_pct = round((expected_demand - stock) / stock * 100, 1)
        movers.append({
            "product_id": str(product_id),
            "product_name": name,
            "category": category,
            "current_stock": stock,
            "predicted_demand": round(expected_demand),
            "forecast_target_date": target_date.isoformat(),
            "change_pct": change_pct,
        })
    return movers


def get_forecast_movers(conn, tenant_id: str, limit: int = DEFAULT_LIMIT) -> dict:
    movers = _load_forecast_vs_stock(conn, tenant_id)

    increasing = sorted((m for m in movers if m["change_pct"] > STABLE_BAND_PCT), key=lambda m: -m["change_pct"])
    decreasing = sorted((m for m in movers if m["change_pct"] < -STABLE_BAND_PCT), key=lambda m: m["change_pct"])
    stable_count = len(movers) - len(increasing) - len(decreasing)

    return {
        "products_forecasted": len(movers),
        "increasing_count": len(increasing),
        "decreasing_count": len(decreasing),
        "stable_count": stable_count,
        "top_increasing": increasing[:limit],
        "top_decreasing": decreasing[:limit],
    }
