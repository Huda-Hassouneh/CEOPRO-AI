"""
The Command Center: one response answering what a business owner asks first
- what's happening (revenue, units, orders, today), what changed (vs the
previous period), what needs attention (restock, falling products, price
gaps), what competitors are doing (recent price moves), what demand looks
like (30-day forecast) and what to do next (ranked, data-backed actions).

Built from the same functions as the dedicated screens, so every number here
matches Products, Demand, Competitors and Reports exactly.
"""

from datetime import datetime, timedelta, timezone

from src.ai.dashboard import metrics as dashboard_metrics
from src.ai.forecasting import overview as forecast_overview
from src.ai.market_inputs import discovered_competitors
from src.ai.core import tenant_cache
from src.ai.core.business_time import business_today, window_start

MOVER_MIN_UNITS = 5
MOVER_PCT = 10.0
PRICE_GAP_PCT = 5.0


def get_command_center(conn, tenant_id: str, window_days: int = 30) -> dict:
    """build_command_center(), shared for a few seconds between the screens
    that need it at the same time (the dashboard and the alerts bell) - see
    core/tenant_cache.py for when it is recomputed."""
    return tenant_cache.get_or_compute("command_center", tenant_id, window_days,
                                       lambda: build_command_center(conn, tenant_id, window_days))


def build_command_center(conn, tenant_id: str, window_days: int = 30) -> dict:
    now = datetime.now(timezone.utc)
    today = business_today(conn)  # the company's local date
    metrics = dashboard_metrics.get_dashboard_metrics(conn, tenant_id, window_days)
    trend = dashboard_metrics.get_sales_trend(conn, tenant_id, window_days)
    demand = forecast_overview.build_overview(conn, tenant_id, today=today)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(i.total_amount), 0),
                   COALESCE((SELECT SUM(ii.quantity)
                             FROM invoice_items ii
                             JOIN invoices sale ON sale.tenant_id = ii.tenant_id
                               AND sale.invoice_id = ii.invoice_id
                             WHERE ii.tenant_id = %s AND sale.payment_status = 'PAID'
                               AND sale.issue_date >= CURRENT_DATE::timestamptz), 0),
                   MAX(i.currency)
            FROM invoices i
            WHERE i.tenant_id = %s AND i.payment_status = 'PAID'
              AND i.issue_date >= CURRENT_DATE::timestamptz;
            """,
            (tenant_id, tenant_id),
        )
        orders_today, revenue_today, units_today, currency_today = cursor.fetchone()

        # The setup screen describes a tenant that has never imported sales.
        # A quiet reporting window must not send an established customer back
        # to onboarding when older canonical sales still exist.
        cursor.execute("SELECT EXISTS (SELECT 1 FROM invoices WHERE tenant_id = %s AND payment_status = 'PAID');", (tenant_id,))
        has_sales = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT ii.product_id, localized_text(p.product_name),
                   COALESCE(SUM(ii.total_price) FILTER (WHERE i.issue_date >= %(recent)s), 0) AS revenue,
                   COALESCE(SUM(ii.total_price) FILTER (WHERE i.issue_date < %(recent)s), 0) AS revenue_prev,
                   COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date >= %(recent)s), 0) AS units,
                   COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date < %(recent)s), 0) AS units_prev,
                   MAX(i.currency)
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id AND p.deleted_at IS NULL
            WHERE ii.tenant_id = %(tenant)s AND i.payment_status = 'PAID'
              AND i.issue_date >= %(previous)s
            GROUP BY ii.product_id, p.product_name;
            """,
            {"tenant": tenant_id, "recent": window_start(conn, window_days), "previous": window_start(conn, window_days, periods=2)},
        )
        product_rows = cursor.fetchall()

        cursor.execute(
            """
            WITH ranked AS (
                SELECT cpm.product_id, gc.global_competitor_id, gc.competitor_name, cp.scraped_price, cp.currency, cp.observed_at,
                       LAG(cp.scraped_price) OVER (PARTITION BY cp.mapping_id ORDER BY cp.observed_at) AS previous_price,
                       ROW_NUMBER() OVER (PARTITION BY cp.mapping_id ORDER BY cp.observed_at DESC) AS rn
                FROM competitor_prices cp
                JOIN competitor_product_mappings cpm ON cpm.tenant_id = cp.tenant_id AND cpm.mapping_id = cp.mapping_id
                JOIN tenant_competitors tc ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id AND tc.is_tracked
                JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
                WHERE cp.tenant_id = %s
            )
            SELECT r.product_id, localized_text(p.product_name), r.global_competitor_id, r.competitor_name,
                   r.scraped_price, r.previous_price, r.currency, r.observed_at, p.current_price, p.currency
            FROM ranked r
            JOIN products p ON p.tenant_id = %s AND p.product_id = r.product_id AND p.deleted_at IS NULL
            WHERE r.rn = 1;
            """,
            (tenant_id, tenant_id),
        )
        latest_competitor_prices = cursor.fetchall()

    def pct(new, old):
        return round((new - old) / old * 100, 1) if old else None

    products = []
    for pid, name, revenue, revenue_prev, units, units_prev, currency in product_rows:
        products.append({
            "product_id": str(pid), "name": name, "currency": currency,
            "revenue": round(float(revenue), 2), "revenue_change_pct": pct(float(revenue), float(revenue_prev)),
            "units": float(units), "units_prev": float(units_prev), "units_change_pct": pct(float(units), float(units_prev)),
        })
    top_products = sorted(products, key=lambda p: -p["revenue"])[:5]
    declining = sorted(
        [p for p in products if p["units_prev"] >= MOVER_MIN_UNITS and (p["units_change_pct"] or 0) <= -MOVER_PCT],
        key=lambda p: p["units_change_pct"],
    )[:5]
    growing = sorted(
        [p for p in products if p["units_prev"] >= MOVER_MIN_UNITS and (p["units_change_pct"] or 0) >= MOVER_PCT],
        key=lambda p: -p["units_change_pct"],
    )[:5]

    restock = sorted(
        [p for p in demand["products"] if p["stock_action"] == "restock" and p["forecast_next_30"] is not None],
        key=lambda p: (p["stock_priority"] != "high", p["stock_days_of_cover"] if p["stock_days_of_cover"] is not None else 0),
    )
    restock_view = [{
        "product_id": p["product_id"], "name": p["name"], "stock": p["current_stock"], "days_of_cover": p["stock_days_of_cover"],
        "suggested_qty": p["stock_suggested_qty"], "priority": p["stock_priority"],
    } for p in restock[:6]]

    competitor_moves, gaps_by_product = [], {}
    for pid, product_name, cid, competitor, price, previous, currency, observed, own_price, own_currency in latest_competitor_prices:
        price = float(price)
        if previous is not None and float(previous) and abs(pct(price, float(previous)) or 0) >= 1 and observed >= now - timedelta(days=30):
            competitor_moves.append({
                "competitor_id": str(cid), "competitor": competitor, "product_id": str(pid), "product": product_name,
                "price": price, "previous_price": float(previous), "change_pct": pct(price, float(previous)),
                "currency": currency, "observed_at": observed.isoformat(),
            })
        if currency == own_currency:
            gaps_by_product.setdefault(str(pid), {"product_id": str(pid), "name": product_name, "your_price": float(own_price),
                                                   "currency": own_currency, "prices": []})["prices"].append((competitor, price))
    competitor_moves.sort(key=lambda m: m["observed_at"], reverse=True)

    price_opportunities = []
    for entry in gaps_by_product.values():
        prices = [p for _, p in entry["prices"]]
        average = sum(prices) / len(prices)
        gap = pct(entry["your_price"], average)
        if gap is None or abs(gap) < PRICE_GAP_PCT:
            continue
        cheapest = min(entry["prices"], key=lambda item: item[1])
        price_opportunities.append({
            "product_id": entry["product_id"], "name": entry["name"], "your_price": entry["your_price"], "currency": entry["currency"],
            "market_average": round(average, 4), "gap_pct": gap, "competitors": len(prices),
            "cheapest_competitor": cheapest[0], "cheapest_price": cheapest[1],
            "kind": "above_market" if gap > 0 else "below_market",
        })
    price_opportunities.sort(key=lambda o: -abs(o["gap_pct"]))

    actions = _actions(restock_view, declining, price_opportunities, demand, growing)

    return {
        "as_of": now.isoformat(),
        "window_days": window_days,
        "metrics": metrics,
        "today": {"orders": int(orders_today), "revenue": round(float(revenue_today), 2), "units": float(units_today),
                  "currency": currency_today or metrics["revenue"]["currency"]},
        "sales_trend": trend,
        "demand": {**demand["totals"], "refreshing": False},
        "top_products": top_products,
        "growing": growing,
        "declining": declining,
        "restock": restock_view,
        "restock_total": len(restock),
        "competitor_moves": competitor_moves[:6],
        "price_opportunities": price_opportunities[:6],
        "actions": actions,
        "market": discovered_competitors.market_summary(conn, tenant_id),
        "has_sales": bool(has_sales),
        "product_count": len(demand["products"]),
    }


def _actions(restock, declining, price_opportunities, demand, growing) -> list:
    """What to do next, most urgent first. Each action names its product and
    the numbers behind it; the frontend words it in the user's language."""
    actions = []
    for item in restock[:2]:
        actions.append({"kind": "restock", "priority": item["priority"], **item})
    for item in declining[:2]:
        actions.append({"kind": "declining", "priority": "medium", "product_id": item["product_id"], "name": item["name"], "pct": item["units_change_pct"]})
    for item in [o for o in price_opportunities if o["kind"] == "above_market"][:2]:
        actions.append({"kind": "priced_above", "priority": "medium", "product_id": item["product_id"], "name": item["name"],
                        "pct": item["gap_pct"], "competitor": item["cheapest_competitor"]})
    # A product with rising demand and enough stock is the clearest thing to promote.
    promotable = [p for p in demand["products"] if p["trend"] == "increasing" and p["stock_action"] in ("monitor", "reduce", "none")]
    overstocked = [p for p in demand["products"] if p["stock_action"] == "reduce"]
    if promotable:
        p = promotable[0]
        actions.append({"kind": "promote_rising", "priority": "low", "product_id": p["product_id"], "name": p["name"], "pct": p["trend_change_pct"]})
    elif overstocked:
        p = max(overstocked, key=lambda x: x["stock_days_of_cover"] or 0)
        actions.append({"kind": "promote_overstock", "priority": "low", "product_id": p["product_id"], "name": p["name"], "days": p["stock_days_of_cover"]})
    elif growing:
        p = growing[0]
        actions.append({"kind": "promote_growing", "priority": "low", "product_id": p["product_id"], "name": p["name"], "pct": p["units_change_pct"]})
    rank = {"high": 0, "medium": 1, "low": 2}
    # The promotion idea always keeps its place, after the five most urgent.
    promotions = [a for a in actions if a["kind"].startswith("promote")]
    others = sorted([a for a in actions if not a["kind"].startswith("promote")], key=lambda a: rank.get(a["priority"], 3))
    return others[:5] + promotions[:1]
