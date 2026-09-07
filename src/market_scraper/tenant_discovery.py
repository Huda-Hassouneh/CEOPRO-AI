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
  3. direct_search.search_product_across_retailers() - a free, zero-API-
     cost path layered on top, but only contributes candidates for
     verticals that happen to already have a hand-seeded
     RETAILER_DOMAINS_BY_VERTICAL entry (today: electronics_hobbyist,
     seeded during this codebase's own live validation run). An
     optimization on top of #2, never a substitute for it - a tenant in
     any other vertical still gets full coverage from #2 alone.
  4. discovery.evaluate_candidate() / register_tenant_scoped_competitor() -
     unchanged, already fully generic, the real technical/policy decision
     engine and persistence layer.

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

from src.market_scraper.direct_search import RETAILER_DOMAINS_BY_VERTICAL, search_product_across_retailers
from src.market_scraper.discovery import evaluate_candidate, register_tenant_scoped_competitor
from src.market_scraper.sector_detection import detect_vertical, resolve_tenant_geo_scope
from src.market_scraper.web_product_discovery import discover_product_candidates


def _load_active_tenant_products(conn, tenant_id: str) -> List[dict]:
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
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
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
    candidates_per_product: int = 5,
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

    Returns one result dict per registered candidate (register_tenant_
    scoped_competitor()'s own return shape, with product_id/product_name
    added) - every found candidate is registered regardless of its
    resulting policy_status (ALLOWED/RESTRICTED/BLOCKED all get recorded,
    matching register_tenant_scoped_competitor()'s own "record what was
    found" contract), so callers needing "how many are actually
    collectible" filter on result["policy_status"] == "ALLOWED" rather
    than assuming len() of the return value.
    """
    products = _load_active_tenant_products(conn, tenant_id)
    if max_products is not None:
        products = products[:max_products]

    vertical = detect_vertical([p["product_name"] for p in products]).vertical
    seeded_domains = RETAILER_DOMAINS_BY_VERTICAL.get(vertical, [])
    resolved_geo_scope = resolve_tenant_geo_scope(conn, tenant_id, override=geo_scope)

    results = []
    for product in products:
        candidates = list(discover_product_candidates(
            product["product_name"], resolved_geo_scope, max_results=candidates_per_product,
        ))
        if seeded_domains:
            candidates.extend(search_product_across_retailers(
                product["product_name"], seeded_domains, per_domain_limit=2,
            ))
        for candidate in candidates:
            decision = evaluate_candidate(candidate)
            registered = register_tenant_scoped_competitor(
                conn, tenant_id, actor_user_id, decision, product["product_id"],
            )
            results.append({
                **registered,
                "product_id": product["product_id"],
                "product_name": product["product_name"],
            })
    return results
