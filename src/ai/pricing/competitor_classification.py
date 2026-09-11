"""
CEOPRO AI - Real-Competitor Classification.

Discovery (market_scraper/discovery.py) records every seller found for a
matched product as a global_competitors/tenant_competitors row - useful as
an audit trail ("log the details it did find"), but not every seller found
that way is actually a competitor:

- A manufacturer/wholesaler selling its own product isn't a retail rival.
- A seller with no presence in the tenant's operating region can't
  realistically be undercutting or outcompeting the tenant there.
- A seller who happens to carry one of the tenant's products isn't
  meaningfully "competing" with the tenant unless a real share of the
  tenant's catalog overlaps with theirs.

classify_competitor() computes an honest product_match_rate (this tenant's
active products that also have an active mapping to this competitor,
divided by this tenant's total active products) and combines it with the
manufacturer/region checks to decide tenant_competitors.is_confirmed_competitor
and is_tracked. Only a confirmed, tracked competitor is ever handed to a
collector (market_scraper/data_access.py::load_scrape_targets() already
filters on tc.is_tracked = TRUE) - this module is what makes that flag mean
something instead of being unconditionally TRUE at insert time.

DEFAULT_MATCH_RATE_THRESHOLD is 0.5 (50%, the exact bar CEOPRO's product
owner specified) but is a parameter, not a constant baked into the query -
different tenants/verticals may reasonably want a stricter or looser bar.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.market_scraper.geo import distance_km_if_known

DEFAULT_MATCH_RATE_THRESHOLD = 0.5

# Breadth classification thresholds - a separate axis from the tier above:
# tier answers "is this a real, trackable competitor at all", scope answers
# "how much of my catalog do they actually compete on". A NICHE_ITEM
# competitor can still be STRATEGIC-tier confirmed (e.g. the one product
# they carry is exactly matched, in-region, not a manufacturer) while only
# ever covering one line item - "real but narrow" is a genuine, distinct
# outcome from "real and broad", not a contradiction.
NICHE_ITEM_MAX_MATCHED_PRODUCTS = 1
# Reuses DEFAULT_MATCH_RATE_THRESHOLD's own value as the BROAD_DOMAIN bar
# by default (both mean "clears half the catalog"), but is its own
# parameter - a tenant could reasonably want a stricter/looser breadth bar
# than the confirmation bar without the two being forced to move together.
DEFAULT_BROAD_DOMAIN_THRESHOLD = DEFAULT_MATCH_RATE_THRESHOLD


TIER_CANDIDATE = "CANDIDATE"
TIER_RELEVANT = "RELEVANT"
TIER_STRATEGIC = "STRATEGIC"

SCOPE_NICHE_ITEM = "NICHE_ITEM"
SCOPE_PARTIAL_OVERLAP = "PARTIAL_OVERLAP"
SCOPE_BROAD_DOMAIN = "BROAD_DOMAIN"


@dataclass(frozen=True)
class ClassificationResult:
    global_competitor_id: str
    product_match_rate: float
    is_manufacturer: bool
    in_operating_region: bool
    is_confirmed_competitor: bool
    tier: str
    reason: str
    competitor_scope: str
    matched_product_count: int
    distance_km: Optional[float]


def _matched_and_total_product_counts(conn, tenant_id: str, global_competitor_id: str) -> tuple:
    """Shared query core for compute_product_match_rate() and
    classify_competitor() - the breadth classification (NICHE_ITEM vs
    BROAD_DOMAIN) needs the real matched-product COUNT, not just the
    ratio compute_product_match_rate() returns, so this is computed once
    and both derive from it instead of running the count query twice."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
        total_products = cursor.fetchone()[0]
        if total_products == 0:
            return 0, 0

        cursor.execute(
            """
            SELECT COUNT(DISTINCT cpm.product_id)
            FROM competitor_product_mappings cpm
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id
            WHERE cpm.tenant_id = %s
              AND cpm.global_competitor_id = %s
              AND cpm.is_active = TRUE
              AND p.deleted_at IS NULL;
            """,
            (tenant_id, global_competitor_id),
        )
        matched_products = cursor.fetchone()[0]

    return matched_products, total_products


def compute_product_match_rate(conn, tenant_id: str, global_competitor_id: str) -> float:
    """
    (this tenant's active products this competitor also has an active
    mapping to) / (this tenant's total active products). 0.0 (not
    undefined/None) when the tenant has zero active products - there is
    nothing to overlap with, so no seller can clear a match-rate bar yet.
    """
    matched_products, total_products = _matched_and_total_product_counts(
        conn, tenant_id, global_competitor_id
    )
    if total_products == 0:
        return 0.0
    return matched_products / total_products


def classify_competitor_scope(
    matched_product_count: int, match_rate: float, broad_domain_threshold: float = DEFAULT_BROAD_DOMAIN_THRESHOLD,
) -> str:
    """
    NICHE_ITEM: this competitor was only ever found selling a single
    product (or none, for a not-yet-mapped row) - "just on a single
    product" from the product owner's own wording. BROAD_DOMAIN: clears
    the breadth threshold on real catalog overlap - "competing across
    most products". Everything between the two is PARTIAL_OVERLAP - a
    real, honest middle ground, never silently rounded to one extreme.
    """
    if matched_product_count <= NICHE_ITEM_MAX_MATCHED_PRODUCTS:
        return SCOPE_NICHE_ITEM
    if match_rate >= broad_domain_threshold:
        return SCOPE_BROAD_DOMAIN
    return SCOPE_PARTIAL_OVERLAP


def _in_operating_region(competitor_country: Optional[str], tenant_country: str, tenant_operating_countries: list) -> bool:
    """
    A competitor with no known country is not excluded - there's no
    evidence it's out of region, only an absence of evidence (same
    honesty convention as discovery.py's robots.txt handling: unknown
    never silently becomes a pass, but here it never silently becomes a
    fail either - it just can't be evaluated, so it's let through and
    left to the match-rate/manufacturer checks).
    """
    if not competitor_country:
        return True
    return competitor_country == tenant_country or competitor_country in (tenant_operating_countries or [])


def classify_competitor(
    conn, tenant_id: str, global_competitor_id: str,
    threshold: float = DEFAULT_MATCH_RATE_THRESHOLD,
    broad_domain_threshold: float = DEFAULT_BROAD_DOMAIN_THRESHOLD,
) -> ClassificationResult:
    """
    Computes and persists the classification for one tenant_competitors
    row. Idempotent - safe to re-run as a tenant's catalog/mappings grow
    (e.g. after each new discovery run or scrape), which is the intended
    usage: a seller found for one product today may cross the match-rate
    bar next week once more of the tenant's catalog is mapped to it.

    Also computes and persists competitor_scope (NICHE_ITEM/PARTIAL_OVERLAP/
    BROAD_DOMAIN - how much of the catalog this competitor covers) and, when
    both sides have known coordinates, distance_km (real great-circle
    distance from companies.latitude/longitude to global_competitors.
    latitude/longitude) - None when either side's location is unknown,
    never a fabricated distance. Neither of these is a new gate: an
    out-of-radius or NICHE_ITEM competitor is still tracked exactly like
    before - ranking/filtering by distance or scope is the caller's choice
    at query time (see data_access.py::list_tenant_competitors_by_proximity),
    not something baked into is_confirmed_competitor here.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0.0 and 1.0")
    if not 0.0 <= broad_domain_threshold <= 1.0:
        raise ValueError("broad_domain_threshold must be between 0.0 and 1.0")

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_manufacturer, country_code, latitude, longitude FROM global_competitors "
            "WHERE global_competitor_id = %s;",
            (global_competitor_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("global_competitor_id not found")
        is_manufacturer, competitor_country, competitor_lat, competitor_lon = row

        cursor.execute(
            "SELECT country_code, operating_countries, latitude, longitude FROM companies WHERE tenant_id = %s;",
            (tenant_id,),
        )
        company_row = cursor.fetchone()
        if not company_row:
            raise ValueError("tenant_id not found")
        tenant_country, tenant_operating_countries, tenant_lat, tenant_lon = company_row

    matched_product_count, total_products = _matched_and_total_product_counts(
        conn, tenant_id, global_competitor_id
    )
    match_rate = 0.0 if total_products == 0 else matched_product_count / total_products
    in_region = _in_operating_region(competitor_country, tenant_country, tenant_operating_countries)
    scope = classify_competitor_scope(matched_product_count, match_rate, broad_domain_threshold)
    distance_km = distance_km_if_known(tenant_lat, tenant_lon, competitor_lat, competitor_lon)

    if is_manufacturer:
        reason = "excluded: manufacturer/wholesaler, not a retail competitor"
        confirmed = False
        tier = TIER_CANDIDATE
    elif not in_region:
        reason = f"excluded: competitor country {competitor_country!r} is outside the tenant's operating region"
        confirmed = False
        tier = TIER_CANDIDATE
    elif match_rate < threshold:
        reason = f"below threshold: {match_rate:.0%} product overlap (needs >= {threshold:.0%})"
        confirmed = False
        # Passed the manufacturer/region checks - a real, in-region retail
        # seller, just not (yet) enough catalog overlap to call "strategic".
        # This is the tier recommended_collector_config() (product_families.py)
        # gates expensive deep-collection (paid comment/review depth) OFF for -
        # a RELEVANT competitor still gets tracked and price-compared, just
        # not the expensive social depth STRATEGIC gets.
        tier = TIER_RELEVANT
    else:
        reason = f"confirmed: {match_rate:.0%} product overlap, in-region, not a manufacturer"
        confirmed = True
        tier = TIER_STRATEGIC

    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE tenant_competitors
            SET product_match_rate = %s, is_confirmed_competitor = %s,
                is_tracked = %s, classified_at = %s, tier = %s,
                competitor_scope = %s, distance_km = %s
            WHERE tenant_id = %s AND global_competitor_id = %s;
            """,
            (
                match_rate, confirmed, confirmed, datetime.now(timezone.utc), tier,
                scope, distance_km, tenant_id, global_competitor_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("tenant_competitors row not found for this tenant/competitor pair")
    conn.commit()

    return ClassificationResult(
        global_competitor_id=str(global_competitor_id),
        product_match_rate=match_rate,
        is_manufacturer=bool(is_manufacturer),
        in_operating_region=in_region,
        is_confirmed_competitor=confirmed,
        tier=tier,
        reason=reason,
        competitor_scope=scope,
        matched_product_count=matched_product_count,
        distance_km=distance_km,
    )
