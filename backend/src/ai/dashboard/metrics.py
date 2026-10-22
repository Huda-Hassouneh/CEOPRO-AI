"""
KEEL - Dashboard Key Metrics (presentation layer, not a new model).

Pure aggregation over already-existing tables (invoices, invoice_items,
tenant_competitors) for the dashboard's top metric cards. Deliberately
does NOT touch, wrap, or reshape any existing model's input/output
contract (forecasting, sentiment, insights, pricing all stay exactly as
they are) - this module only counts and sums rows that already exist,
the same read-only aggregation style rag/structured_summaries.py's own
generate_sales_history_summary() already uses for the identical tables,
just returned as structured numbers instead of narrative text.

Explicitly out of scope, matching the current product scope: inventory
status (the `inventory` table is not populated by any real ingestion/
sales path yet - see PENDING_ACTIONS.md-equivalent discussion), Quick
Sale, and anything requiring login/billing.

Metric definitions (spelled out here since none of these numbers is
self-evidently unambiguous):
  revenue        Sum of PAID invoices.total_amount within the trailing window,
                 vs. the prior window of equal length. Summed across
                 whatever currencies exist on those invoices, same
                 simplification generate_sales_history_summary() already
                 makes - correct for the common single-currency-tenant
                 case; a genuinely multi-currency tenant would need a
                 real currency-aware rollup, not built here.
  units_sold     Sum of PAID invoice_items.quantity in the same two windows -
                 a distinct number from revenue (unit volume, not value).
  transaction_growth_pct
                 Percent change in PAID invoice COUNT (not amount) between the
                 two windows - "is the business making more separate
                 sales", a genuinely different signal than the revenue/
                 units totals above, not a restatement of either.
  competitors_tracked
                 Count of tenant_competitors with is_tracked = TRUE, plus
                 how many of those were added within the trailing window.
  market_sentiment
                 Business-wide sentiment (reviews.subject_type IN ('BUSINESS', 'PRODUCT')),
                 the exact same weighted (avg positive_probability - avg
                 negative_probability) formula sentiment/data_access.py::
                 load_aggregate_sentiment() already uses - just windowed
                 here (that function isn't) so a trend can be shown, and
                 rescaled from that function's native -1..1 range to a
                 0..100 display score via (score + 1) / 2 * 100, purely a
                 presentation transform, not a different metric.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ai.core.quantities import as_quantity
from src.ai.core.business_time import business_today, window_start

DEFAULT_WINDOW_DAYS = 30


def _pct_change(recent: float, prior: float) -> Optional[float]:
    """None (never a fabricated 0% or 100%) when there's no prior-window
    value to compare against - same "don't manufacture a trend from
    nothing" discipline insights/pipeline.py's own sales-trend loader
    already follows."""
    if prior <= 0:
        return None
    return round((recent - prior) / prior * 100, 1)


def _first_sale_at(conn, tenant_id: str):
    with conn.cursor() as cursor:
        cursor.execute("SELECT MIN(issue_date) FROM invoices WHERE tenant_id = %s AND payment_status = 'PAID';", (tenant_id,))
        row = cursor.fetchone()
    return row[0] if row else None


def get_dashboard_metrics(conn, tenant_id: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, window_days)
    prior_start = window_start(conn, window_days, periods=2)
    # Period-over-period change is only meaningful when the tenant's sales
    # history actually covers the whole prior window. Found in first-customer
    # acceptance testing: with history starting June 8, the 90-day view
    # compared against a "prior 90 days" that was mostly before the first
    # sale and showed "Growth +205.2%" - a real-looking number that was an
    # artefact of missing history, not growth. Partial coverage -> None.
    first_sale_at = _first_sale_at(conn, tenant_id)
    prior_window_covered = first_sale_at is not None and first_sale_at.date() <= prior_start

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN issue_date >= %(recent_start)s THEN total_amount ELSE 0 END), 0) AS recent_revenue,
                COALESCE(SUM(CASE WHEN issue_date >= %(prior_start)s AND issue_date < %(recent_start)s
                    THEN total_amount ELSE 0 END), 0) AS prior_revenue,
                COUNT(*) FILTER (WHERE issue_date >= %(recent_start)s) AS recent_invoice_count,
                COUNT(*) FILTER (WHERE issue_date >= %(prior_start)s AND issue_date < %(recent_start)s) AS prior_invoice_count
            FROM invoices
            WHERE tenant_id = %(tenant_id)s AND payment_status = 'PAID' AND issue_date >= %(prior_start)s;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start, "prior_start": prior_start},
        )
        recent_revenue, prior_revenue, recent_invoice_count, prior_invoice_count = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN i.issue_date >= %(recent_start)s THEN ii.quantity ELSE 0 END), 0) AS recent_units,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(prior_start)s AND i.issue_date < %(recent_start)s
                    THEN ii.quantity ELSE 0 END), 0) AS prior_units
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE ii.tenant_id = %(tenant_id)s AND i.payment_status = 'PAID'
              AND i.issue_date >= %(prior_start)s;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start, "prior_start": prior_start},
        )
        recent_units, prior_units = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_tracked = TRUE) AS tracked_count,
                COUNT(*) FILTER (WHERE is_tracked = TRUE AND added_at >= %(recent_start)s) AS new_this_window
            FROM tenant_competitors
            WHERE tenant_id = %(tenant_id)s;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start},
        )
        tracked_count, new_this_window = cursor.fetchone()

        cursor.execute("SELECT primary_currency FROM companies WHERE tenant_id = %s;", (tenant_id,))
        currency_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                CASE WHEN COUNT(*) FILTER (WHERE r.review_date >= %(recent_start)s) = 0 THEN NULL ELSE
                    SUM(sr.positive_probability - sr.negative_probability) FILTER (WHERE r.review_date >= %(recent_start)s)
                    / COUNT(*) FILTER (WHERE r.review_date >= %(recent_start)s)
                END AS recent_score,
                CASE WHEN COUNT(*) FILTER (WHERE r.review_date >= %(prior_start)s AND r.review_date < %(recent_start)s) = 0 THEN NULL ELSE
                    SUM(sr.positive_probability - sr.negative_probability)
                        FILTER (WHERE r.review_date >= %(prior_start)s AND r.review_date < %(recent_start)s)
                    / COUNT(*) FILTER (WHERE r.review_date >= %(prior_start)s AND r.review_date < %(recent_start)s)
                END AS prior_score
            FROM reviews r
            JOIN sentiment_results sr ON sr.review_id = r.review_id
            -- The business's own reviews: about the business itself or one of
            -- its products (competitor reviews are excluded). Product reviews
            -- used to be left out, so a business whose feedback is mostly
            -- per-product had no sentiment score at all.
            WHERE r.tenant_id = %(tenant_id)s AND r.subject_type IN ('BUSINESS', 'PRODUCT')
              AND r.review_date >= %(prior_start)s;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start, "prior_start": prior_start},
        )
        recent_sentiment, prior_sentiment = cursor.fetchone()

    market_sentiment = None
    if recent_sentiment is not None:
        recent_display_score = round((float(recent_sentiment) + 1) / 2 * 100, 1)
        change_pts = None
        if prior_sentiment is not None:
            prior_display_score = round((float(prior_sentiment) + 1) / 2 * 100, 1)
            change_pts = round(recent_display_score - prior_display_score, 1)
        market_sentiment = {"score": recent_display_score, "change_pts": change_pts}

    def change(recent, prior):
        return _pct_change(float(recent), float(prior)) if prior_window_covered else None

    return {
        "window_days": window_days,
        "revenue": {
            "amount": float(recent_revenue),
            "currency": currency_row[0] if currency_row else None,
            "change_pct": change(recent_revenue, prior_revenue),
        },
        "units_sold": {
            "units": as_quantity(recent_units),
            "change_pct": change(recent_units, prior_units),
        },
        "transaction_growth_pct": change(recent_invoice_count, prior_invoice_count),
        "history_covers_prior_window": prior_window_covered,
        "competitors_tracked": {
            "count": int(tracked_count),
            "new_this_window": int(new_this_window),
        },
        "market_sentiment": market_sentiment,
    }


def get_sales_trend(conn, tenant_id: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Daily revenue and units for the Dashboard's Sales Overview chart.

    Uses exactly the same window and source (invoices.total_amount,
    invoice_items.quantity) as get_dashboard_metrics(), so the chart's points
    always sum to the Revenue/Total Sales cards above it. Days without sales
    are explicit zeros rather than gaps. The chart used to have no backing
    endpoint at all and always said "No sales data", even for a tenant with
    thousands of imported sales.
    """
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, window_days)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.issue_date::date AS day,
                   SUM(i.total_amount) AS revenue
            FROM invoices i
            WHERE i.tenant_id = %(tenant_id)s AND i.payment_status = 'PAID'
              AND i.issue_date >= %(recent_start)s
            GROUP BY day;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start},
        )
        revenue_by_day = {day: float(revenue) for day, revenue in cursor.fetchall()}
        cursor.execute(
            """
            SELECT i.issue_date::date AS day, SUM(ii.quantity) AS units
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE ii.tenant_id = %(tenant_id)s AND i.payment_status = 'PAID'
              AND i.issue_date >= %(recent_start)s
            GROUP BY day;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start},
        )
        units_by_day = {day: as_quantity(units) for day, units in cursor.fetchall()}
        cursor.execute("SELECT primary_currency FROM companies WHERE tenant_id = %s;", (tenant_id,))
        currency_row = cursor.fetchone()

    # The same calendar days as the KPI cards: the last `window_days` days in
    # the company's time zone, today included, so the points sum to them.
    day = window_start(conn, window_days)
    today = business_today(conn)
    points = []
    while day <= today:
        points.append({"date": day.isoformat(), "value": round(revenue_by_day.get(day, 0.0), 2), "units": units_by_day.get(day, 0)})
        day += timedelta(days=1)
    return {
        "window_days": window_days,
        "currency": currency_row[0] if currency_row else None,
        "has_data": any(point["value"] or point["units"] for point in points),
        "points": points,
    }
