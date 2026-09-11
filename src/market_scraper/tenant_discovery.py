"""
CEOPRO AI - Tenant-Level, Industry-Agnostic Discovery Orchestration.

The one missing wiring step tying together every already-generic piece in
this package into one real, callable pipeline that behaves the same way
for a tenant selling electronics, coffee, furniture, or anything else this
codebase has never seen a product name from before - none of the pieces
below branch on industry:

  1. sector_detection.detect_vertical() - reads the tenant's OWN product
     catalog; a vertical it doesn't recognize honestly degrades to
     "general_retail" rather than guessing.
  2. web_product_discovery.discover_product_candidates() - one real
     Google Custom Search call per product. This is the actual
     industry-agnostic path: it runs the same way regardless of what
     detect_vertical() returned, including "general_retail".
  3. web_product_discovery.discover_social_profile_candidates() - real
     Custom Search site:instagram.com/site:facebook.com queries per
     product, for a competitor that ONLY exists as a social profile
     (no e-commerce site at all) - structurally invisible to every other
     path here, which all look for a seller's own site.
  4. direct_search.search_product_across_retailers() - a free, zero-API-
     cost path layered on top, but only contributes candidates for
     verticals that happen to already have a hand-seeded
     RETAILER_DOMAINS_BY_VERTICAL entry (today: electronics_hobbyist,
     seeded during this codebase's own live validation run). An
     optimization on top of #2, never a substitute for it - a tenant in
     any other vertical still gets full coverage from #2 alone.
  5. sitemap_discovery.discover_products_via_sitemap() - another free,
     zero-API-cost path for a domain that's robots.txt-allowed but
     publishes no schema.org SearchAction (so #4 finds nothing there) -
     only fires for verticals with a hand-seeded, live-verified
     SITEMAP_DOMAINS_BY_VERTICAL entry, same discipline as #4.
  6. discovery.evaluate_candidate() / register_tenant_scoped_competitor() -
     unchanged, already fully generic, the real technical/policy decision
     engine and persistence layer. website_identity_key (domain, or
     domain+handle for a social profile) is the real dedup key here, not
     competitor name - two paths finding the same seller under two
     different titles land on one row, not two.

Family-keyed by default (product_families.py, Architecture C's real
scaling fix): a catalog with thousands of SKU-level variants ("1 Ohm
resistor, 2 Ohm resistor, ...") is grouped into families and searched
ONCE per family (a real, sales-volume-selected representative SKU), not
once per SKU - the found competitors are then applied to every real SKU
in that family via register_tenant_scoped_competitor() (a real mapping
row per SKU, zero re-searching). This is what makes "adding another
customer" not multiply scraping cost the way SKU count does, the
explicit design requirement agreed earlier this session. Set
group_by_family=False to search every product individually instead.

Nothing here auto-approves collection. register_tenant_scoped_competitor()
only ever sets approval_reference/approved_by when real terms_evidence is
supplied, and a fully automated run never has any - every discovered
candidate lands as ALLOWED-but-still-unapproved or RESTRICTED, exactly
like a source added any other way, and still needs the existing human
approval step (data_access.record_policy_decision's approval fields,
enforced by cli.py's own gate) before any collection actually runs.
Discovery finds and records candidates; it was never the thing deciding
it's safe to scrape them.
"""
from typing import List, Optional
from urllib.parse import urlsplit

from src.market_scraper.company_geo_profile import get_tenant_search_scope
from src.market_scraper.direct_search import RETAILER_DOMAINS_BY_VERTICAL, search_product_across_retailers
from src.market_scraper.discovery import (
    evaluate_candidate, register_domain_level_competitor, register_tenant_scoped_competitor,
)
from src.market_scraper.places_nearby_discovery import discover_nearby_places
from src.market_scraper.product_families import select_family_representatives
from src.market_scraper.sector_detection import (
    VERTICAL_INDUSTRY_LABELS, detect_vertical, resolve_tenant_geo_scope, resolve_tenant_search_radius,
)
from src.market_scraper.sitemap_discovery import SITEMAP_DOMAINS_BY_VERTICAL, discover_products_via_sitemap
from src.market_scraper.web_product_discovery import (
    discover_industry_candidates, discover_product_candidates, discover_social_profile_candidates,
)


def _load_active_tenant_products(conn, tenant_id: str, skip_already_discovered: bool = True) -> List[dict]:
    """
    Returns [{"product_id", "product_name"}] for every active product -
    the same products.product_name JSONB convention load_known_product_
    names() (src/ai/extraction/data_access.py) already established
    (multilingual dict, e.g. {"en": "...", "ar": "..."}; first non-empty
    text variant wins here since discovery only needs one query string
    per product, not every language). Kept local rather than imported
    from the extraction track: that module's own docstring scopes it to
    extraction's read set, and this needs product_id alongside the name,
    which that function doesn't return.

    skip_already_discovered (default True) excludes a product that
    already has at least one competitor_product_mappings row - the real
    mechanism behind "the same daily cron call just makes free
    incremental progress": once today's search_quota.py budget runs out
    partway through a large catalog, whatever wasn't reached yet simply
    stays un-mapped, and tomorrow's identical call skips everything
    already covered and picks up from there, with no separate resume-
    index or queue to maintain. Set False for a deliberate full re-
    discovery pass (a mapped product might still be missing a competitor
    that's shown up since).
    """
    query = "SELECT product_id, product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL"
    if skip_already_discovered:
        query += (
            " AND product_id NOT IN ("
            "SELECT DISTINCT product_id FROM competitor_product_mappings WHERE tenant_id = %s"
            ")"
        )
    with conn.cursor() as cursor:
        cursor.execute(query + ";", (tenant_id, tenant_id) if skip_already_discovered else (tenant_id,))
        rows = cursor.fetchall()
    products = []
    for product_id, product_name in rows:
        if isinstance(product_name, dict):
            text = next((v for v in product_name.values() if isinstance(v, str) and v), None)
        elif isinstance(product_name, str):
            text = product_name
        else:
            text = None
        if text:
            products.append({"product_id": str(product_id), "product_name": text})
    return products


def discover_competitors_for_tenant(
    conn, tenant_id: str, actor_user_id: str,
    geo_scope: Optional[str] = None, max_products: Optional[int] = None,
    candidates_per_product: int = 5, include_social_only: bool = True,
    group_by_family: bool = True, skip_already_discovered: bool = True,
    daily_query_limit: Optional[int] = 100,
) -> List[dict]:
    """
    Runs real discovery for every active product in this tenant's own
    catalog and registers whatever real candidates come back - the actual
    "any company, any industry, out of the box" entry point referenced in
    this module's docstring.

    max_products caps how many catalog products get a discovery pass in
    one call (None = every active product) - useful for a first run on a
    large catalog, or for keeping one call inside the Custom Search
    free tier's 100 queries/day.

    include_social_only additionally runs web_product_discovery.py::
    discover_social_profile_candidates() per search unit - competitors
    that only exist as an Instagram/Facebook profile, no e-commerce site
    at all, which the other two paths structurally cannot find (both only
    ever look for a seller's own site). Doubles this call's Custom Search
    query volume (one extra query per platform per search unit), so it's
    a real, controllable knob against the same 100/day free-tier budget,
    not a free addition - set False to skip it for a large catalog's
    first pass.

    group_by_family (default True) is Architecture C's real cost fix:
    products.product_families.select_family_representatives() groups the
    catalog into families and this function searches ONCE per family (a
    real, sales-volume-selected representative), applying whatever's
    found to every real SKU in that family via register_tenant_scoped_
    competitor() - one real Custom Search query per family, not per SKU,
    with a real competitor_product_mappings row for every SKU regardless.
    Set False to search every product individually instead (the pre-
    Architecture-C behavior, still available since a catalog that's
    already small enough not to need this can skip the extra DB queries
    select_family_representatives() itself does).

    skip_already_discovered (default True) is the real zero-dollar answer
    to "the daily quota isn't enough for the whole catalog in one run":
    a product that already has at least one competitor_product_mappings
    row is excluded before family-grouping even happens, so once search_
    quota.py's daily budget runs out partway through a large catalog, the
    SAME call re-run tomorrow (e.g. via a daily cron) naturally picks up
    only what's still unmapped - no separate resume-index or queue to
    build or maintain. daily_query_limit (default 100, Google's real
    free-tier cap) is passed straight through to web_product_discovery.py
    - see its own docstring for the pacer's full reasoning.

    Returns one result dict per registered candidate (register_tenant_
    scoped_competitor()'s own return shape, with product_id/product_name
    added) - every found candidate is registered for every family member
    regardless of its resulting policy_status (ALLOWED/RESTRICTED/BLOCKED
    all get recorded, matching register_tenant_scoped_competitor()'s own
    "record what was found" contract) - a social-only competitor
    typically lands BLOCKED (Instagram/Facebook's own robots.txt
    disallows most paths for a generic bot - see discover_social_profile_
    candidates()'s docstring), which is correct: it's still recorded as a
    real, tracked competitor, it's just not directly fetchable the way a
    normal product page is. Callers needing "how many are actually
    collectible" filter on result["policy_status"] == "ALLOWED" rather
    than assuming len() of the return value.
    """
    products = _load_active_tenant_products(conn, tenant_id, skip_already_discovered=skip_already_discovered)
    if max_products is not None:
        products = products[:max_products]

    vertical = detect_vertical([p["product_name"] for p in products]).vertical
    seeded_domains = RETAILER_DOMAINS_BY_VERTICAL.get(vertical, [])
    sitemap_domains = SITEMAP_DOMAINS_BY_VERTICAL.get(vertical, [])
    resolved_geo_scope = resolve_tenant_geo_scope(conn, tenant_id, override=geo_scope)

    if group_by_family:
        search_units = select_family_representatives(conn, tenant_id, products)
    else:
        search_units = [{**product, "family_members": [product]} for product in products]

    results = []
    for unit in search_units:
        candidates = list(discover_product_candidates(
            unit["product_name"], resolved_geo_scope, max_results=candidates_per_product, conn=conn,
            daily_query_limit=daily_query_limit,
        ))
        if include_social_only:
            candidates.extend(discover_social_profile_candidates(
                unit["product_name"], conn=conn, daily_query_limit=daily_query_limit,
            ))
        if seeded_domains:
            candidates.extend(search_product_across_retailers(
                unit["product_name"], seeded_domains, per_domain_limit=2,
            ))
        for domain in sitemap_domains:
            candidates.extend(discover_products_via_sitemap(domain, unit["product_name"], limit=2))

        # Evaluated ONCE per candidate (real robots.txt fetch included),
        # then reused for every family member - this is the actual cost
        # saving, not just the search query above.
        decisions = [evaluate_candidate(candidate) for candidate in candidates]
        for member in unit["family_members"]:
            for decision in decisions:
                registered = register_tenant_scoped_competitor(
                    conn, tenant_id, actor_user_id, decision, member["product_id"],
                )
                results.append({
                    **registered,
                    "product_id": member["product_id"],
                    "product_name": member["product_name"],
                })
    return results


def discover_domain_level_competitors_for_tenant(
    conn, tenant_id: str, actor_user_id: str,
    google_places_api_key: Optional[str] = None,
    geo_scope: Optional[str] = None, radius_km: Optional[float] = None,
    max_results: int = 15, daily_query_limit: Optional[int] = 100,
) -> List[dict]:
    """
    The real fix for "the system cannot rely only on exact product
    matches": finds competitors by INDUSTRY/domain, not by matching a
    specific product. discover_competitors_for_tenant() above can only
    ever find a seller already seen carrying something the tenant also
    sells - a same-industry rival with a genuinely different product mix
    (spec example: "a large manufacturing factory is not a direct
    competitor to a local retail shop" is the exclusion case; this
    function's whole point is the inclusion case that product-matching
    alone structurally misses) never shows up through that path at all.

    Two real, combined discovery sources (the "hybrid" approach) run in
    this one call:
    1. **Places nearby-search** (places_nearby_discovery.py) - only runs
       when the tenant has real coordinates on file (company_geo_profile.py)
       AND a Google Places API key is supplied; searches a real radius
       (resolve_tenant_search_radius() - the tenant's own CITY/PROVINCE/
       COUNTRY/CUSTOM preference, see company_geo_profile.py - clamped to
       Google's real 50km Nearby Search cap) around the tenant's own
       location for the tenant's detected industry keyword.
    2. **Industry-keyword Custom Search** (web_product_discovery.py::
       discover_industry_candidates()) - always attempted (needs no
       coordinates, only the tenant's detected vertical + country-level
       geo_scope text, same as product-level discovery already uses);
       the real fallback/complement when the tenant has no coordinates on
       file yet, or as an additional source alongside Places either way.

    Every real candidate from either source is registered via discovery.py
    ::register_domain_level_competitor() - no competitor_product_mappings
    row (there's no specific product to scope one to), but a real,
    classified, potentially-confirmed tenant_competitors row, exactly the
    same downstream shape discover_competitors_for_tenant() produces.

    Nothing here auto-approves collection, same discipline as every other
    discovery path in this module - these are business identities found
    and recorded, not sources cleared for scraping.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
        product_names = []
        for (product_name,) in cursor.fetchall():
            if isinstance(product_name, dict):
                text = next((v for v in product_name.values() if isinstance(v, str) and v), None)
            elif isinstance(product_name, str):
                text = product_name
            else:
                text = None
            if text:
                product_names.append(text)

    vertical = detect_vertical(product_names).vertical
    resolved_geo_scope = resolve_tenant_geo_scope(conn, tenant_id, override=geo_scope)
    scope = get_tenant_search_scope(conn, tenant_id)
    resolved_radius_km = resolve_tenant_search_radius(conn, tenant_id, override_km=radius_km)

    candidates = []

    # resolved_radius_km is None only for an explicit COUNTRY scope choice
    # (resolve_tenant_search_radius()'s own contract) - a radius-bounded
    # Nearby Search is not a meaningful operation for "this tenant's whole
    # country", so Places is correctly skipped there, not fed a fabricated
    # radius; the industry-keyword search below still covers that scope via
    # its own text-based geo_scope, unaffected by this gate.
    if (
        scope["latitude"] is not None and scope["longitude"] is not None
        and google_places_api_key and resolved_radius_km is not None
    ):
        keyword = VERTICAL_INDUSTRY_LABELS.get(vertical, VERTICAL_INDUSTRY_LABELS["general_retail"])
        candidates.extend(discover_nearby_places(
            scope["latitude"], scope["longitude"], keyword,
            radius_km=resolved_radius_km,
            api_key=google_places_api_key, max_results=max_results,
        ))

    candidates.extend(discover_industry_candidates(
        vertical, resolved_geo_scope, max_results=max_results, conn=conn, daily_query_limit=daily_query_limit,
    ))

    active_products = _load_active_tenant_products(conn, tenant_id, skip_already_discovered=False)

    results = []
    for candidate in candidates:
        decision = evaluate_candidate(candidate)
        method = "PLACES_NEARBY" if candidate.latitude is not None else "INDUSTRY_KEYWORD_SEARCH"
        registered = register_domain_level_competitor(
            conn, tenant_id, actor_user_id, candidate, discovery_method=method, industry_sector=vertical,
        )
        result = {**registered, "policy_status": decision.policy_status}

        # "Scrape data from their websites if they have one": a domain-level
        # find has no product mapping yet (register_domain_level_competitor()
        # deliberately creates none - see its own docstring), so it's
        # invisible to load_scrape_targets() (mapping-driven) until one
        # exists. Only worth the crawl effort for a CONFIRMED competitor -
        # same "don't spend real work on an excluded manufacturer/out-of-
        # region find" discipline as recommended_collector_config()'s own
        # STRATEGIC-only gate elsewhere in this codebase.
        if registered["is_confirmed_competitor"] and registered.get("website_url"):
            result["mapped_products"] = map_products_on_domain_competitor_site(
                conn, tenant_id, actor_user_id, registered["website_url"], active_products,
            )
        results.append(result)
    return results


def map_products_on_domain_competitor_site(
    conn, tenant_id: str, actor_user_id: str, website_url: str, products: list,
    group_by_family: bool = True, per_product_limit: int = 3,
) -> list:
    """
    The real fix for "a domain-level competitor is discovered but nothing
    ever scrapes their site": runs BOTH existing, free, zero-API-cost
    product-discovery mechanisms - direct_search.py::
    search_product_across_retailers() (schema.org SearchAction) and
    sitemap_discovery.py::discover_products_via_sitemap() (sitemap.xml) -
    against this ONE known competitor's own domain (both functions are
    domain-agnostic at the call site; the hand-seeded *_BY_VERTICAL dicts
    elsewhere are only an optimization for "which domains to try" when the
    domain isn't already known - irrelevant here, since it IS known) for
    every real product in the tenant's catalog.

    Any real match found registers via the ordinary discovery.py::
    register_tenant_scoped_competitor() path - the SAME function product-
    level discovery already uses. This is what actually closes the loop:
    website_identity_key dedup means this lands on the exact same
    global_competitors row register_domain_level_competitor() already
    created (proven by this session's own test_domain_and_product_level_
    finds_converge_on_the_same_competitor_row), and - unlike the domain-
    level registration - creates real competitor_product_mappings/
    data_sources rows, which is exactly what load_scrape_targets()
    requires to ever hand this competitor to a real collector. A domain-
    level competitor with a real product match here becomes, from that
    point on, indistinguishable from one product-level discovery found
    directly.

    group_by_family (default True) reuses Architecture C's cost fix here
    too - not for API cost (there is none - both mechanisms are free),
    but for politeness: searching once per family instead of once per
    SKU means fewer real HTTP requests against this one competitor's own
    server, not a shared API quota.
    """
    domain = urlsplit(website_url).hostname
    if not domain:
        return []

    if group_by_family:
        search_units = select_family_representatives(conn, tenant_id, products)
    else:
        search_units = [{**product, "family_members": [product]} for product in products]

    results = []
    for unit in search_units:
        candidates = list(search_product_across_retailers(
            unit["product_name"], [domain], per_domain_limit=per_product_limit,
        ))
        candidates.extend(discover_products_via_sitemap(
            domain, unit["product_name"], limit=per_product_limit,
        ))
        if not candidates:
            continue

        decisions = [evaluate_candidate(candidate) for candidate in candidates]
        for member in unit["family_members"]:
            for decision in decisions:
                registered = register_tenant_scoped_competitor(
                    conn, tenant_id, actor_user_id, decision, member["product_id"],
                )
                results.append({
                    **registered, "product_id": member["product_id"], "product_name": member["product_name"],
                })
    return results

