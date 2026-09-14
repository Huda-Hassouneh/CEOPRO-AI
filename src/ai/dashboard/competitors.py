"""
CEOPRO AI - Dashboard Competitor Directory (presentation layer, not a new
model).

The final backend contract the frontend team is building the competitor
UI against - grouped by tier, since STRATEGIC and RELEVANT competitors
are shown differently on purpose (spec, this session's own product
decision):

- STRATEGIC (product_match_rate >= the classification threshold - see
  pricing/competitor_classification.py::DEFAULT_MATCH_RATE_THRESHOLD):
  name, tier badge, website URL, and the EXACT overlap percentage - the
  number that earned them the badge.
- RELEVANT (a real, in-region, non-manufacturer competitor - see that
  same module's own docstring on why RELEVANT is tracked at all - just
  below the STRATEGIC bar): name, tier badge, website URL, and a
  per-product price comparison list instead of a bare percentage, since
  the exact match rate is less actionable to a shop owner here than
  seeing where prices actually differ.

Both groups are already limited to tc.is_tracked = TRUE (competitor_
classification.py excludes only TIER_CANDIDATE - manufacturer, or out
of region - from tracking at all), so a CANDIDATE never appears here;
there's nothing an ordinary shop owner should do with a competitor this
platform already decided isn't real.

Every row also carries four fields added for the "Your Competitors"
table view (additive - nothing above changes): market_sentiment_label
(Positive/Neutral/Negative, or None with no analyzed reviews for this
competitor yet - reuses sentiment/data_access.py::
load_aggregate_sentiment_by_competitor(), the same N+1-safe, no-side-
effect bulk read structured_summaries.py already relies on, rather than
get_subject_sentiment_summary()'s per-call evidence_records write, which
would be a real, unwanted side effect fired once per competitor on every
dashboard load), price_competitiveness (reuses market_scraper/scoring.py's
existing 1-10 score, same building block price_competitiveness.py's own
headline KPI uses, averaged across this one competitor's own mapped
products - None with no real price observation yet), last_updated
(tenant_competitors.classified_at - the real timestamp
classify_competitor() already stamps every time this competitor is
reclassified, not a new computation), and market_activity (High/Medium/
Low - see competitor_activity.py::get_market_activity_levels()'s own
docstring for exactly what real signal this is built from and why; a
competitor with no price observations in the window defaults to "Low",
matching "no detected change" rather than "unknown").
"""
from typing import Optional

from src.ai.dashboard.competitor_activity import LEVEL_HIGH, LEVEL_LOW, LEVEL_MEDIUM, get_market_activity_levels
from src.ai.pricing.competitor_classification import TIER_RELEVANT, TIER_STRATEGIC
from src.ai.sentiment.data_access import load_aggregate_sentiment_by_competitor
from src.market_scraper.scoring import composite_score, price_competitiveness

# A deliberately coarse numeric stand-in for market_activity's own High/
# Medium/Low label, used ONLY as one of composite_score()'s three 0-100
# inputs below - the real, precise signal stays the label itself
# (untouched, still returned as market_activity). scoring.py's own
# composite_score() already renormalizes across whichever inputs are
# actually available, so a missing price/sentiment/activity signal is
# still handled honestly (see relevance_score below), not padded to zero.
_ACTIVITY_SCORE_100 = {LEVEL_LOW: 15.0, LEVEL_MEDIUM: 50.0, LEVEL_HIGH: 90.0}

# Bar for calling a real price_competitiveness/sentiment reading a
# "strength" or "weakness" bullet - both thresholds intentionally mirror
# the "clearly on one side, not borderline" discipline already used for
# _SENTIMENT_LABEL_THRESHOLD below, so a middling score earns neither
# bullet rather than being forced into one.
_PRICE_STRENGTH_THRESHOLD = 7.0
_PRICE_WEAKNESS_THRESHOLD = 4.0

# Thresholds for turning a continuous -1..1 sentiment_score into a plain
# label for a table column - a shop owner reads "Positive/Neutral/
# Negative" far faster than a raw float, same "translate the number, keep
# the fact" discipline llm_client.py's SYSTEM_PROMPT already applies to
# confidence scores. +-0.1 is a deliberately small dead zone around zero,
# not a claim of statistical significance - just enough to keep a
# genuinely mixed/borderline sentiment from reading as falsely Positive
# or Negative.
_SENTIMENT_LABEL_THRESHOLD = 0.1


def _load_price_comparisons(conn, tenant_id: str, global_competitor_id: str) -> list:
    """Per-product your-price-vs-their-price for one specific competitor,
    same source shape as competitor_pricing.py's own query but scoped to
    a single global_competitor_id instead of averaged across all of
    them - a RELEVANT competitor's card shows where THEY specifically
    differ, not a market-wide average."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS product_name,
                   p.current_price, p.currency, latest.scraped_price
            FROM competitor_product_mappings cpm
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id
            JOIN LATERAL (
                SELECT cpr.scraped_price
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
                ORDER BY cpr.observed_at DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE cpm.tenant_id = %s AND cpm.global_competitor_id = %s
              AND cpm.is_active = TRUE AND p.deleted_at IS NULL
            ORDER BY product_name;
            """,
            (tenant_id, global_competitor_id),
        )
        rows = cursor.fetchall()
    return [
        {
            "product_name": product_name,
            "your_price": float(your_price),
            "their_price": float(their_price),
            "currency": currency,
        }
        for product_name, your_price, currency, their_price in rows
    ]


def _avg_raw_price_competitiveness(price_pairs: list) -> Optional[float]:
    """The same average price_competitiveness().value scoring.py returns -
    on its native ~10-100 scale, BEFORE _price_competitiveness_for_
    competitor() below rescales it to this table's 0-10 display column.
    Kept as its own function so composite_score() (relevance_score) can
    consume the real 0-100-ish number directly, instead of re-deriving it
    from the already-rescaled display value."""
    scores = [
        price_competitiveness(pair["your_price"], pair["their_price"]).value
        for pair in price_pairs
    ]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def _price_competitiveness_for_competitor(price_pairs: list) -> Optional[float]:
    raw = _avg_raw_price_competitiveness(price_pairs)
    if raw is None:
        return None
    return round(raw / 10, 2)  # scoring.py's 0-100 scale -> this table's 0-10 scale


def _relevance_score(raw_price_100: Optional[float], sentiment_score: Optional[float], activity_level: Optional[str]) -> Optional[float]:
    """0-100 composite via scoring.py's existing composite_score()
    (price 45% / sentiment 35% / activity 20%, renormalized across
    whichever of the three are actually available) - the same real
    inputs the table already computes, just combined into the one
    ranking number "Relevance Score" and the Leaderboard's "Composite
    Score" both ask for. None only when none of the three signals exist
    yet for this competitor, never a fabricated default."""
    sentiment_100 = None if sentiment_score is None else (sentiment_score + 1) / 2 * 100
    activity_100 = None if activity_level is None else _ACTIVITY_SCORE_100[activity_level]
    result = composite_score(raw_price_100, sentiment_100, activity_100)
    return result.value


def _strengths_and_weaknesses(price_competitiveness_10: Optional[float], sentiment_label: Optional[str]) -> "tuple[list, list]":
    """Plain-language bullets derived directly from the two real signals
    above that are naturally positive/negative (price_competitiveness,
    sentiment) - market_activity is deliberately excluded here, since a
    competitor changing prices often isn't inherently good or bad for the
    tenant, just active; forcing it into "strength"/"weakness" would be
    exactly the kind of invented framing this platform's own SYSTEM_PROMPT
    already forbids the chatbot from doing."""
    strengths, weaknesses = [], []
    if price_competitiveness_10 is not None:
        if price_competitiveness_10 >= _PRICE_STRENGTH_THRESHOLD:
            strengths.append("Priced competitively against the market")
        elif price_competitiveness_10 <= _PRICE_WEAKNESS_THRESHOLD:
            weaknesses.append("Priced less competitively than the market")
    if sentiment_label == "Positive":
        strengths.append("Positive customer sentiment")
    elif sentiment_label == "Negative":
        weaknesses.append("Negative customer sentiment")
    return strengths, weaknesses


def _summary_line(tier: str, overlap_pct: Optional[float], matched_product_count: int) -> str:
    """One factual sentence built only from fields this table already
    computes - never a researched "who they are" narrative (this
    platform doesn't scrape a competitor's own About page), just what
    the real classification and matching already established about them."""
    if tier == TIER_STRATEGIC:
        return f"Strategic competitor — {overlap_pct:.0f}% product overlap with your catalog."
    plural = "product" if matched_product_count == 1 else "products"
    return f"Relevant competitor — {matched_product_count} of your {plural} matched for price comparison."


def get_competitor_directory(conn, tenant_id: str) -> dict:
    """Returns {"strategic": [...], "relevant": [...]} - the exact two
    groups and fields the frontend needs (see this module's own
    docstring). Ordered alphabetically by name within each group."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.global_competitor_id, gc.competitor_name, gc.website_url,
                   tc.tier, tc.product_match_rate, tc.classified_at
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE AND tc.tier IN (%s, %s)
            ORDER BY gc.competitor_name ASC;
            """,
            (tenant_id, TIER_STRATEGIC, TIER_RELEVANT),
        )
        rows = cursor.fetchall()

    sentiment_by_competitor = load_aggregate_sentiment_by_competitor(conn, tenant_id)
    activity_by_competitor = get_market_activity_levels(conn, tenant_id)

    strategic = []
    relevant = []
    for global_competitor_id, name, website_url, tier, match_rate, classified_at in rows:
        global_competitor_id = str(global_competitor_id)
        price_pairs = _load_price_comparisons(conn, tenant_id, global_competitor_id)

        sentiment_score = sentiment_by_competitor.get(global_competitor_id, {}).get("sentiment_score")
        sentiment_label = None
        if sentiment_score is not None:
            if sentiment_score > _SENTIMENT_LABEL_THRESHOLD:
                sentiment_label = "Positive"
            elif sentiment_score < -_SENTIMENT_LABEL_THRESHOLD:
                sentiment_label = "Negative"
            else:
                sentiment_label = "Neutral"

        price_competitiveness_10 = _price_competitiveness_for_competitor(price_pairs)
        # activity_for_composite stays None with no real observation in the
        # window - distinct from the displayed market_activity field below,
        # which defaults an unobserved competitor to "Low" for the UI
        # ("no detected change"). Feeding that same default into
        # relevance_score would quietly manufacture a non-zero composite
        # score for a competitor with zero real activity signal - exactly
        # the false-precision this platform's own honesty discipline (see
        # cold_start.py, UNKNOWN evidence records) exists to avoid.
        activity_for_composite = activity_by_competitor.get(global_competitor_id)
        market_activity = activity_for_composite or LEVEL_LOW
        strengths, weaknesses = _strengths_and_weaknesses(price_competitiveness_10, sentiment_label)
        overlap_pct = round(float(match_rate) * 100, 1) if tier == TIER_STRATEGIC else None

        common_fields = {
            "name": name,
            "tier": tier,
            "website_url": website_url,
            "market_sentiment_label": sentiment_label,
            "price_competitiveness": price_competitiveness_10,
            "last_updated": classified_at.isoformat() if classified_at else None,
            "market_activity": market_activity,
            "relevance_score": _relevance_score(_avg_raw_price_competitiveness(price_pairs), sentiment_score, activity_for_composite),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "summary_line": _summary_line(tier, overlap_pct, len(price_pairs)),
        }

        if tier == TIER_STRATEGIC:
            strategic.append({**common_fields, "overlap_pct": overlap_pct})
        else:
            relevant.append({**common_fields, "price_comparisons": price_pairs})

    return {"strategic": strategic, "relevant": relevant}
