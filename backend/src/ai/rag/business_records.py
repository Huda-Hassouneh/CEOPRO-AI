"""
KEEL - exact business records for the assistant, computed for the question.

structured_context.py gives every question the same fixed snapshot (the last
30 days, the top 5 products, five forecasts). That cannot answer "how much did
we sell in March?", "Q2 2026 vs Q2 2025", "how many Sidr Honey did we sell last
month?", "what is my stock of olive oil?" or "has customer sentiment improved?":
the figure asked for is not in the snapshot, so the model either says it has no
information or reaches for a number from the wrong period.

This module runs the query the question needs, for the periods and products it
names (understanding.py resolves "last month", "آذار", "Q2 2025" and "the honey"
to exact dates and catalogue products), with plain SQL aggregates - never the
model's arithmetic, never document similarity search:

- sales for each period: revenue and invoices (invoices.total_amount by
  issue_date, the dashboard's definition), units and revenue per product,
  the top products by revenue and by units, the change against the period
  before, gross profit when the member may see costs, a month-by-month
  series, the biggest customers, and the period's coverage by the records;
- each named product's sales, stock, reorder level, days of cover and latest
  demand forecast;
- customer reviews for a period: positive / neutral / negative counts and
  average rating, month by month, so a change of opinion is measured.

Every line names its source. A period with no records says so, with the dates
the records do cover - never a zero presented as a real result. All queries
are tenant-scoped (and RLS-protected by the connection's role).
"""
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

from src.ai.core.money import format_money_text as format_money
from src.ai.core.quantities import format_quantity
from src.ai.rag import periods as _periods

TOP_PRODUCTS = 10
TOP_CUSTOMERS = 10
MAX_SERIES_MONTHS = 24
SERIES_MIN_DAYS = 85  # a quarter or longer gets its month-by-month figures
STOCK_LIST_LIMIT = 40
FORECAST_LIST_LIMIT = 30


def _d(value: str) -> date:
    return date.fromisoformat(value)


def _span(period: dict) -> str:
    return _periods.label_dates(period)


def _pct(new: float, old: float) -> Optional[str]:
    if not old:
        return None
    change = (new - old) / old * 100
    return f"{change:+.1f}%"


def _money(value, currency: str) -> str:
    return f"{format_money(value or 0, currency)} {currency}"


def sales_coverage(conn, tenant_id: str) -> Optional[tuple]:
    """(first, last) dates with a recorded invoice, or None when there are none."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT MIN(issue_date)::date, MAX(issue_date)::date FROM invoices WHERE tenant_id = %s;",
                       (tenant_id,))
        row = cursor.fetchone()
    return (row[0], row[1]) if row and row[0] else None


def _totals(cursor, tenant_id: str, start: date, end: date) -> Dict[str, tuple]:
    cursor.execute(
        """
        SELECT currency, COALESCE(SUM(total_amount), 0), COUNT(*)
        FROM invoices WHERE tenant_id = %s AND issue_date >= %s AND issue_date < %s
        GROUP BY currency ORDER BY 2 DESC;
        """,
        (tenant_id, start, end),
    )
    return {currency: (float(total), int(count)) for currency, total, count in cursor.fetchall()}


def _product_rows(cursor, tenant_id: str, start: date, end: date, language: str,
                  product_ids: Optional[Sequence[str]] = None) -> List[tuple]:
    """(product_id, name, currency, units, revenue, invoices, cost) per product sold in [start, end)."""
    lang = "ar" if language == "ar" else "en"
    cursor.execute(
        f"""
        SELECT p.product_id, localized_text(p.product_name, '{lang}'), i.currency,
               SUM(ii.quantity), SUM(ii.total_price), COUNT(DISTINCT ii.invoice_id),
               SUM(ii.quantity * p.cost_price)
        FROM invoice_items ii
        JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
        JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
        WHERE ii.tenant_id = %s AND i.issue_date >= %s AND i.issue_date < %s
          AND (cardinality(%s::uuid[]) = 0 OR ii.product_id = ANY(%s::uuid[]))
        GROUP BY p.product_id, p.product_name, i.currency;
        """,
        (tenant_id, start, end, list(product_ids or []), list(product_ids or [])),
    )
    return cursor.fetchall()


def _coverage_note(period: dict, coverage: Optional[tuple]) -> Optional[str]:
    if coverage is None:
        return None
    first, last = coverage
    start, end = _d(period["start"]), _d(period["end"]) - timedelta(days=1)
    if start < first or end > last:
        return (f"Note: your sales records run from {first.isoformat()} to {last.isoformat()}, so only that part "
                f"of {period['label']} ({_span(period)}) has records.")
    return None


def sales_lines(conn, tenant_id: str, period: dict, *, product_ids: Sequence[str] = (), with_costs: bool = False,
                language: str = "en", series: bool = False, customers: bool = False,
                coverage: Optional[tuple] = None, compare_previous: bool = True,
                top: int = TOP_PRODUCTS) -> List[str]:
    """Header + "- " lines with the exact sales of `period` (see the module docstring)."""
    start, end = _d(period["start"]), _d(period["end"])
    label = f"{period['label']} ({_span(period)})"
    lines: List[str] = []
    with conn.cursor() as cursor:
        totals = _totals(cursor, tenant_id, start, end)
        if not totals:
            span = (f" Your sales records run from {coverage[0].isoformat()} to {coverage[1].isoformat()}."
                    if coverage else " No sales are recorded at all yet.")
            return [f"Sales for {label} (source: invoices by issue_date): no sales are recorded in this period.{span}"]
        previous = _periods.previous_period(period) if compare_previous else None
        before = _totals(cursor, tenant_id, _d(previous["start"]), _d(previous["end"])) if previous else {}
        rows = _product_rows(cursor, tenant_id, start, end, language)
        lines.append(f"Sales for {label} (source: invoices.total_amount by issue_date, the same revenue definition as "
                     f"the dashboard):")
        for currency, (total, count) in totals.items():
            text = f"- Revenue {_money(total, currency)} from {count} invoices in {period['label']}"
            prior = before.get(currency)
            if previous:
                if prior:
                    change = _pct(total, prior[0])
                    named = previous["label"] if previous["label"] == _span(previous) else \
                        f"{previous['label']} ({_span(previous)})"
                    text += (f"; {named}: {_money(prior[0], currency)} from {prior[1]} invoices"
                             + (f", a change of {change}" if change else ""))
                    if coverage and _d(previous["start"]) < coverage[0] < _d(previous["end"]):
                        text += (f" (but your records only start on {coverage[0].isoformat()}, so that earlier "
                                 f"period is incomplete and the change is not like for like)")
                elif coverage and _d(previous["end"]) <= coverage[0]:
                    text += f"; there are no records for the period before ({previous['label']}) to compare with"
                else:
                    text += f"; no sales recorded in the period before ({previous['label']})"
            lines.append(text + ".")
            units = sum(float(r[3] or 0) for r in rows if r[2] == currency)
            if count:
                lines.append(f"- In {period['label']}: {format_quantity(units)} units sold across all products; "
                             f"average invoice {_money(total / count, currency)}.")
            if with_costs:
                costed = [r for r in rows if r[2] == currency and r[6] is not None]
                item_revenue = sum(float(r[4] or 0) for r in rows if r[2] == currency)
                if costed and item_revenue:
                    revenue = sum(float(r[4] or 0) for r in costed)
                    profit = revenue - sum(float(r[6]) for r in costed)
                    share = revenue / item_revenue * 100
                    lines.append(
                        f"- Gross profit in {period['label']} (product line revenue minus quantity x the product's "
                        f"current recorded cost price): {_money(profit, currency)}, a gross margin of "
                        f"{profit / revenue * 100:.1f}% on {_money(revenue, currency)} of product revenue "
                        f"({share:.1f}% of product revenue has a cost price on file). Operating expenses, "
                        f"marketing, discounts and taxes are not included.")
        note = _coverage_note(period, coverage)
        if note:
            lines.append(f"- {note}")

        by_revenue = sorted(rows, key=lambda r: -float(r[4] or 0))[:top]
        if by_revenue:
            lines.append(f"Top products by revenue in {label} (source: invoice_items joined to products):")
            for rank, (_pid, name, currency, units, revenue, invoices, _cost) in enumerate(by_revenue, 1):
                lines.append(f"- #{rank} {name}: {_money(revenue, currency)} from {format_quantity(units)} units "
                             f"in {period['label']}.")
            by_units = sorted(rows, key=lambda r: -float(r[3] or 0))[:top]
            lines.append(f"Top products by units sold in {label} (source: invoice_items joined to products):")
            for rank, (_pid, name, currency, units, revenue, invoices, _cost) in enumerate(by_units, 1):
                lines.append(f"- #{rank} {name}: {format_quantity(units)} units ({_money(revenue, currency)}) "
                             f"in {period['label']}.")

        if product_ids:
            named = {str(r[0]): r for r in rows if str(r[0]) in set(product_ids)}
            prior_rows = ({str(r[0]): r for r in _product_rows(cursor, tenant_id, _d(previous["start"]),
                                                                 _d(previous["end"]), language, product_ids)}
                          if previous else {})
            lines.append(f"Sales of the products asked about in {label} (source: invoice_items):")
            for product_id in product_ids:
                row = named.get(product_id)
                if row is None:
                    name = _product_name(cursor, tenant_id, product_id, language)
                    lines.append(f"- {name}: no units sold in {period['label']}.")
                    continue
                _pid, name, currency, units, revenue, invoices, _cost = row
                text = (f"- {name}: {format_quantity(units)} units sold for {_money(revenue, currency)} on "
                        f"{invoices} invoices in {period['label']} (average {_money(float(revenue) / float(units), currency)}"
                        f" per unit)" if units else f"- {name}: no units sold in {period['label']}")
                prior = prior_rows.get(product_id)
                if previous and prior:
                    change = _pct(float(units or 0), float(prior[3] or 0))
                    text += (f"; {previous['label']}: {format_quantity(prior[3])} units for "
                             f"{_money(prior[4], prior[2])}" + (f" ({change} in units)" if change else ""))
                lines.append(text + ".")

        if series or (compare_previous and (end - start).days >= SERIES_MIN_DAYS):
            lines += _monthly_series(cursor, tenant_id, start, end, period["label"])
        if customers:
            lines += _top_customers(cursor, tenant_id, start, end, label)
    return lines


def _product_name(cursor, tenant_id: str, product_id: str, language: str) -> str:
    lang = "ar" if language == "ar" else "en"
    cursor.execute(f"SELECT localized_text(product_name, '{lang}') FROM products WHERE tenant_id = %s AND product_id = %s;",
                   (tenant_id, product_id))
    row = cursor.fetchone()
    return row[0] if row else "This product"


def _monthly_series(cursor, tenant_id: str, start: date, end: date, label: str) -> List[str]:
    cursor.execute(
        """
        SELECT to_char(date_trunc('month', issue_date), 'YYYY-MM'), currency, SUM(total_amount), COUNT(*)
        FROM invoices WHERE tenant_id = %s AND issue_date >= %s AND issue_date < %s
        GROUP BY 1, 2 ORDER BY 1 LIMIT %s;
        """,
        (tenant_id, start, end, MAX_SERIES_MONTHS * 3),
    )
    rows = cursor.fetchall()
    if len({r[0] for r in rows}) < 2:
        return []
    out = [f"Revenue month by month in {label} (source: invoices.total_amount by issue_date; a month at the edge "
           f"of the period counts only its days inside it):"]
    for month, currency, total, count in rows[:MAX_SERIES_MONTHS]:
        out.append(f"- {month}: {_money(total, currency)} from {count} invoices.")
    return out


def _top_customers(cursor, tenant_id: str, start: date, end: date, label: str) -> List[str]:
    cursor.execute(
        """
        SELECT customer_name, currency, SUM(total_amount), COUNT(*)
        FROM invoices WHERE tenant_id = %s AND issue_date >= %s AND issue_date < %s
          AND NULLIF(TRIM(customer_name), '') IS NOT NULL
        GROUP BY customer_name, currency ORDER BY 3 DESC LIMIT %s;
        """,
        (tenant_id, start, end, TOP_CUSTOMERS),
    )
    rows = cursor.fetchall()
    if not rows:
        return [f"Customers in {label} (source: invoices.customer_name): the sales records carry no customer "
                f"names, so customers can't be ranked."]
    out = [f"Biggest customers by revenue in {label} (source: invoices.customer_name):"]
    for rank, (name, currency, total, count) in enumerate(rows, 1):
        out.append(f"- #{rank} {name}: {_money(total, currency)} from {count} invoices.")
    return out


def comparison_lines(conn, tenant_id: str, periods: Sequence[dict]) -> List[str]:
    """Revenue of each asked period side by side, with the change from the first to each other one."""
    if len(periods) < 2:
        return []
    with conn.cursor() as cursor:
        totals = [(_totals(cursor, tenant_id, _d(p["start"]), _d(p["end"])), p) for p in periods]
    lines = ["Comparison of the periods asked about (source: invoices.total_amount by issue_date):"]
    base, base_period = totals[0]
    for other, period in totals[1:]:
        for currency in sorted(set(base) | set(other)):
            first = base.get(currency, (0.0, 0))
            second = other.get(currency, (0.0, 0))
            change = _pct(first[0], second[0])
            lines.append(
                f"- {base_period['label']}: {_money(first[0], currency)} ({first[1]} invoices) vs "
                f"{period['label']}: {_money(second[0], currency)} ({second[1]} invoices); difference "
                f"{_money(first[0] - second[0], currency)}" + (f" ({change} for {base_period['label']} against "
                                                                  f"{period['label']})" if change else "") + ".")
    return lines


# --- products: stock and forecasts ------------------------------------------------

def product_status_lines(conn, tenant_id: str, product_ids: Sequence[str], language: str = "en", *,
                         with_stock: bool = True, with_forecast: bool = True, with_sales: bool = True,
                         compare_stock: bool = False) -> List[str]:
    """For each named product: stock, reorder level, last 30 days' units and days of cover (`with_sales`: the
    member may see sales), latest forecast."""
    if not product_ids:
        return []
    lang = "ar" if language == "ar" else "en"
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT p.product_id, localized_text(p.product_name, '{lang}'), inv.stock_quantity, inv.reorder_level,
                   inv.safety_stock, inv.updated_at,
                   (SELECT SUM(ii.quantity) FROM invoice_items ii
                    JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
                    WHERE ii.tenant_id = p.tenant_id AND ii.product_id = p.product_id
                      AND i.issue_date >= CURRENT_DATE - INTERVAL '29 days'),
                   f.expected_demand, f.confidence_range_lower, f.confidence_range_upper, f.forecast_start_date,
                   f.forecast_target_date, f.created_at
            FROM products p
            LEFT JOIN inventory inv ON inv.tenant_id = p.tenant_id AND inv.product_id = p.product_id
            LEFT JOIN LATERAL (
                SELECT expected_demand, confidence_range_lower, confidence_range_upper, forecast_start_date,
                       forecast_target_date, created_at
                FROM demand_forecasts df WHERE df.tenant_id = p.tenant_id AND df.product_id = p.product_id
                ORDER BY df.created_at DESC LIMIT 1
            ) f ON TRUE
            WHERE p.tenant_id = %s AND p.product_id = ANY(%s::uuid[]) AND p.deleted_at IS NULL;
            """,
            (tenant_id, list(product_ids)),
        )
        rows = {str(r[0]): r for r in cursor.fetchall()}
    lines = []
    for product_id in product_ids:
        row = rows.get(product_id)
        if row is None:
            continue
        (_pid, name, stock, reorder, safety, updated, sold_30, expected, low, high, f_start, f_target,
         f_created) = row
        if with_stock:
            header = f"Stock of {name} (source: inventory table"
            if stock is None:
                lines.append(f"{header}): no stock level is recorded for this product.")
            else:
                parts = [f"{format_quantity(stock)} units in stock"]
                if updated is not None:
                    parts[0] += f" (updated {updated.date().isoformat()})"
                if reorder is not None:
                    parts.append(f"reorder level {format_quantity(reorder)}")
                if safety:
                    parts.append(f"safety stock {format_quantity(safety)}")
                if with_sales and sold_30:
                    daily = float(sold_30) / 30
                    parts.append(f"{format_quantity(sold_30)} units sold in the last 30 days, about "
                                 f"{float(stock) / daily:.0f} days of stock at that pace" if daily else "")
                elif with_sales:
                    parts.append("no units sold in the last 30 days")
                if reorder is not None:
                    parts.append("at or below its reorder level" if float(stock) <= float(reorder)
                                 else "above its reorder level")
                lines.append(f"{header}): " + "; ".join(p for p in parts if p) + ".")
        if with_forecast:
            if expected is None:
                lines.append(f"Demand forecast for {name} (source: demand_forecasts): no forecast has been made for "
                             f"this product yet.")
            else:
                window = (f"from {f_start.isoformat()} to {f_target.isoformat()}" if f_start
                          else f"between now and {f_target.isoformat()}")
                spread = (f" (likely between {format_quantity(low)} and {format_quantity(high)})"
                          if low is not None and high is not None else "")
                text = (f"Demand forecast for {name} (source: demand_forecasts, made {f_created.date().isoformat()}): "
                        f"about {format_quantity(expected)} units expected {window}{spread}.")
                if (with_stock or compare_stock) and stock is not None:
                    gap = float(expected) - float(stock)
                    text += (f" Current stock ({format_quantity(stock)}) covers it." if gap <= 0 else
                             f" That is {format_quantity(round(gap))} more than the {format_quantity(stock)} in stock.")
                lines.append(text)
    return lines


def stock_list_lines(conn, tenant_id: str, language: str = "en", with_sales: bool = True) -> List[str]:
    """Every product's stock level, the lowest days of cover first (`with_sales`: the member may see the sales
    pace the days of cover come from; otherwise the lowest stock first)."""
    lang = "ar" if language == "ar" else "en"
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT localized_text(p.product_name, '{lang}'), inv.stock_quantity, inv.reorder_level,
                   (SELECT SUM(ii.quantity) FROM invoice_items ii
                    JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
                    WHERE ii.tenant_id = p.tenant_id AND ii.product_id = p.product_id
                      AND i.issue_date >= CURRENT_DATE - INTERVAL '29 days')
            FROM products p JOIN inventory inv ON inv.tenant_id = p.tenant_id AND inv.product_id = p.product_id
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()
    if not rows:
        return ["Stock levels (source: inventory table): no stock levels are recorded yet."]

    def cover(row):
        stock, sold = float(row[1] or 0), float(row[3] or 0)
        if not with_sales:
            return stock
        return stock / (sold / 30) if sold else float("inf")

    rows.sort(key=cover)
    total = sum(float(r[1] or 0) for r in rows)
    order = ("the shortest days of cover first (source: inventory table; days of cover at the last 30 days' sales "
             "pace)" if with_sales else "the lowest stock first (source: inventory table)")
    lines = [f"Stock levels of all {len(rows)} stocked products, {order}; {format_quantity(total)} units in stock "
             f"in all:"]
    for name, stock, reorder, sold in rows[:STOCK_LIST_LIMIT]:
        days = cover((name, stock, reorder, sold)) if with_sales else None
        lines.append(f"- {name}: {format_quantity(stock)} in stock"
                     + (f", reorder level {format_quantity(reorder)}" if reorder is not None else "")
                     + ("" if days is None else f", about {days:.0f} days of cover" if days != float("inf")
                        else ", no sales in the last 30 days")
                     + ".")
    return lines


# --- customer reviews ----------------------------------------------------------

def review_trend_lines(conn, tenant_id: str, periods: Sequence[dict] = (), product_ids: Sequence[str] = (),
                       months: int = 6) -> List[str]:
    """Positive / neutral / negative counts and average rating: per asked period (with the period before),
    else month by month for the last `months` months - the measure behind "has opinion improved?"."""
    positive = "COALESCE(sr.sentiment_label ILIKE 'pos%%', r.review_rating >= 4)"
    negative = "COALESCE(sr.sentiment_label ILIKE 'neg%%', r.review_rating <= 2)"

    def stats(cursor, start: Optional[date], end: Optional[date]):
        cursor.execute(
            f"""
            SELECT COUNT(*), AVG(r.review_rating), COUNT(*) FILTER (WHERE {positive}),
                   COUNT(*) FILTER (WHERE {negative})
            FROM reviews r
            LEFT JOIN LATERAL (SELECT sentiment_label FROM sentiment_results s
                               WHERE s.tenant_id = r.tenant_id AND s.review_id = r.review_id
                               ORDER BY s.processed_at DESC LIMIT 1) sr ON TRUE
            WHERE r.tenant_id = %s AND r.safety_status = 'SAFE' AND r.subject_type IN ('BUSINESS', 'PRODUCT')
              AND (%s::date IS NULL OR r.review_date >= %s::date) AND (%s::date IS NULL OR r.review_date < %s::date)
              AND (cardinality(%s::uuid[]) = 0 OR r.product_id = ANY(%s::uuid[]));
            """,
            (tenant_id, start, start, end, end, list(product_ids), list(product_ids)),
        )
        return cursor.fetchone()

    def describe(row) -> str:
        count, rating, pos, neg = row
        if not count:
            return "no reviews"
        neutral = count - pos - neg
        text = (f"{count} reviews: {pos} positive ({pos / count * 100:.0f}%), {neutral} neutral, {neg} negative "
                f"({neg / count * 100:.0f}%)")
        return text + (f", average rating {float(rating):.2f}/5" if rating is not None else "")

    lines = []
    with conn.cursor() as cursor:
        if periods:
            lines.append("Customer reviews in the periods asked about (source: reviews and sentiment_results; "
                         "positive/negative from the sentiment analysis, else from the star rating):")
            for period in periods:
                previous = _periods.previous_period(period)
                now = stats(cursor, _d(period["start"]), _d(period["end"]))
                before = stats(cursor, _d(previous["start"]), _d(previous["end"]))
                lines.append(f"- {period['label']} ({_span(period)}): {describe(now)}; {previous['label']}: "
                             f"{describe(before)}.")
            return lines
        cursor.execute(
            f"""
            SELECT to_char(date_trunc('month', r.review_date), 'YYYY-MM'), COUNT(*), AVG(r.review_rating),
                   COUNT(*) FILTER (WHERE {positive}), COUNT(*) FILTER (WHERE {negative})
            FROM reviews r
            LEFT JOIN LATERAL (SELECT sentiment_label FROM sentiment_results s
                               WHERE s.tenant_id = r.tenant_id AND s.review_id = r.review_id
                               ORDER BY s.processed_at DESC LIMIT 1) sr ON TRUE
            WHERE r.tenant_id = %s AND r.safety_status = 'SAFE' AND r.subject_type IN ('BUSINESS', 'PRODUCT')
              AND r.review_date >= date_trunc('month', CURRENT_DATE) - (%s || ' months')::interval
              AND (cardinality(%s::uuid[]) = 0 OR r.product_id = ANY(%s::uuid[]))
            GROUP BY 1 ORDER BY 1;
            """,
            (tenant_id, months - 1, list(product_ids), list(product_ids)),
        )
        rows = cursor.fetchall()
        overall = stats(cursor, None, None)
    if overall[0]:
        lines.append(f"All stored customer reviews (source: reviews and sentiment_results): {describe(overall)}.")
    if rows:
        lines.append(f"Customer reviews month by month, last {months} months (source: reviews and "
                     f"sentiment_results; positive/negative from the sentiment analysis, else the star rating):")
        for month, count, rating, pos, neg in rows:
            lines.append(f"- {month}: {describe((count, rating, pos, neg))}.")
    return lines


# --- the company itself --------------------------------------------------------

def company_profile_lines(conn, tenant_id: str, with_competitors: bool = True) -> List[str]:
    """The company's own profile as entered in Settings, plus the size of its records (the competitor count
    only for members who may see competitors)."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT business_name, business_type, industry_key, city, country_code, primary_currency,
                   business_description, website_url, created_at,
                   (SELECT COUNT(*) FROM products p WHERE p.tenant_id = c.tenant_id AND p.deleted_at IS NULL),
                   (SELECT COUNT(*) FROM tenant_competitors t WHERE t.tenant_id = c.tenant_id AND t.is_tracked)
            FROM companies c WHERE tenant_id = %s;
            """,
            (tenant_id,),
        )
        row = cursor.fetchone()
    if not row:
        return []
    name, business_type, industry, city, country, currency, description, website, created, products, competitors = row
    parts = [f"{name}"]
    if business_type or industry:
        parts.append(f"business type {business_type or industry}")
    if city or country:
        parts.append("located in " + ", ".join(filter(None, [city, country])))
    if currency:
        parts.append(f"currency {currency}")
    if website:
        parts.append(f"website {website}")
    parts.append(f"{products} products in the catalogue")
    if with_competitors:
        parts.append(f"{competitors} tracked competitors")
    lines = ["Company profile (source: the company settings in KEEL): " + "; ".join(parts) + "."]
    if description:
        lines.append(f"Company description (source: the company settings in KEEL): {description.strip()}")
    return lines


def unique(texts: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for text in texts:
        key = " ".join((text or "").lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out
