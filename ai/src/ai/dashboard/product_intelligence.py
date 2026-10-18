"""
Everything about one product, for the product page: identity, sales
(windows, daily series, recent sales), the 30-day forecast with stock advice,
competitor prices for this product (product-level competitors) and the
company's other tracked competitors (industry-level), customer reviews, and
plain, data-backed signals ("needs restock", "priced above the market").

Every number comes from the company's own records (invoices, inventory,
products, reviews) or KEEL's tracking and calculations (competitor prices,
forecasts); a signal is only produced when its data exists.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ai.dashboard.product_market import competitor_details, product_market_detail
from src.ai.forecasting import overview as forecast_overview
from src.ai.routers.products import get_product
from src.ai.core.business_time import business_today, window_start

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
TREND_MIN_UNITS = 5
TREND_PCT = 10.0
PRICE_GAP_PCT = 5.0
NEGATIVE_REVIEW_SHARE = 0.3


def _num(value) -> Optional[float]:
    return float(value) if value is not None else None


def _pct(new, old) -> Optional[float]:
    return round((new - old) / old * 100, 1) if old else None


def build_product_intelligence(conn, tenant_id: str, product_id: str, today=None) -> Optional[dict]:
    product = get_product(conn, tenant_id, product_id)
    if product is None:
        return None
    today = today or business_today(conn)
    # "Last 30 days" means the same as on the dashboard (dashboard/metrics.py):
    # the 30 days up to now, compared with the 30 days before that.
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, WINDOW_DAYS)
    previous_start = window_start(conn, WINDOW_DAYS, periods=2)

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT localized_text(product_name), localized_text(category), localized_text(brand) FROM products WHERE tenant_id = %s AND product_id = %s;",
            (tenant_id, product_id),
        )
        display_name, display_category, display_brand = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date >= %(recent)s), 0),
                COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date >= %(previous)s AND i.issue_date < %(recent)s), 0),
                COALESCE(SUM(ii.total_price) FILTER (WHERE i.issue_date >= %(recent)s), 0),
                COALESCE(SUM(ii.total_price) FILTER (WHERE i.issue_date >= %(previous)s AND i.issue_date < %(recent)s), 0),
                COUNT(DISTINCT i.invoice_id) FILTER (WHERE i.issue_date >= %(recent)s),
                COALESCE(SUM(ii.quantity), 0), COALESCE(SUM(ii.total_price), 0),
                MIN(i.issue_date), MAX(i.issue_date), MAX(i.currency)
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE ii.tenant_id = %(tenant)s AND ii.product_id = %(product)s;
            """,
            {"tenant": tenant_id, "product": product_id, "today": today, "recent": recent_start, "previous": previous_start},
        )
        (units_30, units_prev, revenue_30, revenue_prev, orders_30, units_all, revenue_all,
         first_sale, last_sale, sales_currency) = cursor.fetchone()

        cursor.execute(
            """
            SELECT i.issue_date, ii.quantity, ii.unit_price, ii.total_price, i.currency
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE ii.tenant_id = %s AND ii.product_id = %s
            ORDER BY i.issue_date DESC
            LIMIT 8;
            """,
            (tenant_id, product_id),
        )
        recent_sales = [
            {"date": d.isoformat(), "quantity": float(q), "unit_price": float(p), "total": float(t), "currency": c}
            for d, q, p, t, c in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT gc.global_competitor_id, gc.competitor_name, tc.tier, cpm.competitor_product_url,
                   latest.scraped_price, latest.currency, latest.observed_at, latest.is_available,
                   prev.scraped_price, tc.competition_level, gc.website_url, ds.source_name
            FROM competitor_product_mappings cpm
            LEFT JOIN data_sources ds ON ds.tenant_id = cpm.tenant_id AND ds.source_id = cpm.source_id
            JOIN tenant_competitors tc ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id
            JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
            LEFT JOIN LATERAL (
                SELECT scraped_price, currency, observed_at, is_available FROM competitor_prices cp
                WHERE cp.tenant_id = cpm.tenant_id AND cp.mapping_id = cpm.mapping_id
                ORDER BY observed_at DESC LIMIT 1
            ) latest ON TRUE
            LEFT JOIN LATERAL (
                SELECT scraped_price FROM competitor_prices cp
                WHERE cp.tenant_id = cpm.tenant_id AND cp.mapping_id = cpm.mapping_id
                ORDER BY observed_at DESC OFFSET 1 LIMIT 1
            ) prev ON TRUE
            WHERE cpm.tenant_id = %s AND cpm.product_id = %s AND cpm.is_active AND tc.is_tracked
            ORDER BY latest.scraped_price NULLS LAST;
            """,
            (tenant_id, product_id),
        )
        product_competitors = []
        for cid, name, tier, url, price, currency, observed, available, previous_price, level, website, source_name in cursor.fetchall():
            # Where the price came from: the competitor's product page, a
            # connected data source, or an entry made by the team.
            source_kind = "product_page" if url else "data_source" if source_name else "manual"
            product_competitors.append({
                "competitor_id": str(cid),
                "name": name,
                "tier": tier,
                "level": level or "MARKET",
                "url": url,
                "website": website,
                "source": {"kind": source_kind, "url": url, "name": source_name, "recorded_at": observed.isoformat() if observed else None},
                "price": _num(price),
                "currency": currency,
                "observed_at": observed.isoformat() if observed else None,
                "available": available,
                "previous_price": _num(previous_price),
                "price_change_pct": _pct(float(price), float(previous_price)) if price is not None and previous_price else None,
                "vs_you_pct": _pct(float(price), product["current_price"]) if price is not None and currency == product["currency"] else None,
            })

        mapped_ids = [c["competitor_id"] for c in product_competitors]
        cursor.execute(
            """
            SELECT gc.global_competitor_id, gc.competitor_name, tc.tier, tc.competitor_scope, gc.website_url
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            -- Industry level = competitors the business marked as competing
            -- across its whole market. Product-level specialists (a honey
            -- shop, a coffee roaster) only appear on the products they are
            -- linked to, never on unrelated ones.
            WHERE tc.tenant_id = %s AND tc.is_tracked AND COALESCE(tc.competition_level, 'MARKET') = 'MARKET'
              AND NOT (tc.global_competitor_id::text = ANY(%s))
            ORDER BY CASE tc.tier WHEN 'STRATEGIC' THEN 0 WHEN 'RELEVANT' THEN 1 ELSE 2 END, gc.competitor_name
            LIMIT 12;
            """,
            (tenant_id, mapped_ids),
        )
        industry_competitors = [
            {"competitor_id": str(cid), "name": name, "tier": tier, "scope": scope, "website": website}
            for cid, name, tier, scope, website in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT COUNT(*), AVG(r.review_rating),
                   COUNT(*) FILTER (WHERE s.sentiment_label = 'POSITIVE'),
                   COUNT(*) FILTER (WHERE s.sentiment_label = 'NEGATIVE'),
                   COUNT(s.sentiment_label),
                   COUNT(*) FILTER (WHERE s.model_version = 'star-rating-v1')
            FROM reviews r
            LEFT JOIN sentiment_results s ON s.tenant_id = r.tenant_id AND s.review_id = r.review_id
            WHERE r.tenant_id = %s AND r.product_id = %s AND r.subject_type = 'PRODUCT';
            """,
            (tenant_id, product_id),
        )
        review_count, avg_rating, positive, negative, analysed, from_ratings = cursor.fetchone()
        cursor.execute(
            """
            SELECT r.review_date, r.review_rating, r.review_text, r.source_platform, s.sentiment_label
            FROM reviews r
            LEFT JOIN sentiment_results s ON s.tenant_id = r.tenant_id AND s.review_id = r.review_id
            WHERE r.tenant_id = %s AND r.product_id = %s AND r.subject_type = 'PRODUCT'
            ORDER BY r.review_date DESC NULLS LAST
            LIMIT 3;
            """,
            (tenant_id, product_id),
        )
        latest_reviews = [
            {"date": d.isoformat() if d else None, "rating": _num(rating), "text": text, "platform": platform, "sentiment": label}
            for d, rating, text, platform, label in cursor.fetchall()
        ]

    demand = forecast_overview.build_overview(conn, tenant_id, product_id, today=today)
    demand_row = next((p for p in demand["products"] if p["product_id"] == product_id), None) or {}

    units_30, units_prev = float(units_30), float(units_prev)
    revenue_30, revenue_prev = float(revenue_30), float(revenue_prev)
    sales = {
        "units_last_30": units_30,
        "units_previous_30": units_prev,
        "units_change_pct": _pct(units_30, units_prev),
        "revenue_last_30": round(revenue_30, 2),
        "revenue_previous_30": round(revenue_prev, 2),
        "revenue_change_pct": _pct(revenue_30, revenue_prev),
        "orders_last_30": int(orders_30),
        "units_all_time": float(units_all),
        "revenue_all_time": round(float(revenue_all), 2),
        "currency": sales_currency or product["currency"],
        "first_sale_at": first_sale.isoformat() if first_sale else None,
        "last_sale_at": last_sale.isoformat() if last_sale else None,
        "recent": recent_sales,
    }

    priced = [c for c in product_competitors if c["price"] is not None and c["currency"] == product["currency"]]
    market = None
    if priced:
        prices = [c["price"] for c in priced]
        market = {
            "competitors_priced": len(priced),
            "lowest": min(prices),
            "highest": max(prices),
            "average": round(sum(prices) / len(prices), 4),
            "your_price": product["current_price"],
            "cheaper_count": sum(1 for p in prices if p < product["current_price"]),
            "position_pct": _pct(product["current_price"], sum(prices) / len(prices)),
        }

    reviews = {
        "count": int(review_count),
        "average_rating": round(float(avg_rating), 2) if avg_rating is not None else None,
        "positive": int(positive),
        "negative": int(negative),
        "analysed": int(analysed),
        # How the sentiment was read: the text model, the customers' own star
        # ratings (when the model is unavailable), or both.
        "sentiment_basis": None if not analysed else "star_rating" if from_ratings == analysed else "model" if not from_ratings else "mixed",
        "latest": latest_reviews,
    }

    margin = None
    if product.get("cost_price") is not None and product["current_price"]:
        margin = round((product["current_price"] - product["cost_price"]) / product["current_price"] * 100, 1)

    # Depth beyond the headline price list: ratings, real comment counts, likes as agreement,
    # data completeness and reasons per competitor, the product's market-price coverage and
    # open-market reference prices. Additive - a failure here must never take the page down.
    market_detail = {"barcode": None, "price_coverage": None, "reference_prices": [], "reference_market": None}
    try:
        market_detail = product_market_detail(conn, tenant_id, product)
        details = competitor_details(conn, tenant_id, [c["competitor_id"] for c in product_competitors + industry_competitors])
        for competitor in product_competitors + industry_competitors:
            competitor["details"] = details.get(competitor["competitor_id"])
    except Exception:  # noqa: BLE001
        conn.rollback()
        logger.exception("could not load market detail for product %s", product_id)

    return {
        "product": {**product, "display_name": display_name, "display_category": display_category,
                    "display_brand": display_brand, "margin_pct": margin, "barcode": market_detail["barcode"]},
        "sales": sales,
        "demand": {
            "forecast_next_30": demand_row.get("forecast_next_30"),
            "forecast_lower": demand_row.get("forecast_lower"),
            "forecast_upper": demand_row.get("forecast_upper"),
            "forecast_created_at": demand_row.get("forecast_created_at"),
            "forecast_method": demand_row.get("forecast_method"),
            "trend": demand_row.get("trend"),
            "trend_change_pct": demand_row.get("trend_change_pct"),
            "expected_revenue": demand_row.get("expected_revenue"),
            "stock": {
                "current": demand_row.get("current_stock"),
                "reorder_level": demand_row.get("reorder_level"),
                "action": demand_row.get("stock_action"),
                "suggested_qty": demand_row.get("stock_suggested_qty"),
                "days_of_cover": demand_row.get("stock_days_of_cover"),
                "priority": demand_row.get("stock_priority"),
            },
            "series": demand["series"],
            "as_of": demand["as_of"],
        },
        "competitors": {
            "product_level": product_competitors, "industry_level": industry_competitors, "market": market,
            "price_coverage": market_detail["price_coverage"], "reference_prices": market_detail["reference_prices"],
            "reference_market": market_detail["reference_market"],
        },
        "reviews": reviews,
        "signals": _signals(sales, demand_row, market, reviews, product_competitors, industry_competitors),
    }


def _signals(sales, demand_row, market, reviews, product_competitors, industry_competitors) -> list:
    """Plain, data-backed observations, most important first. Each has a
    `kind` (the frontend words it in the user's language) and the numbers
    behind it."""
    signals = []
    action = demand_row.get("stock_action")
    if action == "restock":
        signals.append({"kind": "restock", "tone": "danger" if demand_row.get("stock_priority") == "high" else "warning",
                        "qty": demand_row.get("stock_suggested_qty"), "days": demand_row.get("stock_days_of_cover")})
    elif action == "reduce":
        signals.append({"kind": "overstock", "tone": "violet", "qty": demand_row.get("stock_suggested_qty"),
                        "days": demand_row.get("stock_days_of_cover")})

    change = sales["units_change_pct"]
    if change is not None and sales["units_previous_30"] >= TREND_MIN_UNITS:
        if change <= -TREND_PCT:
            signals.append({"kind": "sales_down", "tone": "danger", "pct": change})
        elif change >= TREND_PCT:
            signals.append({"kind": "sales_up", "tone": "success", "pct": change})
    if sales["last_sale_at"] and sales["units_last_30"] == 0:
        signals.append({"kind": "no_recent_sales", "tone": "warning", "since": sales["last_sale_at"]})

    if market:
        if market["position_pct"] is not None and market["position_pct"] >= PRICE_GAP_PCT:
            signals.append({"kind": "priced_above", "tone": "warning", "pct": market["position_pct"],
                            "cheaper_count": market["cheaper_count"], "count": market["competitors_priced"]})
        elif market["position_pct"] is not None and market["position_pct"] <= -PRICE_GAP_PCT:
            signals.append({"kind": "priced_below", "tone": "success", "pct": market["position_pct"],
                            "count": market["competitors_priced"]})
    elif not product_competitors:
        signals.append({"kind": "no_competitor_prices", "tone": "neutral", "industry_count": len(industry_competitors)})

    rising = [c for c in product_competitors if c["price_change_pct"] is not None and abs(c["price_change_pct"]) >= 3]
    for competitor in rising[:2]:
        signals.append({"kind": "competitor_price_change", "tone": "neutral", "name": competitor["name"],
                        "pct": competitor["price_change_pct"]})

    if reviews["analysed"] >= 5 and reviews["negative"] / reviews["analysed"] >= NEGATIVE_REVIEW_SHARE:
        signals.append({"kind": "negative_reviews", "tone": "warning",
                        "share": round(reviews["negative"] / reviews["analysed"] * 100), "count": reviews["analysed"]})
    return signals
