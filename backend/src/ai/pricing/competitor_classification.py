"""
KEEL - Real-Competitor Classification.

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

DEFAULT_MATCH_RATE_THRESHOLD is 0.6 (60%, the product owner's chosen
balanced middle ground for the STRATEGIC bar - raised from an earlier 0.5
- but is a parameter, not a constant baked into the query - different
tenants/verticals may reasonably want a stricter or looser bar.

is_confirmed_competitor/is_tracked mean "not excluded" (passed the
manufacturer/region gates), NOT "cleared the STRATEGIC match-rate bar" -
a real, in-region, non-manufacturer seller is a real competitor worth
tracking and price-comparing the moment it clears those two gates,
whether or not enough of the tenant's catalog overlaps with theirs yet
to call it STRATEGIC. tier is the separate axis that answers "how much
of my catalog do they compete on" (RELEVANT below the bar, STRATEGIC at
or above it) - only TIER_CANDIDATE (manufacturer, out of region, or a
different business category - a donut shop is not a burger restaurant's
competitor) is ever excluded from tracking.

Category relevance (market_scraper/category_taxonomy.py) is also what
decides STRATEGIC for a domain-level find with no product mappings: same
segment earns STRATEGIC, a merely related one RELEVANT. Every result also
carries a 0-100 confidence score + reasons (competitor_confidence.py), which
the competitor directory orders by.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.ai.core import usage
from src.market_scraper.company_target_markets import (
    extract_country_codes, get_tenant_target_markets, has_global_target_market,
)
from src.ai.forecasting.evidence import insert_evidence_record
from src.ai.pricing.competitor_confidence import ConfidenceResult, compute_confidence
from src.market_scraper.category_taxonomy import (
    MIN_COMPETING_SIMILARITY, STRONG_COMPETING_SIMILARITY, best_similarity, categorize, categorize_catalog,
)
from src.market_scraper.geo import distance_km_if_known
from src.market_scraper.sector_detection import TENANT_MANUFACTURER_SELF_DESCRIPTIONS

# Scope levels that carry no distance-ring/country gate at all - a tenant
# who explicitly chose this level said "worldwide," and companies.
# operating_countries/default_search_radius_km stop meaning "the boundary
# of relevance" the moment that choice is made (company_geo_profile.py's
# own SCOPE_LEVEL_GLOBAL contract).
_SCOPE_LEVEL_GLOBAL = "GLOBAL"
# Levels where a real, known distance in km is a meaningful exclusion
# signal - COUNTRY and GLOBAL both mean "no radius filter" by design
# (company_geo_profile.py::set_tenant_search_scope), so distance_km is
# informational only there, never a gate.
_RADIUS_GATED_SCOPE_LEVELS = {"CITY", "PROVINCE", "CUSTOM"}

DEFAULT_MATCH_RATE_THRESHOLD = 0.6

SOURCE_MODULE = "competitor_classification"
MODEL_VERSION = "competitor-classification-v1"
# A new evidence record is written only when the tier changes or the score
# moves by at least this many points - re-scoring an unchanged competitor
# must not flood the (append-only) evidence trail.
EVIDENCE_SCORE_DELTA = 1.0

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
    category_similarity: Optional[float] = None
    confidence_score: Optional[float] = None
    confidence_label: Optional[str] = None
    confidence_reasons: tuple = ()
    confidence_breakdown: tuple = ()
    evidence_id: Optional[str] = None


def _tenant_category_paths(cursor, tenant_id: str, business_type: Optional[str]) -> list:
    """The category paths this tenant operates in, from its own product
    names (every language variant of the JSONB name) plus business_type."""
    cursor.execute("SELECT product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant_id,))
    names = []
    for (product_name,) in cursor.fetchall():
        if isinstance(product_name, dict):
            names.extend(v for v in product_name.values() if isinstance(v, str) and v)
        elif isinstance(product_name, str):
            names.append(product_name)
    return categorize_catalog(names, business_type)


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


# discovery_method values that find a competitor by industry/domain rather
# than by an exact product match - see market_scraper/discovery.py's
# register_domain_level_competitor() and tenant_discovery.py's hybrid
# discovery sources. Kept here (not imported from market_scraper) to avoid
# a circular import - market_scraper/discovery.py already imports FROM
# this module.
DOMAIN_LEVEL_DISCOVERY_METHODS = {"PLACES_NEARBY", "INDUSTRY_KEYWORD_SEARCH"}


def classify_competitor_scope(
    matched_product_count: int, match_rate: float, broad_domain_threshold: float = DEFAULT_BROAD_DOMAIN_THRESHOLD,
    discovery_method: Optional[str] = None,
) -> str:
    """
    NICHE_ITEM: this competitor was only ever found selling a single
    product (or none, for a not-yet-mapped row) - "just on a single
    product" from the product owner's own wording. BROAD_DOMAIN: clears
    the breadth threshold on real catalog overlap - "competing across
    most products". Everything between the two is PARTIAL_OVERLAP - a
    real, honest middle ground, never silently rounded to one extreme.

    A competitor found via a domain-level discovery source (discovery_method
    in DOMAIN_LEVEL_DISCOVERY_METHODS) with zero mapped products yet is the
    one deliberate exception: it's labeled BROAD_DOMAIN, not NICHE_ITEM,
    because it was found BY being a same-industry business, not by carrying
    one specific SKU - mislabeling it "niche" would be backwards. Once real
    competitor_product_mappings rows exist for it (a later product-level
    match), the ordinary matched_product_count/match_rate logic takes back
    over on the next classify_competitor() run, same as any other row.
    """
    if discovery_method in DOMAIN_LEVEL_DISCOVERY_METHODS and matched_product_count == 0:
        return SCOPE_BROAD_DOMAIN
    if matched_product_count <= NICHE_ITEM_MAX_MATCHED_PRODUCTS:
        return SCOPE_NICHE_ITEM
    if match_rate >= broad_domain_threshold:
        return SCOPE_BROAD_DOMAIN
    return SCOPE_PARTIAL_OVERLAP


def _tenant_business_type_signals_manufacturer(business_type: Optional[str]) -> bool:
    """
    Reuses the exact same generic, industry-agnostic vocabulary
    (sector_detection.MANUFACTURER_SIGNAL_WORDS) discovery.py already
    applies to a CANDIDATE's own name/URL - applied here to the TENANT's
    own self-described companies.business_type instead. This is the real
    fix for "a retailer should not automatically get a factory/
    manufacturer unless the user explicitly includes that type": the
    manufacturer exclusion below only ever makes sense for a tenant whose
    own real competitors are NOT manufacturers (the common case - a
    retailer, a service business, a restaurant, a SaaS company...). A
    tenant who typed something like "Manufacturer" or "Wholesale
    Distributor" for their own business_type IS the exception the spec
    describes ("unless the user explicitly includes that type") - their
    real rivals ARE other manufacturers/wholesalers, so the exclusion
    would be backwards for them and is skipped entirely.

    No fixed taxonomy invented: business_type is the tenant's own free-text
    field (already collected at onboarding/settings, src/ai/routers/
    settings.py), never a hardcoded enum - this just tests it against the
    same lexical signal words already proven generic across every
    vertical this codebase has been tested against.
    """
    if not business_type:
        return False
    text = business_type.lower()
    return any(word in text for word in TENANT_MANUFACTURER_SELF_DESCRIPTIONS)


def _in_target_market_scope(
    competitor_country: Optional[str], tenant_country: str, tenant_operating_countries: list,
    search_scope_level: Optional[str], search_radius_km: Optional[float], distance_km: Optional[float],
    tenant_declared_target_markets: Optional[list] = None,
    tenant_has_global_target_market: bool = False,
) -> bool:
    """
    The real fix for "why did a tenant with a specific target market end
    up with competitors from anywhere in the world": country_code/
    operating_countries alone (the previous check) could never actually
    exclude anything, because neither discovery path ever populated
    global_competitors.country_code before discovery.py::
    infer_country_code_from_domain() started doing so - every competitor
    silently fell into the "unknown, let it through" branch below,
    regardless of the tenant's own selected scope. That data gap is fixed
    upstream; this function is what actually USES the real evidence once
    it exists, gated by the tenant's own explicit choice:

    - GLOBAL search scope, OR a declared GLOBAL Target Market
      (company_target_markets.py's own MARKET_TYPE_GLOBAL - a real,
      independent "I want to compete everywhere" declaration, never
      inferred from search_scope_level): always in-scope, no country/
      region/radius exclusion at all. "Must not assume that global
      competitors are relevant just because they sell the same product"
      cuts both ways: it also must not assume they're IRRELEVANT once the
      user asked for global, through either mechanism.
    - A KNOWN competitor country that appears in the tenant's own
      EXPLICITLY declared COUNTRY-type Target Markets (never
      operating_countries, never inferred, never a REGION-type entry -
      see company_target_markets.py's own docstring for why a free-text
      region can't honestly resolve to a country list): always in-scope,
      overriding both the country-mismatch and radius checks below. A
      target market is a real, human-declared commercial intent ("I want
      to compete in this country") that operating_countries/search radius
      were never designed to express - a manufacturer based in one
      country whose declared target market is three others must not have
      its real target-market competitors excluded just for being outside
      where the tenant happens to physically operate or search nearby.
      tenant_declared_target_markets defaults to None/empty (no rows in
      company_target_markets yet) and changes nothing when empty - this is
      a pure addition to the existing gate, never a narrowing of it.
    - Any other scope with a KNOWN competitor country that doesn't match
      the tenant's own country or operating_countries list: excluded. This
      is the actual fix for "a Jordanian retailer should not automatically
      get a Chinese manufacturer as a direct competitor" - a real,
      evidence-based mismatch, not a guess.
    - A radius-gated scope (CITY/PROVINCE/CUSTOM) with a KNOWN distance_km
      beyond the tenant's configured radius: excluded - "if the user
      targets one city/governorate, results outside that geographic scope
      should not be treated as direct competitors," now actually enforced
      rather than merely stored as informational data.
    - Everything else (no known country AND no known distance, or a known
      country/distance that matches): in-scope. Absence of evidence is
      still never treated as evidence of exclusion - same honesty
      convention as discovery.py's robots.txt handling and every other
      "unknown, not guessed" contract in this codebase.
    """
    if search_scope_level == _SCOPE_LEVEL_GLOBAL or tenant_has_global_target_market:
        return True
    if competitor_country and competitor_country in (tenant_declared_target_markets or []):
        return True
    if competitor_country and competitor_country != tenant_country and competitor_country not in (tenant_operating_countries or []):
        return False
    if (
        search_scope_level in _RADIUS_GATED_SCOPE_LEVELS
        and search_radius_km is not None and distance_km is not None
        and distance_km > search_radius_km
    ):
        return False
    return True


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
            "SELECT is_manufacturer, country_code, latitude, longitude, competitor_name, category_path, "
            "place_types, website_url, address, rating FROM global_competitors "
            "WHERE global_competitor_id = %s;",
            (global_competitor_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("global_competitor_id not found")
        (is_manufacturer, competitor_country, competitor_lat, competitor_lon, competitor_name, stored_category_path,
         competitor_place_types, competitor_website, competitor_address, competitor_rating) = row

        cursor.execute(
            "SELECT country_code, operating_countries, latitude, longitude, business_type, "
            "       search_scope_level, default_search_radius_km "
            "FROM companies WHERE tenant_id = %s;",
            (tenant_id,),
        )
        company_row = cursor.fetchone()
        if not company_row:
            raise ValueError("tenant_id not found")
        (
            tenant_country, tenant_operating_countries, tenant_lat, tenant_lon, tenant_business_type,
            search_scope_level, search_radius_km,
        ) = company_row
        tenant_category_paths = _tenant_category_paths(cursor, tenant_id, tenant_business_type)

        cursor.execute(
            "SELECT discovery_method FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, global_competitor_id),
        )
        discovery_row = cursor.fetchone()
        if discovery_row is None:
            raise ValueError("tenant_competitors row not found for this tenant/competitor pair")
        discovery_method = discovery_row[0]

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tier, confidence_score, evidence_id FROM tenant_competitors "
            "WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, global_competitor_id),
        )
        previous_tier, previous_score, previous_evidence_id = cursor.fetchone()

    matched_product_count, total_products = _matched_and_total_product_counts(
        conn, tenant_id, global_competitor_id
    )
    match_rate = 0.0 if total_products == 0 else matched_product_count / total_products
    scope = classify_competitor_scope(matched_product_count, match_rate, broad_domain_threshold, discovery_method)
    distance_km = distance_km_if_known(tenant_lat, tenant_lon, competitor_lat, competitor_lon)
    # Explicit commercial Target Markets (company_target_markets.py) - a
    # real, human-declared "I want to compete here" list, never inferred
    # from operating_countries/country_code/business_type/products, kept
    # deliberately separate from both. A competitor whose country is on
    # the declared COUNTRY list, or ANY competitor at all when GLOBAL is
    # declared, is never excluded by the operating-region/radius gate
    # below, on top of (not instead of) the existing checks. REGION-type
    # entries are intentionally excluded here (discovery-bias evidence
    # only - see company_target_markets.py's own docstring).
    tenant_target_markets = get_tenant_target_markets(conn, tenant_id)
    tenant_target_market_countries = extract_country_codes(tenant_target_markets)
    tenant_has_global_target_market = has_global_target_market(tenant_target_markets)
    in_region = _in_target_market_scope(
        competitor_country, tenant_country, tenant_operating_countries,
        search_scope_level, search_radius_km, distance_km,
        tenant_declared_target_markets=tenant_target_market_countries,
        tenant_has_global_target_market=tenant_has_global_target_market,
    )
    in_declared_target_market = (
        tenant_has_global_target_market
        or (bool(competitor_country) and competitor_country in tenant_target_market_countries)
    )
    is_domain_level_find = discovery_method in DOMAIN_LEVEL_DISCOVERY_METHODS and matched_product_count == 0
    # See _tenant_business_type_signals_manufacturer()'s own docstring:
    # the manufacturer exclusion below only applies to a tenant whose own
    # business genuinely competes with retailers/services, not with other
    # manufacturers - skipped entirely for a tenant that IS one.
    tenant_is_manufacturer_type = _tenant_business_type_signals_manufacturer(tenant_business_type)
    # Only ever says "not a manufacturer" when that's actually true - a
    # manufacturer-type tenant can reach the confirmed branches below WITH
    # is_manufacturer=True (the exclusion was skipped for them), and the
    # reason text must not silently misstate that.
    manufacturer_clause = "" if is_manufacturer else ", not a manufacturer"

    # Only appended when it's actually WHY the competitor is in-scope (see
    # _in_target_market_scope()'s own docstring) - never claimed for a
    # competitor that would already be in-scope via operating_countries/
    # radius alone, so this stays an honest, specific signal.
    target_market_clause = ", within a declared target market" if in_declared_target_market else ""

    # Category relevance: the missing check that let a donut shop be listed
    # as a burger restaurant's competitor. Uses the stored category when a
    # discovery source already derived one, else categorizes the competitor
    # now from its name/Places types. None on either side = unknown, which
    # is never treated as a mismatch.
    competitor_category = tuple(stored_category_path) if stored_category_path else None
    if competitor_category is None:
        categorization = categorize(competitor_name, competitor_place_types)
        competitor_category = categorization.path if categorization else None
    category_similarity = best_similarity(tenant_category_paths, competitor_category)
    category_label = " > ".join(p.replace("_", " ") for p in competitor_category) if competitor_category else None
    # A manually added competitor (discovery_method NULL) is the owner's own
    # call - never second-guessed by category. Strong product evidence
    # (overlap at/above the STRATEGIC bar) also outranks a category guess.
    different_category = (
        category_similarity is not None
        and category_similarity < MIN_COMPETING_SIMILARITY
        and discovery_method is not None
        and match_rate < threshold
    )

    if is_manufacturer and not tenant_is_manufacturer_type:
        reason = "excluded: manufacturer/wholesaler, not a retail competitor"
        tier = TIER_CANDIDATE
    elif not in_region:
        if competitor_country and competitor_country != tenant_country and competitor_country not in (tenant_operating_countries or []):
            reason = (
                f"excluded: competitor is based in {competitor_country!r}, outside the tenant's "
                f"operating/search scope ({tenant_country!r} / {tenant_operating_countries!r}) "
                f"and not one of its declared target markets"
            )
        else:
            reason = (
                f"excluded: {distance_km:.0f}km away, outside the tenant's configured "
                f"{search_radius_km:.0f}km {search_scope_level} search radius"
            )
        tier = TIER_CANDIDATE
    elif different_category:
        reason = (
            f"excluded: different business category ({category_label}) - does not compete with this tenant's "
            f"{' / '.join(' > '.join(p) for p in tenant_category_paths)}"
        )
        tier = TIER_CANDIDATE
    elif is_domain_level_find:
        # A domain-level find (Places nearby-search / industry-keyword
        # search) has no product mappings to measure overlap against, so
        # category closeness is its evidence instead: same segment
        # (burger vs. pizza) earns STRATEGIC; only broadly related, or a
        # category we could not determine, is RELEVANT - found nearby is
        # not by itself proof of competing. Once real product mappings
        # appear for this competitor, a later run falls through to the
        # ordinary match-rate branches below instead.
        if category_similarity is not None and category_similarity >= STRONG_COMPETING_SIMILARITY:
            reason = (
                f"confirmed (STRATEGIC): same-segment category ({category_label}), in operating/search scope"
                f"{manufacturer_clause}{target_market_clause} (found via {discovery_method})"
            )
            tier = TIER_STRATEGIC
        elif category_similarity is not None:
            reason = f"tracked (RELEVANT): broadly related category ({category_label}) (found via {discovery_method})"
            tier = TIER_RELEVANT
        else:
            reason = (
                f"tracked (RELEVANT): category could not be verified, in operating/search scope"
                f"{manufacturer_clause}{target_market_clause} (found via {discovery_method})"
            )
            tier = TIER_RELEVANT
    elif match_rate < threshold:
        # Passed the manufacturer/region/category checks - a real,
        # in-scope retail seller, just not (yet) enough catalog overlap to
        # call "strategic". Still tracked and price-compared (tier answers
        # "how much of my catalog do they cover", not "is this a real
        # competitor at all"). This is the tier recommended_collector_config()
        # (product_families.py) gates expensive deep-collection OFF for.
        reason = (
            f"tracked (RELEVANT): {match_rate:.0%} product overlap - below the {threshold:.0%} "
            f"STRATEGIC bar, but a real, in-scope competitor{manufacturer_clause}{target_market_clause}"
        )
        tier = TIER_RELEVANT
    else:
        reason = (
            f"confirmed (STRATEGIC): {match_rate:.0%} product overlap, "
            f"in operating/search scope{manufacturer_clause}{target_market_clause}"
        )
        tier = TIER_STRATEGIC

    confidence = compute_confidence(
        category_similarity=category_similarity,
        product_match_rate=match_rate,
        matched_product_count=matched_product_count,
        distance_km=distance_km,
        strategic_match_rate=threshold,
        has_website=bool(competitor_website),
        has_address=bool(competitor_address),
        has_rating=competitor_rating is not None,
        category_label=category_label,
    )

    # is_confirmed_competitor/is_tracked = "not excluded" (see this
    # function's own docstring) - true for every tier except CANDIDATE,
    # regardless of which match-rate branch above produced it.
    confirmed = tier != TIER_CANDIDATE
    # Tracking also respects the plan's competitor cap: one already tracked
    # stays tracked while confirmed; a newly confirmed one is tracked only if
    # the cap has room, otherwise it stays a suggestion the owner can track.
    room = usage.capacity_left(conn, tenant_id, usage.TRACKED_COMPETITORS) if confirmed else 0
    may_track = room is None or room > 0

    # Spec S22: confidence is not implemented independently - the assessment
    # is recorded in the shared evidence_records trail. UNKNOWN when there is
    # no category evidence and no product overlap to judge by; otherwise a
    # FACT derived from observed data by transparent rules. Written only on a
    # real change (see EVIDENCE_SCORE_DELTA).
    evidence_id = previous_evidence_id
    changed = (
        previous_evidence_id is None
        or previous_tier != tier
        or previous_score is None
        or abs(float(previous_score) - confidence.score) >= EVIDENCE_SCORE_DELTA
    )
    if changed:
        evidence_id = insert_evidence_record(
            conn, tenant_id,
            "UNKNOWN" if category_similarity is None and matched_product_count == 0 else "FACT",
            SOURCE_MODULE,
            {"global_competitor_id": str(global_competitor_id), "weights": confidence.weights},
            round(confidence.score / 100, 2),
            f"{tier}: {reason}. Confidence {confidence.score:.0f}/100 ({confidence.label}): "
            + "; ".join(confidence.reasons) + ".",
            MODEL_VERSION,
            tenant_country,
        )

    with conn.cursor() as cursor:
        if stored_category_path is None and competitor_category is not None:
            # Persist a category derived just now so the directory can show
            # it and later runs skip re-deriving (backfills pre-existing rows).
            cursor.execute(
                "UPDATE global_competitors SET category_path = %s WHERE global_competitor_id = %s AND category_path IS NULL;",
                (list(competitor_category), global_competitor_id),
            )
        cursor.execute(
            """
            UPDATE tenant_competitors
            SET product_match_rate = %s, is_confirmed_competitor = %s,
                is_tracked = CASE WHEN NOT %s THEN FALSE WHEN tenant_competitors.is_tracked THEN TRUE ELSE %s END,
                classified_at = %s, tier = %s,
                competitor_scope = %s, distance_km = %s,
                category_similarity = %s, confidence_score = %s, confidence_label = %s,
                confidence_reasons = %s, classification_reason = %s,
                confidence_breakdown = %s, evidence_id = %s
            WHERE tenant_id = %s AND global_competitor_id = %s;
            """,
            (
                match_rate, confirmed, confirmed, may_track, datetime.now(timezone.utc), tier,
                scope, distance_km, category_similarity, confidence.score, confidence.label,
                json.dumps(confidence.reasons), reason, json.dumps(confidence.breakdown), evidence_id,
                tenant_id, global_competitor_id,
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
        category_similarity=category_similarity,
        confidence_score=confidence.score,
        confidence_label=confidence.label,
        confidence_reasons=tuple(confidence.reasons),
        confidence_breakdown=tuple(confidence.breakdown),
        evidence_id=str(evidence_id) if evidence_id else None,
    )


def reclassify_all_for_tenant(conn, tenant_id: str, threshold: float = DEFAULT_MATCH_RATE_THRESHOLD) -> dict:
    """Re-runs classify_competitor() over every competitor this tenant has,
    including ones previously tracked - the way rows classified before the
    category rules existed (a donut shop under a burger restaurant) get
    re-scored, demoted to CANDIDATE, and given a confidence score. Safe to
    re-run. Returns a count per resulting tier plus how many were demoted."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT global_competitor_id, tier FROM tenant_competitors WHERE tenant_id = %s;", (tenant_id,),
        )
        rows = [(str(cid), old_tier) for cid, old_tier in cursor.fetchall()]

    counts = {TIER_STRATEGIC: 0, TIER_RELEVANT: 0, TIER_CANDIDATE: 0}
    demoted = 0
    for competitor_id, old_tier in rows:
        result = classify_competitor(conn, tenant_id, competitor_id, threshold=threshold)
        counts[result.tier] += 1
        if result.tier == TIER_CANDIDATE and old_tier in (TIER_STRATEGIC, TIER_RELEVANT):
            demoted += 1
    return {"reclassified": len(rows), "by_tier": counts, "demoted_to_candidate": demoted}
