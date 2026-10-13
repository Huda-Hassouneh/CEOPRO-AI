"""
KEEL - Financial/Profitability Summary (presentation layer, not a new
model). Same pure-aggregation style as dashboard/metrics.py, extended to
the one thing that module explicitly doesn't compute: cost, gross profit,
and gross margin.

Built for the RAG Business Copilot's financial questions ("which products
are most profitable", "where did my profit go", "why did revenue
decrease") - src/ai/rag/business_tools.py calls these functions and
formats their output into the chat prompt. This module itself has no RAG/
LLM dependency; it is a plain, deterministic, directly-testable read layer,
matching this feature's own "use deterministic calculations, not LLM
arithmetic" requirement.

## What this can and cannot answer

`products.cost_price` is nullable (Final_schema.sql) - a tenant is never
required to enter it. Every function here is explicit about how much of
the revenue it summed actually has a known cost: `cost_data_coverage_pct`
on the summary, `has_cost_data` per product row. A product/period with no
cost data contributes to revenue and units but is excluded from cost/
margin math entirely - never assumed to have zero cost (which would
fabricate an inflated margin).

This computes **gross profit/gross margin** only: revenue minus cost of
goods sold (unit_price - cost_price, summed across items sold). It does
NOT include fixed operating expenses, marketing spend, discounts/returns,
or any other overhead - this schema has no tables for any of those today.
Callers (the chat prompt, eventually) must say "gross margin", never bare
"profit", and must say plainly that net profit/fixed costs are not
tracked - never imply this is the tenant's full P&L.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from src.ai.core.quantities import as_quantity
from src.ai.core.business_time import window_start

DEFAULT_WINDOW_DAYS = 30
DEFAULT_PRODUCT_LIMIT = 10


def _pct_change(recent: float, prior: float) -> Optional[float]:
    """None (never a fabricated 0%/100%) when there's no prior-window
    value to compare against - same convention as dashboard/metrics.py's
    own _pct_change()."""
    if prior <= 0:
        return None
    return round((recent - prior) / prior * 100, 1)


def get_profitability_summary(conn, tenant_id: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """
    Business-wide revenue / cost of goods sold / gross profit / gross
    margin for the trailing `window_days`, vs. the prior window of equal
    length - same two-window comparison convention as
    dashboard/metrics.py::get_dashboard_metrics(). Revenue here is summed
    from invoice_items (unit_price * quantity), not invoices.total_amount
    (which includes tax) - the right base for a cost/margin comparison,
    a deliberate difference from metrics.py's own top-line revenue figure.
    """
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, window_days)
    prior_start = window_start(conn, window_days, periods=2)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN i.issue_date >= %(recent_start)s
                    THEN ii.total_price ELSE 0 END), 0) AS recent_revenue,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(recent_start)s AND p.cost_price IS NOT NULL
                    THEN ii.quantity * p.cost_price ELSE 0 END), 0) AS recent_cogs,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(recent_start)s AND p.cost_price IS NOT NULL
                    THEN ii.total_price ELSE 0 END), 0) AS recent_revenue_with_cost_data,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(prior_start)s AND i.issue_date < %(recent_start)s
                    THEN ii.total_price ELSE 0 END), 0) AS prior_revenue,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(prior_start)s AND i.issue_date < %(recent_start)s
                    AND p.cost_price IS NOT NULL THEN ii.quantity * p.cost_price ELSE 0 END), 0) AS prior_cogs,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(prior_start)s AND i.issue_date < %(recent_start)s
                    AND p.cost_price IS NOT NULL THEN ii.total_price ELSE 0 END), 0) AS prior_revenue_with_cost_data
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
            WHERE ii.tenant_id = %(tenant_id)s AND i.issue_date >= %(prior_start)s;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start, "prior_start": prior_start},
        )
        (
            recent_revenue, recent_cogs, recent_revenue_with_cost_data,
            prior_revenue, prior_cogs, prior_revenue_with_cost_data,
        ) = cursor.fetchone()

        cursor.execute("SELECT primary_currency FROM companies WHERE tenant_id = %s;", (tenant_id,))
        currency_row = cursor.fetchone()

    recent_revenue, recent_cogs, recent_revenue_with_cost_data = float(recent_revenue), float(recent_cogs), float(recent_revenue_with_cost_data)
    prior_revenue, prior_cogs, prior_revenue_with_cost_data = float(prior_revenue), float(prior_cogs), float(prior_revenue_with_cost_data)

    recent_gross_profit = recent_revenue_with_cost_data - recent_cogs
    prior_gross_profit = prior_revenue_with_cost_data - prior_cogs
    recent_margin_pct = round(recent_gross_profit / recent_revenue_with_cost_data * 100, 1) if recent_revenue_with_cost_data > 0 else None
    prior_margin_pct = round(prior_gross_profit / prior_revenue_with_cost_data * 100, 1) if prior_revenue_with_cost_data > 0 else None

    return {
        "window_days": window_days,
        "currency": currency_row[0] if currency_row else None,
        "revenue": {"amount": round(recent_revenue, 2), "change_pct": _pct_change(recent_revenue, prior_revenue)},
        "cost_data_coverage_pct": round(recent_revenue_with_cost_data / recent_revenue * 100, 1) if recent_revenue > 0 else None,
        "gross_profit": {
            "amount": round(recent_gross_profit, 2) if recent_revenue_with_cost_data > 0 else None,
            "change_pct": (
                _pct_change(recent_gross_profit, prior_gross_profit)
                if recent_revenue_with_cost_data > 0 and prior_revenue_with_cost_data > 0 else None
            ),
        },
        "gross_margin_pct": {
            "recent": recent_margin_pct,
            "change_pts": round(recent_margin_pct - prior_margin_pct, 1) if recent_margin_pct is not None and prior_margin_pct is not None else None,
        },
        # Never omitted - every caller (especially the chat prompt) must
        # be able to say plainly what this figure does not include.
        "excludes": ["fixed_operating_expenses", "marketing_spend", "discounts_and_returns", "taxes"],
        # Raw (unrounded) components, for analyze_margin_change()'s own
        # decomposition below - reusing this function's own query results
        # instead of a second copy of the same SQL. Not primarily meant
        # for direct chat-facing display (the rounded fields above are).
        "_components": {
            "recent_revenue_with_cost_data": recent_revenue_with_cost_data,
            "recent_cogs": recent_cogs,
            "prior_revenue_with_cost_data": prior_revenue_with_cost_data,
            "prior_cogs": prior_cogs,
        },
    }


def get_product_profitability(conn, tenant_id: str, window_days: int = DEFAULT_WINDOW_DAYS, limit: int = DEFAULT_PRODUCT_LIMIT) -> dict:
    """
    Per-product revenue/units/gross-profit/gross-margin for the trailing
    `window_days`, split into `most_profitable` (highest gross profit,
    only among products with known cost_price) and `no_cost_data`
    (sold in-window but cost_price is unset, so profitability cannot be
    computed - listed separately rather than silently dropped, so a
    tenant can see exactly what's missing and why "which products are
    losing money" might be incomplete without it).
    """
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, window_days)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                p.product_id,
                localized_text(p.product_name) AS product_name,
                p.cost_price IS NOT NULL AS has_cost_data,
                SUM(ii.quantity) AS units_sold,
                SUM(ii.total_price) AS revenue,
                SUM(ii.quantity * p.cost_price) FILTER (WHERE p.cost_price IS NOT NULL) AS cogs
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
            WHERE ii.tenant_id = %(tenant_id)s AND i.issue_date >= %(recent_start)s
            GROUP BY p.product_id, p.product_name, p.cost_price;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start},
        )
        rows = cursor.fetchall()

    with_cost_data, without_cost_data = [], []
    for product_id, product_name, has_cost_data, units_sold, revenue, cogs in rows:
        revenue = float(revenue)
        row = {
            "product_id": str(product_id), "product_name": product_name,
            "units_sold": as_quantity(units_sold), "revenue": round(revenue, 2),
        }
        if has_cost_data:
            gross_profit = revenue - float(cogs)
            row["gross_profit"] = round(gross_profit, 2)
            row["gross_margin_pct"] = round(gross_profit / revenue * 100, 1) if revenue > 0 else None
            with_cost_data.append(row)
        else:
            without_cost_data.append(row)

    most_profitable = sorted(with_cost_data, key=lambda r: r["gross_profit"], reverse=True)[:limit]
    least_profitable = sorted(with_cost_data, key=lambda r: r["gross_profit"])[:limit]

    return {
        "window_days": window_days,
        "most_profitable": most_profitable,
        "least_profitable": least_profitable,
        "no_cost_data": without_cost_data,
    }


# ---------------------------------------------------------------------------
# Root-cause decomposition (B5/B6 - Business Copilot Phase 2)
#
# Both functions below are DETERMINISTIC arithmetic over real query
# results - no LLM is involved in producing a single number here. What
# they add over get_profitability_summary()/get_product_profitability()
# is decomposition: not just "revenue changed by X%", but "X% of that
# change came from unit volume vs. average selling price" (an exact,
# textbook-standard decomposition, not a guess), and "here are the
# specific products whose revenue moved the most" (a correlation/signal -
# these products' revenue changed alongside the total, not proof that
# they CAUSED it, and every caller must say so, per this feature's own
# "if only correlation/signals exist, say so explicitly" requirement).
# Neither function invents a cause this schema cannot support (marketing
# spend, discounts, competitor actions) - see each docstring's own
# "explicitly not covered" note.
# ---------------------------------------------------------------------------

DEFAULT_MOVERS_LIMIT = 5


def analyze_revenue_change(conn, tenant_id: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """
    Decomposes the revenue change get_profitability_summary() already
    reports into units-sold vs. average-selling-price effects (exact,
    additive: delta_revenue == units_effect + price_effect, standard
    variance-decomposition algebra, not a heuristic), plus the specific
    products whose revenue moved most (an observed correlation with the
    total change, not a causal claim - callers must present it as such).

    Explicitly NOT covered (no data exists for these in this schema):
    marketing spend/campaign attribution, discounts/promotions,
    competitor actions, seasonality. If a product's revenue mix shifted,
    this can say WHICH product and BY HOW MUCH, never WHY.
    """
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, window_days)
    prior_start = window_start(conn, window_days, periods=2)

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                p.product_id,
                localized_text(p.product_name) AS product_name,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(recent_start)s THEN ii.quantity ELSE 0 END), 0) AS recent_units,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(recent_start)s THEN ii.total_price ELSE 0 END), 0) AS recent_revenue,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(prior_start)s AND i.issue_date < %(recent_start)s THEN ii.quantity ELSE 0 END), 0) AS prior_units,
                COALESCE(SUM(CASE WHEN i.issue_date >= %(prior_start)s AND i.issue_date < %(recent_start)s THEN ii.total_price ELSE 0 END), 0) AS prior_revenue
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
            WHERE ii.tenant_id = %(tenant_id)s AND i.issue_date >= %(prior_start)s
            GROUP BY p.product_id, p.product_name;
            """,
            {"tenant_id": tenant_id, "recent_start": recent_start, "prior_start": prior_start},
        )
        rows = cursor.fetchall()

    recent_units_total = sum(float(r[2]) for r in rows)
    recent_revenue_total = sum(float(r[3]) for r in rows)
    prior_units_total = sum(float(r[4]) for r in rows)
    prior_revenue_total = sum(float(r[5]) for r in rows)

    if prior_revenue_total <= 0 and recent_revenue_total <= 0:
        return {"window_days": window_days, "has_data": False}

    recent_asp = recent_revenue_total / recent_units_total if recent_units_total > 0 else None
    prior_asp = prior_revenue_total / prior_units_total if prior_units_total > 0 else None

    units_effect = None
    price_effect = None
    if prior_asp is not None and prior_units_total > 0:
        # Exact additive decomposition: delta_revenue = delta_units * prior_ASP
        # + recent_units * delta_ASP. Requires a known prior ASP (i.e. the
        # prior window had at least one unit sold) - otherwise there is no
        # meaningful "price" to compare against, only "went from 0 to something".
        units_effect = round((recent_units_total - prior_units_total) * prior_asp, 2)
        if recent_asp is not None:
            price_effect = round(recent_units_total * (recent_asp - prior_asp), 2)

    movers = []
    for product_id, product_name, recent_units, recent_revenue, prior_units, prior_revenue in rows:
        delta = float(recent_revenue) - float(prior_revenue)
        if delta == 0:
            continue
        movers.append({
            "product_id": str(product_id),
            "product_name": product_name,
            "recent_revenue": round(float(recent_revenue), 2),
            "prior_revenue": round(float(prior_revenue), 2),
            "revenue_change": round(delta, 2),
        })
    movers.sort(key=lambda m: abs(m["revenue_change"]), reverse=True)

    return {
        "window_days": window_days,
        "has_data": True,
        "revenue_change": round(recent_revenue_total - prior_revenue_total, 2),
        "units_sold_change": recent_units_total - prior_units_total,
        "average_selling_price": {"recent": round(recent_asp, 2) if recent_asp is not None else None, "prior": round(prior_asp, 2) if prior_asp is not None else None},
        "drivers": {
            "units_effect": units_effect,
            "price_effect": price_effect,
            "note": (
                "units_effect + price_effect should approximately equal revenue_change "
                "(exact arithmetic decomposition, real numbers - not an estimate)."
                if units_effect is not None else
                "Cannot decompose into units/price effects - the prior period had zero units sold."
            ),
        },
        "top_movers": movers[:DEFAULT_MOVERS_LIMIT],
        "movers_caveat": (
            "top_movers lists which products' revenue changed the most alongside the total change - "
            "this is a correlation/signal, not proof of causation. This schema has no marketing-spend, "
            "discount, or competitor-action data to attribute a specific cause to any of these products."
        ),
    }


def analyze_margin_change(conn, tenant_id: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """
    Decomposes the gross-margin change get_profitability_summary() already
    reports into how much came from revenue (with cost data) moving vs.
    how much came from cost of goods sold moving - reuses that function's
    own query results (via its "_components" field) rather than a second
    copy of the same SQL.

    Explicitly NOT covered: this is still gross margin only (see this
    module's own top-level docstring) - fixed costs, marketing spend, and
    discounts remain untracked and unattributed here too.
    """
    summary = get_profitability_summary(conn, tenant_id, window_days=window_days)
    components = summary["_components"]

    recent_rev = components["recent_revenue_with_cost_data"]
    recent_cogs = components["recent_cogs"]
    prior_rev = components["prior_revenue_with_cost_data"]
    prior_cogs = components["prior_cogs"]

    if prior_rev <= 0 and recent_rev <= 0:
        return {"window_days": window_days, "has_data": False}

    # gross_profit = revenue_with_cost_data - cogs, so this split is exact:
    # delta_gross_profit == revenue_effect + cogs_effect (cogs_effect
    # negative when COGS rose, since rising COGS reduces gross profit).
    revenue_effect = round(recent_rev - prior_rev, 2)
    cogs_effect = round(-(recent_cogs - prior_cogs), 2)

    return {
        "window_days": window_days,
        "has_data": True,
        "gross_profit": summary["gross_profit"],
        "gross_margin_pct": summary["gross_margin_pct"],
        "cost_data_coverage_pct": summary["cost_data_coverage_pct"],
        "drivers": {
            "revenue_effect": revenue_effect,
            "cogs_effect": cogs_effect,
            "note": "revenue_effect + cogs_effect == the gross_profit change (exact arithmetic, both from real invoice/cost data).",
        },
        "excludes": summary["excludes"],
    }
