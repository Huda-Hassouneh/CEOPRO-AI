"""
KEEL - Category Gap Insight Detection (real "what should I add"
signal, cross-checked against the tenant's own catalog).

The real gap this closes: every existing insight (cross_signal.py,
causal_chain.py) only ever looks at a product the tenant ALREADY carries -
none of them can answer "what am I missing" because none of them ever
looks at what a tracked competitor carries that the tenant's own catalog
doesn't. market_observations (populated by the real scraper/social
collectors - see market_repository.py::save_market_record()) already has
a `category` on nearly every real observation; this module is the first
thing in this codebase to actually read that column for anything other
than storage.

Confidence gate, real and explicit (never a guess dressed up as a
finding):
- Only STRATEGIC/RELEVANT-tier tracked competitors count (never
  CANDIDATE - the same tier gate structured_context.py's own competitor-
  name block already applies for "who are my competitors").
- Only safety_status = 'SAFE' observations (a QUARANTINED one was held
  back by the platform's own safety review for a reason - never counted
  as real evidence here).
- A category needs at least MIN_COMPETITOR_MENTIONS DISTINCT competitors
  carrying it, not just repeat observations from one - one competitor
  selling something isn't "the market", it's one shop's own choice.

The playbook note attached to each finding (vertical_playbook.py) is
general industry guidance, not a fact about this tenant - see that
module's own docstring, and SYSTEM_PROMPT's "Two different kinds of
recommendation" paragraph, for why the two must never be blurred together
in how this gets phrased downstream.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set

from src.ai.insights.cross_signal import Insight
from src.ai.insights.vertical_playbook import get_playbook
from src.market_scraper.sector_detection import detect_vertical, load_business_type

# A category only one competitor happens to carry isn't a real market
# signal - could just as easily be that one shop's own idiosyncratic
# choice. Two or more independent competitors carrying it is a much
# stronger, more defensible basis for "worth considering".
MIN_COMPETITOR_MENTIONS = 2

# Internal ranking only (never shown to the user, same convention as
# every other Insight producer in this package) - deliberately below
# cross_signal.py's own top-tier findings (0.9/0.8/0.7), since this is a
# real but lower-certainty signal (a category gap, not a confirmed
# pricing/sentiment/demand problem on a specific product).
CATEGORY_GAP_CONFIDENCE = 0.55

RECENT_OBSERVATION_WINDOW_DAYS = 90


def _load_competitor_category_counts(conn, tenant_id: str) -> Dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_OBSERVATION_WINDOW_DAYS)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT mo.category, COUNT(DISTINCT gc.global_competitor_id)
            FROM market_observations mo
            JOIN competitor_product_mappings cpm
                ON cpm.tenant_id = mo.tenant_id AND cpm.mapping_id = mo.mapping_id
            JOIN tenant_competitors tc
                ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            JOIN data_sources ds ON ds.tenant_id=mo.tenant_id AND ds.source_id=mo.source_id AND ds.is_active AND ds.policy_status='ALLOWED'
            WHERE mo.tenant_id = %(tenant_id)s
              AND tc.tier IN ('STRATEGIC', 'RELEVANT') AND tc.is_tracked = TRUE
              AND mo.safety_status = 'SAFE' AND mo.category IS NOT NULL
              AND cpm.is_active AND NOT cpm.tracking_paused
              AND mo.observed_at <= now() AND mo.observed_at >= %(since)s
            GROUP BY mo.category;
            """,
            {"tenant_id": tenant_id, "since": since},
        )
        return {category.strip(): count for category, count in cursor.fetchall() if category and category.strip()}


def _load_tenant_categories(conn, tenant_id: str) -> Set[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT COALESCE(category->>'en', category->>'ar')
            FROM products WHERE tenant_id = %s AND deleted_at IS NULL;
            """,
            (tenant_id,),
        )
        return {row[0].strip().lower() for row in cursor.fetchall() if row[0] and row[0].strip()}


def _load_tenant_product_names(conn, tenant_id: str) -> List[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(product_name->>'en', product_name->>'ar', product_name::text)
            FROM products WHERE tenant_id = %s AND deleted_at IS NULL;
            """,
            (tenant_id,),
        )
        return [row[0] for row in cursor.fetchall() if row[0]]


def detect_category_gap_insights(conn, tenant_id: str, max_insights: int = 2) -> List[Insight]:
    """
    Returns at most `max_insights` category-gap findings, highest
    competitor-count first - a category several tracked competitors carry
    is a stronger signal than one only two carry. Returns [] (never a
    fabricated finding) when there's no competitor observation data yet,
    or when nothing clears MIN_COMPETITOR_MENTIONS.
    """
    competitor_categories = _load_competitor_category_counts(conn, tenant_id)
    if not competitor_categories:
        return []

    tenant_categories = _load_tenant_categories(conn, tenant_id)
    vertical = detect_vertical(_load_tenant_product_names(conn, tenant_id), load_business_type(conn, tenant_id)).vertical
    playbook = get_playbook(vertical)

    gaps = [
        (category, count) for category, count in competitor_categories.items()
        if count >= MIN_COMPETITOR_MENTIONS and category.lower() not in tenant_categories
    ]
    gaps.sort(key=lambda pair: pair[1], reverse=True)

    insights = []
    for category, competitor_count in gaps[:max_insights]:
        insights.append(Insight(
            message=(
                f"{competitor_count} of your tracked competitors carry products in the "
                f"\"{category}\" category (source: market_observations, last "
                f"{RECENT_OBSERVATION_WINDOW_DAYS} days), but you don't currently have any "
                f"products listed there. {playbook['add_priority_note']}"
            ),
            category="assortment", product_id="", confidence=CATEGORY_GAP_CONFIDENCE,
            rule_id="category_gap:"+category.casefold(),facts={"category":category,"competitor_count":competitor_count},
        ))
    return insights


def detect_category_gap_details(conn, tenant_id: str, max_results: int = 3) -> List[dict]:
    """
    Same real gaps as detect_category_gap_insights() above (reuses the
    exact same two loaders, same MIN_COMPETITOR_MENTIONS gate, same
    ranking), returned as structured fields instead of one pre-composed
    prose Insight.message - for a UI card (dashboard/market-intelligence's
    "Expansion Opportunities") that needs the category name and
    competitor count on their own, not embedded in a sentence. Never a
    second detection rule: any change to what counts as a gap belongs in
    detect_category_gap_insights() above, and both callers pick it up.
    """
    competitor_categories = _load_competitor_category_counts(conn, tenant_id)
    if not competitor_categories:
        return []

    tenant_categories = _load_tenant_categories(conn, tenant_id)
    vertical = detect_vertical(_load_tenant_product_names(conn, tenant_id), load_business_type(conn, tenant_id)).vertical
    playbook = get_playbook(vertical)

    gaps = [
        (category, count) for category, count in competitor_categories.items()
        if count >= MIN_COMPETITOR_MENTIONS and category.lower() not in tenant_categories
    ]
    gaps.sort(key=lambda pair: pair[1], reverse=True)

    return [
        {
            "category": category,
            "competitor_count": competitor_count,
            "note": playbook["add_priority_note"],
            "confidence": CATEGORY_GAP_CONFIDENCE,
        }
        for category, competitor_count in gaps[:max_results]
    ]
