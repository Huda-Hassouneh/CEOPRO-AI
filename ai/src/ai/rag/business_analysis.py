"""
KEEL - business analysis for the assistant.

Answers the questions an owner actually asks about their own business,
computed here from their own records - never left to the language model's
arithmetic:

- which products are growing or declining (each product's units and
  revenue in the last 30 days vs the 30 days before),
- what to restock (the latest demand forecast vs current stock, and for
  products without a forecast, days of stock left at the last 30 days'
  sales pace; plus the product's own reorder level),
- how each tracked competitor compares (products in common, who is cheaper
  on each, review sentiment) and which one is strongest on that evidence -
  with the rule spelled out, so the answer can explain it.

Each block is labelled with where its numbers come from: the company's own
records, or KEEL's calculations and competitor tracking. Like
orchestrator.py, a block is only built when the question asks for it.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from src.ai.core.money import format_money_text as format_money
from src.ai.core.quantities import format_quantity
from src.ai.dashboard.inventory_recommendations import get_inventory_recommendations
from src.ai.sentiment.data_access import load_aggregate_sentiment_by_competitor
from src.ai.core.business_time import window_start

WINDOW_DAYS = 30
# A product needs this many units in the earlier window before a change is
# called a trend - 2 -> 1 units is noise, not a decline.
MIN_UNITS_FOR_TREND = 5
TREND_THRESHOLD_PCT = 10.0
DAYS_OF_COVER_ALERT = 14

LABEL_COMPANY_DATA = "YOUR_COMPANY_DATA"
LABEL_RADAR = "RADAR_CALCULATION"

_TREND_KEYWORDS = (
    "declin", "dropping", "drop in", "falling", "fell", "slowing", "slow mover", "slow-moving", "selling less",
    "not selling", "worst", "growing", "growth", "trend", "increasing", "rising", "selling more", "improv",
    "best performing", "worst performing", "performing", "momentum", "compared to last month",
    "تراجع", "تتراجع", "انخفاض", "انخفض", "تنخفض", "نزول", "هبوط", "ضعيف", "الأسوأ", "نمو", "تنمو", "تزايد", "زيادة",
    "ارتفاع", "ترتفع", "الأداء", "أداء", "قلت مبيعات", "قلّت",
)
_RESTOCK_KEYWORDS = (
    "restock", "re-stock", "reorder", "re-order", "low stock", "low on stock", "stock level", "in stock",
    "out of stock", "my stock", "my inventory", "inventory level", "run out", "running out", "order more",
    "need to order", "replenish",
    "مخزون", "المخزون", "نفاد", "ينفد", "تنفد", "إعادة تعبئة", "إعادة الطلب", "أطلب", "اطلب", "تخزين", "بضاعة",
)
_COMPETITOR_KEYWORDS = (
    "competitor", "competition", "rival", "strongest", "biggest threat", "main threat", "cheaper than", "compare my price",
    "price comparison", "compared to the market", "market price", "undercut", "overlap",
    "my prices", "prices compare", "price compare", "price gap", "priced", "overpriced", "too expensive", "expensive",
    "أسعاري", "سعري", "تقارن أسعار", "مقارنة سعر", "فرق السعر", "أغلى", "اغلى",
    "منافس", "منافسين", "المنافس", "المنافسة", "أقوى", "اقوى", "أرخص", "ارخص", "مقارنة الأسعار", "أسعار السوق", "سعر السوق",
)


def _asks(question: str, keywords: tuple) -> bool:
    return any(keyword in question for keyword in keywords)


def _name_sql(language: str) -> str:
    # localized_text() (migration 20261008000000): the answer language's name,
    # never an Arabic name in an English answer when another name exists.
    lang = "ar" if language == "ar" else "fr" if language == "fr" else "en"
    return f"localized_text(p.product_name, '{lang}')"


def _pct(new: float, old: float) -> Optional[float]:
    return round((new - old) / old * 100, 1) if old else None


# ---------------------------------------------------------------------------
# Product trends
# ---------------------------------------------------------------------------

def product_trends_block(conn, tenant_id: str, language: str = "en", now: datetime = None) -> str:
    today = now.date() if now is not None else None  # tests pin "now"; otherwise the company's today
    now = now or datetime.now(timezone.utc)
    recent_start = window_start(conn, WINDOW_DAYS, today=today)
    prior_start = window_start(conn, WINDOW_DAYS, periods=2, today=today)
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {_name_sql(language)} AS name, i.currency,
                   COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date >= %(recent)s), 0),
                   COALESCE(SUM(ii.quantity) FILTER (WHERE i.issue_date < %(recent)s), 0),
                   COALESCE(SUM(ii.total_price) FILTER (WHERE i.issue_date >= %(recent)s), 0),
                   COALESCE(SUM(ii.total_price) FILTER (WHERE i.issue_date < %(recent)s), 0)
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
            WHERE ii.tenant_id = %(tenant)s AND i.issue_date >= %(prior)s AND i.issue_date < %(now)s
              AND p.deleted_at IS NULL
            GROUP BY p.product_id, p.product_name, i.currency;
            """,
            {"tenant": tenant_id, "recent": recent_start, "prior": prior_start, "now": now},
        )
        rows = cursor.fetchall()
    if not rows:
        return ""

    declining, growing, stopped = [], [], []
    for name, currency, units_now, units_before, revenue_now, revenue_before in rows:
        units_now, units_before = float(units_now), float(units_before)
        if units_before < MIN_UNITS_FOR_TREND:
            continue
        change = _pct(units_now, units_before)
        entry = (change, name, units_now, units_before, float(revenue_now), float(revenue_before), currency)
        if units_now == 0:
            stopped.append(entry)
        elif change <= -TREND_THRESHOLD_PCT:
            declining.append(entry)
        elif change >= TREND_THRESHOLD_PCT:
            growing.append(entry)
    declining.sort()
    growing.sort(reverse=True)

    def line(entry):
        change, name, units_now, units_before, revenue_now, revenue_before, currency = entry
        return (f"- {name}: {format_quantity(units_now)} units in the last {WINDOW_DAYS} days vs "
                f"{format_quantity(units_before)} the {WINDOW_DAYS} days before ({change:+.0f}%); revenue "
                f"{format_money(revenue_now, currency)} vs {format_money(revenue_before, currency)} {currency}.")

    lines = [
        f"Product sales trends - each product's units sold in the last {WINDOW_DAYS} days compared with the "
        f"{WINDOW_DAYS} days before (source: your own sales records; a change of at least "
        f"{TREND_THRESHOLD_PCT:.0f}% on at least {MIN_UNITS_FOR_TREND} units counts as a trend):"
    ]
    lines.append("Declining:" if declining or stopped else "Declining: none of your products declined by that much.")
    lines += [line(e) for e in stopped[:3]] + [line(e) for e in declining[:6]]
    lines.append("Growing:" if growing else "Growing: none of your products grew by that much.")
    lines += [line(e) for e in growing[:6]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Restock
# ---------------------------------------------------------------------------

def restock_block(conn, tenant_id: str, language: str = "en", now: datetime = None) -> str:
    now = now or datetime.now(timezone.utc)
    forecast = get_inventory_recommendations(conn, tenant_id, limit=50)["recommendations"]
    forecast_names = {row["product_name"] for row in forecast}
    restock = [row for row in forecast if row["action"] == "RESTOCK_NOW"]

    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {_name_sql(language)} AS name, COALESCE(p.product_name->>'en', p.product_name::text) AS en_name,
                   SUM(inv.stock_quantity), MAX(inv.reorder_level),
                   (SELECT COALESCE(SUM(ii.quantity), 0) FROM invoice_items ii
                    JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
                    WHERE ii.tenant_id = p.tenant_id AND ii.product_id = p.product_id AND i.issue_date >= %(since)s)
            FROM products p
            JOIN inventory inv ON inv.tenant_id = p.tenant_id AND inv.product_id = p.product_id
            WHERE p.tenant_id = %(tenant)s AND p.deleted_at IS NULL
            GROUP BY p.tenant_id, p.product_id, p.product_name;
            """,
            {"tenant": tenant_id, "since": window_start(conn, WINDOW_DAYS)},
        )
        stock_rows = cursor.fetchall()
    if not forecast and not stock_rows:
        return ""

    lines = ["Restock check (source: KEEL's 30-day demand forecasts compared with your current stock, and your own "
             "stock levels and last 30 days of sales):"]
    if restock:
        lines.append("Forecast demand is well above current stock for:")
        for row in restock[:8]:
            lines.append(f"- {row['product_name']}: {format_quantity(row['current_stock'])} in stock, about "
                         f"{row['predicted_demand']} expected to sell by {row['forecast_target_date']} - order about "
                         f"{row['suggested_qty']} more.")
    elif forecast:
        lines.append(f"No product's forecast demand is well above its stock ({len(forecast)} products with forecasts checked).")

    at_reorder, low_cover = [], []
    for name, en_name, stock, reorder_level, sold in stock_rows:
        stock, sold = float(stock), float(sold)
        if stock <= float(reorder_level):
            at_reorder.append(f"- {name}: {format_quantity(stock)} in stock, at or below its reorder level of "
                              f"{format_quantity(reorder_level)}.")
        elif sold > 0 and en_name not in forecast_names and name not in forecast_names:
            days_left = stock / (sold / WINDOW_DAYS)
            if days_left <= DAYS_OF_COVER_ALERT:
                low_cover.append((days_left, f"- {name}: {format_quantity(stock)} in stock lasts about "
                                             f"{days_left:.0f} days at the last {WINDOW_DAYS} days' pace "
                                             f"({format_quantity(sold)} sold)."))
    lines.append("At or below the reorder level you set:" if at_reorder else
                 "No product is at or below the reorder level you set.")
    lines += at_reorder[:8]
    if low_cover:
        lines.append(f"Products without a forecast that would run out within {DAYS_OF_COVER_ALERT} days at the recent pace:")
        lines += [text for _days, text in sorted(low_cover)[:6]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Competitors
# ---------------------------------------------------------------------------

def competitor_comparison_block(conn, tenant_id: str, language: str = "en") -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT gc.global_competitor_id, gc.competitor_name, tc.tier,
                   {_name_sql(language)} AS product, p.current_price, p.currency,
                   latest.scraped_price, latest.observed_at
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            LEFT JOIN competitor_product_mappings cpm
                ON cpm.tenant_id = tc.tenant_id AND cpm.global_competitor_id = tc.global_competitor_id AND cpm.is_active
            LEFT JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id AND p.deleted_at IS NULL
            LEFT JOIN LATERAL (
                SELECT cpr.scraped_price, cpr.observed_at FROM competitor_prices cpr
                WHERE cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
                ORDER BY cpr.observed_at DESC LIMIT 1
            ) latest ON TRUE
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()
    if not rows:
        return ""
    sentiment = load_aggregate_sentiment_by_competitor(conn, tenant_id)

    competitors = {}
    for competitor_id, name, tier, product, our_price, currency, their_price, observed_at in rows:
        entry = competitors.setdefault(str(competitor_id), {"name": name, "tier": tier, "products": set(), "prices": []})
        if product:
            entry["products"].add(product)
        if product and their_price is not None and our_price is not None:
            entry["prices"].append((product, float(our_price), float(their_price), currency, observed_at))

    summaries = []
    for competitor_id, entry in competitors.items():
        cheaper = [p for p in entry["prices"] if p[2] < p[1]]
        pricier = [p for p in entry["prices"] if p[2] > p[1]]
        gaps = [_pct(p[2], p[1]) for p in entry["prices"] if p[1]]
        avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else None
        score = sentiment.get(competitor_id, {}).get("sentiment_score")
        summaries.append({**entry, "cheaper": cheaper, "pricier": pricier, "avg_gap": avg_gap, "sentiment": score})

    # Strongest = sells the most of your products for less than you; then the
    # most products in common; then better-reviewed. Stated in the block.
    summaries.sort(key=lambda s: (-len(s["cheaper"]), -len(s["products"]), -(s["sentiment"] or -2)))

    lines = [
        "Competitor comparison (source: KEEL competitor tracking - the products each competitor sells that match "
        "yours and the latest competitor price recorded for each, plus review sentiment where reviews exist). "
        "Ranked strongest first by: how many of your products they sell for less than you, then how many of your "
        "products they also sell, then review sentiment:"
    ]
    for rank, s in enumerate(summaries[:6], start=1):
        parts = [f"{len(s['products'])} of your products in common"]
        if s["prices"]:
            parts.append(f"cheaper than you on {len(s['cheaper'])}, more expensive on {len(s['pricier'])}")
            if s["avg_gap"] is not None:
                parts.append(f"their prices average {s['avg_gap']:+.0f}% vs yours")
        else:
            parts.append("no competitor price recorded yet")
        if s["sentiment"] is not None:
            parts.append(f"review sentiment {'positive' if s['sentiment'] > 0.2 else 'negative' if s['sentiment'] < -0.2 else 'mixed'}")
        lines.append(f"{rank}. {s['name']}: " + "; ".join(parts) + ".")
        # Every price line repeats the competitor's own name, so a price can
        # never be read as belonging to another competitor.
        ordered = sorted(s["cheaper"], key=lambda p: p[2] - p[1])[:4] + sorted(s["pricier"], key=lambda p: p[1] - p[2])[:3]
        for product, ours, theirs, currency, observed_at in ordered:
            relation = "cheaper than you" if theirs < ours else "more expensive than you" if theirs > ours else "same as you"
            lines.append(f"   - {product}: {s['name']} charges {format_money(theirs, currency)} {currency} vs your "
                         f"{format_money(ours, currency)} {currency} ({relation}; recorded {observed_at.date().isoformat()}).")
    if all(not s["prices"] for s in summaries):
        lines.append("No competitor prices have been recorded yet, so prices can't be compared.")
    lines.append("Not available from this data: competitors' sales volumes, market share or advertising spend - "
                 "never estimate those.")
    return "\n".join(lines)


_RESTOCK_TITLE = "Restock check"
_COMPETITOR_TITLE = "Competitor comparison"


def superseded_prefixes(blocks: List[Tuple[str, str]]) -> tuple:
    """orchestrator.py block openings that these blocks replace."""
    prefixes = ()
    if any(text.startswith(_RESTOCK_TITLE) for _label, text in blocks):
        prefixes += ("Products at or below their reorder level", "Inventory (source")
    if any(text.startswith(_COMPETITOR_TITLE) for _label, text in blocks):
        prefixes += ("Tracked competitors", "Competitors (source")
    return prefixes


def build_analysis_blocks(conn, tenant_id: str, question: str, language: str = "en") -> List[Tuple[str, str]]:
    if conn is None:  # no company context, nothing to analyse
        return []
    q = (question or "").lower()
    blocks = []
    if _asks(q, _TREND_KEYWORDS):
        text = product_trends_block(conn, tenant_id, language)
        if text:
            blocks.append((LABEL_COMPANY_DATA, text))
    if _asks(q, _RESTOCK_KEYWORDS):
        text = restock_block(conn, tenant_id, language)
        if text:
            blocks.append((LABEL_RADAR, text))
    if _asks(q, _COMPETITOR_KEYWORDS):
        text = competitor_comparison_block(conn, tenant_id, language)
        if text:
            blocks.append((LABEL_RADAR, text))
    return blocks
