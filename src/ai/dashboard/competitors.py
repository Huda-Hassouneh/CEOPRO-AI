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

Every row also carries three fields added for the "Your Competitors"
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
products - None with no real price observation yet), and last_updated
(tenant_competitors.classified_at - the real timestamp
classify_competitor() already stamps every time this competitor is
reclassified, not a new computation).
"""
from src.ai.pricing.competitor_classification import TIER_RELEVANT, TIER_STRATEGIC
from src.ai.sentiment.data_access import load_aggregate_sentiment_by_competitor
from src.market_scraper.scoring import price_competitiveness

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


def _price_competitiveness_for_competitor(price_pairs: list):
    scores = [
        price_competitiveness(pair["your_price"], pair["their_price"]).value
        for pair in price_pairs
    ]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores) / 10, 2)  # scoring.py's 0-100 scale -> this table's 0-10 scale


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

        common_fields = {
            "name": name,
            "tier": tier,
            "website_url": website_url,
            "market_sentiment_label": sentiment_label,
            "price_competitiveness": _price_competitiveness_for_competitor(price_pairs),
            "last_updated": classified_at.isoformat() if classified_at else None,
        }

        if tier == TIER_STRATEGIC:
            strategic.append({**common_fields, "overlap_pct": round(float(match_rate) * 100, 1)})
        else:
            relevant.append({**common_fields, "price_comparisons": price_pairs})

    return {"strategic": strategic, "relevant": relevant}
