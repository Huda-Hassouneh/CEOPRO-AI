"""
The competitive landscape for the Competitors screen, at two levels:

- market-wide competitors: compete with the business as a whole (another
  grocery store for a grocer);
- product-level competitors: compete on specific products (a coffee roaster
  for a grocer's Arabic coffee).

The level is what the owner chose when adding the competitor
(tenant_competitors.competition_level); when it was never stated, it is
derived: found by an industry or nearby-business search, or overlapping at
least half the catalog -> market-wide; otherwise product-level when linked to
products, market-wide when not linked to any.

Also returns, per product, how many competitors price it and the cheapest
one - the coverage view that shows where competitor intelligence is missing.
"""

from datetime import datetime, timedelta, timezone

MARKET = "MARKET"
PRODUCT = "PRODUCT"
DOMAIN_DISCOVERY = ("PLACES_NEARBY", "INDUSTRY_KEYWORD_SEARCH", "MAP_LISTING", "WEB_SEARCH", "DIRECTORY")
MARKET_OVERLAP_SHARE = 0.5
# Same threshold as the Command Center's price opportunities.
ABOVE_MARKET_PCT = 5.0


def derive_level(stated, discovery_method, linked_products: int, catalog_size: int) -> str:
    if stated in (MARKET, PRODUCT):
        return stated
    if discovery_method in DOMAIN_DISCOVERY:
        return MARKET
    if catalog_size and linked_products / catalog_size >= MARKET_OVERLAP_SHARE:
        return MARKET
    return PRODUCT if linked_products else MARKET


def _pct(new, old):
    return round((new - old) / old * 100, 1) if old else None


def build_landscape(conn, tenant_id: str) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant_id,))
        catalog_size = cursor.fetchone()[0]

        cursor.execute(
            """
            WITH latest AS (
                SELECT DISTINCT ON (cp.mapping_id) cp.mapping_id, cp.scraped_price, cp.currency, cp.observed_at
                FROM competitor_prices cp WHERE cp.tenant_id = %(t)s
                ORDER BY cp.mapping_id, cp.observed_at DESC
            ), changes AS (
                SELECT cpm.global_competitor_id, COUNT(*) AS n
                FROM competitor_prices cp
                JOIN competitor_product_mappings cpm ON cpm.tenant_id = cp.tenant_id AND cpm.mapping_id = cp.mapping_id
                WHERE cp.tenant_id = %(t)s AND cp.observed_at >= %(since)s
                GROUP BY 1
            )
            SELECT gc.global_competitor_id, gc.competitor_name, gc.website_url, tc.tier, tc.competition_level,
                   tc.discovery_method, tc.added_at, tc.distance_km,
                   cpm.product_id, l.scraped_price, l.currency, l.observed_at, p.current_price, p.currency,
                   COALESCE(ch.n, 0)
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            LEFT JOIN competitor_product_mappings cpm
                ON cpm.tenant_id = tc.tenant_id AND cpm.global_competitor_id = tc.global_competitor_id AND cpm.is_active
            LEFT JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id AND p.deleted_at IS NULL
            LEFT JOIN latest l ON l.mapping_id = cpm.mapping_id
            LEFT JOIN changes ch ON ch.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %(t)s AND tc.is_tracked;
            """,
            {"t": tenant_id, "since": since},
        )
        rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT p.product_id, localized_text(p.product_name), localized_text(p.category), p.current_price, p.currency
            FROM products p WHERE p.tenant_id = %s AND p.deleted_at IS NULL
            ORDER BY localized_text(p.product_name);
            """,
            (tenant_id,),
        )
        products = {str(pid): {"product_id": str(pid), "name": name, "category": category, "your_price": float(price),
                               "currency": currency, "competitors": []}
                    for pid, name, category, price, currency in cursor.fetchall()}

    competitors = {}
    for (cid, name, website, tier, stated, discovery, added_at, distance, product_id, price, currency, observed,
         own_price, own_currency, changes_30) in rows:
        entry = competitors.setdefault(str(cid), {
            "competitor_id": str(cid), "name": name, "website_url": website, "tier": tier,
            "stated_level": stated, "discovery_method": discovery,
            "added_at": added_at.isoformat() if added_at else None, "distance_km": distance,
            "products_linked": 0, "products_priced": 0, "cheaper_on": 0, "pricier_on": 0, "gaps": [],
            "last_price_at": None, "price_changes_30d": int(changes_30),
        })
        if product_id is None or own_price is None:
            continue
        entry["products_linked"] += 1
        if price is None:
            continue
        price = float(price)
        entry["products_priced"] += 1
        if observed and (entry["last_price_at"] is None or observed.isoformat() > entry["last_price_at"]):
            entry["last_price_at"] = observed.isoformat()
        if currency == own_currency:
            gap = _pct(price, float(own_price))
            entry["gaps"].append(gap)
            if price < float(own_price):
                entry["cheaper_on"] += 1
            elif price > float(own_price):
                entry["pricier_on"] += 1
            products[str(product_id)]["competitors"].append({"competitor_id": str(cid), "name": name, "price": price})

    result = []
    for entry in competitors.values():
        gaps = [g for g in entry.pop("gaps") if g is not None]
        entry["average_gap_pct"] = round(sum(gaps) / len(gaps), 1) if gaps else None
        entry["level"] = derive_level(entry.pop("stated_level"), entry.pop("discovery_method"), entry["products_linked"], catalog_size)
        result.append(entry)
    result.sort(key=lambda c: (-c["cheaper_on"], -c["products_priced"], c["name"].lower()))

    coverage = []
    for p in products.values():
        prices = p.pop("competitors")
        cheapest = min(prices, key=lambda c: c["price"]) if prices else None
        average = sum(c["price"] for c in prices) / len(prices) if prices else None
        coverage.append({
            **p,
            "competitor_count": len(prices),
            "cheapest": cheapest,
            "market_average": round(average, 4) if average is not None else None,
            "gap_pct": _pct(p["your_price"], average) if average else None,
        })
    covered = [c for c in coverage if c["competitor_count"]]
    return {
        "competitors": result,
        "market_wide": sum(1 for c in result if c["level"] == MARKET),
        "product_level": sum(1 for c in result if c["level"] == PRODUCT),
        "products": coverage,
        "catalog_size": catalog_size,
        "products_covered": len(covered),
        "products_priced_above": sum(1 for c in covered if (c["gap_pct"] or 0) >= ABOVE_MARKET_PCT),
        "price_changes_30d": sum(c["price_changes_30d"] for c in result),
    }


def link_products(conn, tenant_id: str, competitor_id: str, product_ids) -> int:
    """Links a competitor to the products it competes on (no price yet)."""
    linked = 0
    with conn.cursor() as cursor:
        for product_id in product_ids:
            cursor.execute(
                """
                INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id)
                SELECT %s, %s, p.product_id FROM products p
                WHERE p.tenant_id = %s AND p.product_id = %s AND p.deleted_at IS NULL
                ON CONFLICT (tenant_id, global_competitor_id, product_id) DO UPDATE SET is_active = TRUE;
                """,
                (tenant_id, competitor_id, tenant_id, str(product_id)),
            )
            linked += cursor.rowcount
    return linked


def set_level(conn, tenant_id: str, competitor_id: str, level: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE tenant_competitors SET competition_level = %s WHERE tenant_id = %s AND global_competitor_id = %s;",
            (level, tenant_id, competitor_id),
        )
