"""
Per-product market-price coverage: which of the tenant's products have at
least one price, and for those that do not, WHY.

A price is either a COMPETITOR price (a tracked competitor's mapped product,
scraped or entered by hand) or a MARKET REFERENCE price (price_lookup/: a
seller's public page, a public price database or a shopping search, matched to
the product and not wildly off its own price). Either counts as covered;
price_basis says which.

"Every product has a market price" cannot be promised - a product nobody else
sells, or sold only on sites that forbid collection, genuinely has none - but
it can be MEASURED and every gap can carry its cause, so the gap closes the
moment the cause is fixed (review a source, add a price source, add a
competitor) and a product is never silently empty. Manual prices count: they
are written to the same tables as scraped ones.

Gap reasons:
  NO_COMPETITOR_MAPPED  no tracked competitor is matched to this product yet
  TERMS_UNREVIEWED      matched, but every source is waiting for the owner's
                        terms review (source_ids says which to review)
  ROBOTS_DISALLOWED     matched, but every source forbids automated collection
  NO_DATA_COLLECTED     a source is approved but has produced no price yet
"""
from typing import Optional

REASON_NO_MAPPING = "NO_COMPETITOR_MAPPED"
REASON_TERMS = "TERMS_UNREVIEWED"
REASON_ROBOTS = "ROBOTS_DISALLOWED"
REASON_NO_DATA = "NO_DATA_COLLECTED"
REASONS = (REASON_NO_MAPPING, REASON_TERMS, REASON_ROBOTS, REASON_NO_DATA)

_QUERY = """
    SELECT p.product_id,
           COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS product_name,
           p.current_price, p.currency,
           COUNT(DISTINCT m.mapping_id) AS mappings,
           COUNT(DISTINCT cpr.competitor_price_id) AS prices,
           COUNT(DISTINCT m.source_id) FILTER (WHERE ds.policy_status = 'ALLOWED') AS allowed_sources,
           ARRAY_REMOVE(ARRAY_AGG(DISTINCT m.source_id::text) FILTER (WHERE ds.policy_status = 'RESTRICTED'), NULL) AS restricted_sources,
           MAX(cpr.observed_at) AS last_price_at,
           (SELECT COUNT(*) FROM market_price_observations o
             WHERE o.tenant_id = p.tenant_id AND o.product_id = p.product_id AND o.plausible IS NOT FALSE) AS reference_prices,
           l.outcome AS lookup_outcome, l.last_attempt_at AS lookup_at,
           (p.metadata->>'barcode') IS NOT NULL AS has_barcode
    FROM products p
    LEFT JOIN (competitor_product_mappings m
               JOIN tenant_competitors tc ON tc.tenant_id = m.tenant_id
                AND tc.global_competitor_id = m.global_competitor_id AND tc.is_tracked = TRUE)
           ON m.tenant_id = p.tenant_id AND m.product_id = p.product_id AND m.is_active = TRUE
    LEFT JOIN data_sources ds ON ds.tenant_id = m.tenant_id AND ds.source_id = m.source_id
    LEFT JOIN competitor_prices cpr ON cpr.tenant_id = m.tenant_id AND cpr.mapping_id = m.mapping_id
    LEFT JOIN market_price_lookups l ON l.tenant_id = p.tenant_id AND l.product_id = p.product_id
    WHERE p.tenant_id = %s AND p.deleted_at IS NULL
    GROUP BY p.product_id, product_name, p.current_price, p.currency, l.outcome, l.last_attempt_at, has_barcode
    ORDER BY product_name, p.product_id;
"""


def _reason(mappings: int, allowed: int, restricted: list) -> str:
    if not mappings:
        return REASON_NO_MAPPING
    if allowed:
        return REASON_NO_DATA
    if restricted:
        return REASON_TERMS
    return REASON_ROBOTS


def get_barcode_summary(conn, tenant_id: str) -> dict:
    """{"products", "with_barcode", "coverage_pct"}: how many active products carry a barcode.
    A barcode is the exact key for the open price databases, so this is the number the owner
    can move to improve price coverage."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE metadata->>'barcode' IS NOT NULL) "
            "FROM products WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
        total, with_barcode = cursor.fetchone()
    return {
        "products": int(total), "with_barcode": int(with_barcode),
        "coverage_pct": round(with_barcode / total * 100, 1) if total else None,
    }


def get_price_coverage(
    conn, tenant_id: str, include_covered: bool = False, limit: Optional[int] = 100, offset: int = 0,
    missing_barcode: bool = False,
) -> dict:
    """{"summary": {...}, "products": [...]}. The summary always covers EVERY
    product; `products` lists the gaps (plus covered products when
    include_covered) paged by limit/offset. missing_barcode=True instead lists
    every product without a barcode, price gaps first - the owner's worklist for
    entering barcodes (PATCH /products/{id} {"barcode": ...}). Each product says
    has_barcode, and a gap without one carries suggestion "add_barcode"."""
    with conn.cursor() as cursor:
        cursor.execute(_QUERY, (tenant_id,))
        rows = cursor.fetchall()

    by_reason = {reason: 0 for reason in REASONS}
    items = []
    competitor_priced = reference_only = without_barcode = gaps_without_barcode = 0
    for (product_id, name, current_price, currency, mappings, prices, allowed, restricted, last_price_at,
         reference_prices, lookup_outcome, lookup_at, has_barcode) in rows:
        has_price = prices > 0 or reference_prices > 0
        basis = "competitor" if prices > 0 else "market_reference" if reference_prices > 0 else None
        reason = None if has_price else _reason(mappings, allowed, restricted or [])
        if basis == "competitor":
            competitor_priced += 1
        elif basis == "market_reference":
            reference_only += 1
        else:
            by_reason[reason] += 1
        if not has_barcode:
            without_barcode += 1
            if not has_price:
                gaps_without_barcode += 1
        if missing_barcode:
            if has_barcode:
                continue
        elif has_price and not include_covered:
            continue
        items.append({
            "product_id": str(product_id), "product_name": name,
            "your_price": float(current_price) if current_price is not None else None, "currency": currency,
            "has_market_price": has_price, "price_basis": basis,
            "competitor_prices": prices, "reference_prices": reference_prices,
            "last_price_at": last_price_at.isoformat() if last_price_at else None,
            "reason_code": reason, "matched_competitor_sources": mappings,
            "action": "review_source" if reason == REASON_TERMS else None,
            "source_ids": sorted(restricted or []) if reason == REASON_TERMS else [],
            # What the open-market lookup did for this product, if it has run.
            "has_barcode": has_barcode,
            # The one thing the owner can add that makes the open price databases exact.
            "suggestion": "add_barcode" if not has_barcode and not has_price else None,
            "market_lookup": {"outcome": lookup_outcome, "last_attempt_at": lookup_at.isoformat()} if lookup_outcome else None,
        })

    if missing_barcode:
        items.sort(key=lambda item: item["has_market_price"])  # stable: price gaps first, then by name
    total = len(rows)
    covered = competitor_priced + reference_only
    page = items[offset:] if limit is None else items[offset:offset + limit]
    return {
        "summary": {
            "total_products": total, "with_market_price": covered, "without_market_price": total - covered,
            "with_competitor_price": competitor_priced, "with_reference_price_only": reference_only,
            "coverage_pct": round(covered / total * 100, 1) if total else None, "gaps_by_reason": by_reason,
            "products_without_barcode": without_barcode, "gaps_without_barcode": gaps_without_barcode,
        },
        "products": page,
    }
