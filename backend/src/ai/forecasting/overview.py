"""
Demand Prediction overview: one response with everything the page shows,
computed from the same sales (invoices), stock (inventory) and forecasts
(demand_forecasts) every other screen uses.

Per product:
- units sold in the last 30 days and the 30 days before,
- the latest forecast for the next 30 days (with its range and method),
- trend = forecast vs the last 30 days' actual sales
  (increasing / decreasing beyond +-TREND_BAND_PCT, else stable),
- stock advice from stock_advice.advise(),
- expected revenue = forecast units x current price.

Plus a daily series for the chart: actual units for the last 90 days and the
forecast path for the next 30 (summed over the selected products), and the
totals the summary cards show.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from src.ai.forecasting import stock_advice
from src.ai.core.business_time import business_today, window_start

TREND_BAND_PCT = 10.0
HISTORY_DAYS = 90
WINDOW_DAYS = 30


def _f(value) -> Optional[float]:
    return float(value) if value is not None else None


def _trend(forecast: Optional[float], recent: float, previous: float) -> tuple:
    if forecast is None:
        return ("no_sales" if recent == 0 and previous == 0 else "not_forecast"), None
    if recent <= 0:
        return ("increasing" if forecast > 0 else "stable"), None
    change = round((forecast - recent) / recent * 100, 1)
    if change > TREND_BAND_PCT:
        return "increasing", change
    if change < -TREND_BAND_PCT:
        return "decreasing", change
    return "stable", change


def build_overview(conn, tenant_id: str, product_id: Optional[str] = None, today: Optional[date] = None) -> dict:
    today = today or business_today(conn)
    # "Last 30 days" means the same as on the dashboard (dashboard/metrics.py):
    # the 30 days up to now, compared with the 30 days before that.
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, WINDOW_DAYS)
    previous_start = window_start(conn, WINDOW_DAYS, periods=2)
    history_start = today - timedelta(days=HISTORY_DAYS)

    with conn.cursor() as cursor:
        cursor.execute("SELECT primary_currency FROM companies WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()
        company_currency = row[0] if row else None

        cursor.execute(
            """
            WITH sales AS (
                SELECT ii.product_id,
                       COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date >= %(recent)s), 0) AS recent,
                       COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date >= %(previous)s AND i.issue_date < %(recent)s), 0) AS previous,
                       MAX(i.issue_date) AS last_sale
                FROM invoice_items ii
                JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
                WHERE ii.tenant_id = %(tenant)s AND i.payment_status <> 'CANCELLED'
                GROUP BY ii.product_id
            ), latest AS (
                SELECT DISTINCT ON (product_id) product_id, forecast_id, expected_demand,
                       confidence_range_lower, confidence_range_upper, forecast_start_date,
                       forecast_target_date, features_used, created_at, model_version
                FROM demand_forecasts WHERE tenant_id = %(tenant)s
                ORDER BY product_id, created_at DESC
            )
            SELECT p.product_id, localized_text(p.product_name), localized_text(p.category),
                   p.current_price, p.currency, NULL AS unit,
                   i.stock_quantity, i.reorder_level, i.safety_stock,
                   s.recent, s.previous, s.last_sale,
                   l.expected_demand, l.confidence_range_lower, l.confidence_range_upper,
                   l.forecast_start_date, l.forecast_target_date, l.features_used, l.created_at
            FROM products p
            LEFT JOIN (
                SELECT product_id, SUM(stock_quantity) AS stock_quantity,
                       MAX(reorder_level) AS reorder_level, MAX(safety_stock) AS safety_stock
                FROM inventory WHERE tenant_id = %(tenant)s GROUP BY product_id
            ) i ON i.product_id = p.product_id
            LEFT JOIN sales s ON s.product_id = p.product_id
            LEFT JOIN latest l ON l.product_id = p.product_id
            WHERE p.tenant_id = %(tenant)s AND p.deleted_at IS NULL
            ORDER BY localized_text(p.product_name);
            """,
            {"tenant": tenant_id, "today": today, "recent": recent_start, "previous": previous_start},
        )
        rows = cursor.fetchall()

    products = []
    for (pid, name, category, price, currency, unit, stock, reorder_level, safety_stock,
         recent, previous, last_sale, expected, lower, upper, start_date, target_date, features, created_at) in rows:
        recent, previous = float(recent or 0), float(previous or 0)
        forecast = _f(expected)
        trend, change_pct = _trend(forecast, recent, previous)
        advice = stock_advice.advise(_f(stock), forecast, _f(reorder_level), _f(safety_stock)) if forecast is not None else (
            stock_advice.advise(_f(stock), None, _f(reorder_level), _f(safety_stock)) if stock is not None else
            {"action": stock_advice.NONE, "suggested_qty": 0, "days_of_cover": None, "priority": "low", "reason_code": "not_tracked"}
        )
        features = features or {}
        price = _f(price)
        products.append({
            "product_id": str(pid),
            "name": name,
            "category": category,
            "unit": unit,
            "currency": currency or company_currency,
            "current_price": price,
            "current_stock": _f(stock),
            "reorder_level": _f(reorder_level),
            "sold_last_30": recent,
            "sold_previous_30": previous,
            "sales_change_pct": round((recent - previous) / previous * 100, 1) if previous else None,
            "last_sale_at": last_sale.isoformat() if last_sale else None,
            "forecast_next_30": forecast,
            "forecast_lower": _f(lower),
            "forecast_upper": _f(upper),
            "forecast_start_date": start_date.isoformat() if start_date else None,
            "forecast_end_date": target_date.isoformat() if target_date else None,
            "forecast_created_at": created_at.isoformat() if created_at else None,
            "forecast_method": features.get("method"),
            "confidence_score": features.get("confidence_score"),
            "data_sufficiency": features.get("data_sufficiency"),
            "expected_revenue": round(forecast * price, 2) if forecast is not None and price is not None else None,
            "trend": trend,
            "trend_change_pct": change_pct,
            **{f"stock_{k}": v for k, v in advice.items()},
            "_daily": features.get("daily") or ([forecast / stock_advice.HORIZON_DAYS] * stock_advice.HORIZON_DAYS if forecast else []),
        })

    selected = [p for p in products if not product_id or p["product_id"] == product_id]
    series = _series(conn, tenant_id, selected, history_start, today, product_id)

    forecasted = [p for p in selected if p["forecast_next_30"] is not None]
    total_forecast = round(sum(p["forecast_next_30"] for p in forecasted), 2)
    total_recent = round(sum(p["sold_last_30"] for p in forecasted), 2)
    revenue_currency = {p["currency"] for p in forecasted if p["expected_revenue"] is not None}
    totals = {
        "products": len(selected),
        "products_with_sales": sum(1 for p in selected if p["sold_last_30"] or p["sold_previous_30"] or p["last_sale_at"]),
        "forecasted": len(forecasted),
        "forecast_next_30": total_forecast,
        "sold_last_30": total_recent,
        "change_pct": round((total_forecast - total_recent) / total_recent * 100, 1) if total_recent else None,
        "increasing": sum(1 for p in forecasted if p["trend"] == "increasing"),
        "decreasing": sum(1 for p in forecasted if p["trend"] == "decreasing"),
        "stable": sum(1 for p in forecasted if p["trend"] == "stable"),
        "restock": sum(1 for p in selected if p["stock_action"] == stock_advice.RESTOCK),
        "reduce": sum(1 for p in selected if p["stock_action"] == stock_advice.REDUCE),
        "expected_revenue": round(sum(p["expected_revenue"] for p in forecasted if p["expected_revenue"] is not None), 2)
        if len(revenue_currency) == 1 else None,
        "currency": next(iter(revenue_currency)) if len(revenue_currency) == 1 else company_currency,
    }
    for p in products:
        p.pop("_daily", None)

    return {
        "as_of": today.isoformat(),
        "horizon_days": stock_advice.HORIZON_DAYS,
        "trend_band_pct": TREND_BAND_PCT,
        "products": products,
        "selected_product_id": product_id,
        "totals": totals,
        "series": series,
    }


def _series(conn, tenant_id: str, selected: list, history_start: date, today: date, product_id: Optional[str]) -> list:
    """Daily actual units (history) then forecast units (next 30 days)."""
    ids = [p["product_id"] for p in selected]
    actual = {}
    if ids:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.issue_date::date, SUM(ii.quantity)
                FROM invoice_items ii
                JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
                WHERE ii.tenant_id = %s AND i.payment_status <> 'CANCELLED'
                  AND i.issue_date >= %s AND i.issue_date < %s
                  AND ii.product_id = ANY(%s::uuid[])
                GROUP BY 1;
                """,
                (tenant_id, history_start, today, ids),
            )
            actual = {day: float(units) for day, units in cursor.fetchall()}

    points = []
    day = history_start
    while day < today:
        points.append({"date": day.isoformat(), "actual": round(actual.get(day, 0.0), 3), "forecast": None})
        day += timedelta(days=1)

    # Every forecast covers "the next 30 days"; its path is drawn from today
    # so products whose history ends today or yesterday line up.
    forecast_by_day = {}
    for p in selected:
        for offset, value in enumerate(p.get("_daily") or []):
            d = today + timedelta(days=offset)
            forecast_by_day[d] = forecast_by_day.get(d, 0.0) + float(value)
    for d in sorted(forecast_by_day):
        points.append({"date": d.isoformat(), "actual": None, "forecast": round(forecast_by_day[d], 3)})
    return points
