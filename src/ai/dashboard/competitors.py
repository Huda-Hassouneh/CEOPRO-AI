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
"""
from src.ai.pricing.competitor_classification import TIER_RELEVANT, TIER_STRATEGIC


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


def get_competitor_directory(conn, tenant_id: str) -> dict:
    """Returns {"strategic": [...], "relevant": [...]} - the exact two
    groups and fields the frontend needs (see this module's own
    docstring). Ordered alphabetically by name within each group."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.global_competitor_id, gc.competitor_name, gc.website_url,
                   tc.tier, tc.product_match_rate
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE AND tc.tier IN (%s, %s)
            ORDER BY gc.competitor_name ASC;
            """,
            (tenant_id, TIER_STRATEGIC, TIER_RELEVANT),
        )
        rows = cursor.fetchall()

    strategic = []
    relevant = []
    for global_competitor_id, name, website_url, tier, match_rate in rows:
        if tier == TIER_STRATEGIC:
            strategic.append({
                "name": name,
                "tier": tier,
                "website_url": website_url,
                "overlap_pct": round(float(match_rate) * 100, 1),
            })
        else:
            relevant.append({
                "name": name,
                "tier": tier,
                "website_url": website_url,
                "price_comparisons": _load_price_comparisons(conn, tenant_id, str(global_competitor_id)),
            })

    return {"strategic": strategic, "relevant": relevant}
