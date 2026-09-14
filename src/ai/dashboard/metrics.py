"""
CEOPRO AI - Dashboard Key Metrics (presentation layer, not a new model).

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
  revenue        Sum of invoices.total_amount within the trailing window,
                 vs. the prior window of equal length. Summed across
                 whatever currencies exist on those invoices, same
                 simplification generate_sales_history_summary() already
                 makes - correct for the common single-currency-tenant
                 case; a genuinely multi-currency tenant would need a
                 real currency-aware rollup, not built here.
  units_sold     Sum of invoice_items.quantity in the same two windows -
                 a distinct number from revenue (unit volume, not value).
  transaction_growth_pct
                 Percent change in invoice COUNT (not amount) between the
                 two windows - "is the business making more separate
                 sales", a genuinely different signal than the revenue/
                 units totals above, not a restatement of either.
  competitors_tracked
                 Count of tenant_competitors with is_tracked = TRUE, plus
                 how many of those were added within the trailing window.
  market_sentiment
                 Business-wide sentiment (reviews.subject_type = 'BUSINESS'),
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

DEFAULT_WINDOW_DAYS = 30


def _pct_change(recent: float, prior: float) -> Optional[float]:
    """None (never a fabricated 0% or 100%) when there's no prior-window
    value to compare against - same "don't manufacture a trend from
    nothing" discipline insights/pipeline.py's own sales-trend loader
    already follows."""
    if prior <= 0:
        return None
    return round((recent - prior) / prior * 100, 1)


def get_dashboard_metrics(conn, tenant_id: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=window_days)
    prior_start = now - timedelta(days=2 * window_days)

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
            WHERE tenant_id = %(tenant_id)s AND issue_date >= %(prior_start)s;
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
            WHERE ii.tenant_id = %(tenant_id)s AND i.issue_date >= %(prior_start)s;
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
            WHERE r.tenant_id = %(tenant_id)s AND r.subject_type = 'BUSINESS' AND r.review_date >= %(prior_start)s;
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

    return {
        "window_days": window_days,
        "revenue": {
            "amount": float(recent_revenue),
            "currency": currency_row[0] if currency_row else None,
            "change_pct": _pct_change(float(recent_revenue), float(prior_revenue)),
        },
        "units_sold": {
            "units": int(recent_units),
            "change_pct": _pct_change(float(recent_units), float(prior_units)),
        },
        "transaction_growth_pct": _pct_change(float(recent_invoice_count), float(prior_invoice_count)),
        "competitors_tracked": {
            "count": int(tracked_count),
            "new_this_window": int(new_this_window),
        },
        "market_sentiment": market_sentiment,
    }
