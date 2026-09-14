"""
CEOPRO AI - Dashboard Market Overview (presentation layer, not a new
model, no new tables).

Three small, honest aggregates for the Industry Trends / Market
Intelligence Overview pages, each built entirely from real signals this
platform already computes elsewhere - no new data collection, no
schema change:

- price_trend: reuses competitor_activity.py::get_recent_competitor_price_
  changes() (the same real price-change detection "Recent Competitor
  Changes" already relies on) and just counts increases vs. decreases
  across ALL of them instead of listing the individual rows. This is
  deliberately NOT a "weighted index vs. a year-over-year benchmark" -
  nothing in this platform computes that, and a real index needs a real
  market-wide basket definition this platform doesn't have. It IS a real
  directional signal: of the price changes we actually detected recently,
  are more of them up or down.

- sentiment: reuses sentiment/data_access.py::load_aggregate_sentiment_
  by_competitor() (the same per-competitor sentiment competitors.py's
  own table already shows) and buckets the tenant's whole competitor set
  into a plain Bullish/Neutral/Bearish label from the real % with
  Positive sentiment - not a new sentiment model, just a second view of
  numbers already computed.

- category_activity: reuses competitor_activity.py::get_market_activity_
  levels() (the same real High/Medium/Low level already shown per
  competitor) and rolls it up by the tenant's own product category (a
  real column on `products`), taking the highest level seen among
  competitors matched to that category - never a new activity signal,
  just a different grouping of the one that already exists.

None of the three claims to be a full statistical model (no seasonal
decomposition, no weighted market-wide index, no external market-size
denominator) - see this module's own field-level docstrings below for
exactly what's real vs. deliberately not attempted.
"""
from typing import Optional

from src.ai.dashboard.competitor_activity import (
    LEVEL_HIGH, LEVEL_LOW, LEVEL_MEDIUM, get_market_activity_levels, get_recent_competitor_price_changes,
)
from src.ai.sentiment.data_access import load_aggregate_sentiment_by_competitor

# How large a real, tracked-sample the recent-price-change count needs to
# be before "more up than down" is even worth labeling - one lone change
# either way is noise, not a market direction.
PRICE_TREND_MIN_CHANGES = 2

# % of tracked competitors with Positive sentiment above/below which the
# whole set reads as Bullish/Bearish - a deliberate, documented judgment
# call (same discipline as competitor_activity.py's own MARKET_ACTIVITY_*
# thresholds), not a discovered constant.
BULLISH_THRESHOLD_PCT = 60.0
BEARISH_THRESHOLD_PCT = 30.0

_SENTIMENT_LABEL_THRESHOLD = 0.1
_ACTIVITY_SEVERITY = {LEVEL_LOW: 0, LEVEL_MEDIUM: 1, LEVEL_HIGH: 2}


def _price_trend(conn, tenant_id: str) -> dict:
    changes = get_recent_competitor_price_changes(conn, tenant_id, limit=500)
    increases = sum(1 for c in changes if c["direction"] == "increase")
    decreases = sum(1 for c in changes if c["direction"] == "decrease")
    total = increases + decreases
    if total < PRICE_TREND_MIN_CHANGES:
        return {"direction": None, "increases": increases, "decreases": decreases}
    if increases == decreases:
        direction = "Stable"
    else:
        direction = "Up" if increases > decreases else "Down"
    return {"direction": direction, "increases": increases, "decreases": decreases}


def _sentiment_overview(conn, tenant_id: str) -> dict:
    by_competitor = load_aggregate_sentiment_by_competitor(conn, tenant_id)
    scores = [row["sentiment_score"] for row in by_competitor.values() if row.get("sentiment_score") is not None]
    if not scores:
        return {"label": None, "positive_pct": None, "competitors_with_sentiment": 0}

    positive_count = sum(1 for s in scores if s > _SENTIMENT_LABEL_THRESHOLD)
    positive_pct = round(positive_count / len(scores) * 100, 1)

    if positive_pct >= BULLISH_THRESHOLD_PCT:
        label = "Bullish"
    elif positive_pct <= BEARISH_THRESHOLD_PCT:
        label = "Bearish"
    else:
        label = "Neutral"

    return {"label": label, "positive_pct": positive_pct, "competitors_with_sentiment": len(scores)}


def _category_activity(conn, tenant_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT COALESCE(p.category->>'en', p.category->>'ar') AS category,
                   cpm.global_competitor_id
            FROM competitor_product_mappings cpm
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id
            WHERE cpm.tenant_id = %s AND cpm.is_active = TRUE AND p.deleted_at IS NULL
              AND p.category IS NOT NULL;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    activity_by_competitor = get_market_activity_levels(conn, tenant_id)

    highest_level_by_category: dict = {}
    for category, global_competitor_id in rows:
        if category is None:
            continue
        level = activity_by_competitor.get(str(global_competitor_id))
        if level is None:
            continue
        current = highest_level_by_category.get(category)
        if current is None or _ACTIVITY_SEVERITY[level] > _ACTIVITY_SEVERITY[current]:
            highest_level_by_category[category] = level

    return highest_level_by_category


def get_market_overview(conn, tenant_id: str) -> dict:
    return {
        "price_trend": _price_trend(conn, tenant_id),
        "sentiment": _sentiment_overview(conn, tenant_id),
        "category_activity": _category_activity(conn, tenant_id),
    }
