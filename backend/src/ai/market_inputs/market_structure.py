"""The shape of a company's market, from what discovery stored - no model,
no guess: how many businesses compete and how closely, what kinds they
are, how far away, how many are chains, how many publish their prices, and
for each of the company's products the published competitor prices found.
Every figure is a count or a range over stored, source-backed rows."""
from typing import Dict, List

_DISTANCE_BANDS = ((1, "under_1km"), (3, "1_3km"), (5, "3_5km"), (10, "5_10km"), (10_000, "over_10km"))


def _category(raw: str) -> str:
    return raw.split(":", 1)[-1].split("=", 1)[-1].replace("_", " ")


def build(conn, tenant_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(tc.relationship, 'UNCLASSIFIED'), tc.distance_km, COALESCE(tc.branch_count, 1), gc.categories,
                   gc.website_url IS NOT NULL, tc.intel_status, tc.discovery_method
            FROM tenant_competitors tc JOIN global_competitors gc USING (global_competitor_id)
            WHERE tc.tenant_id = %s;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT localized_text(p.product_name), p.current_price, p.currency, cp.scraped_price, cp.currency,
                   gc.competitor_name, cpm.competitor_product_url, cp.observed_at,
                   CASE
                     WHEN EXISTS (SELECT 1 FROM evidence_records e WHERE e.tenant_id=cpm.tenant_id
                       AND e.source_module='manual_competitor_price'
                       AND e.source_record_ids->>'competitor_price_id'=cp.competitor_price_id::text) THEN 'manual'
                     WHEN EXISTS (SELECT 1 FROM market_observations mo WHERE mo.tenant_id=cpm.tenant_id
                       AND mo.mapping_id=cpm.mapping_id AND mo.observed_at=cp.observed_at) THEN 'scraped'
                     ELSE 'manual_or_unrecorded'
                   END
            FROM competitor_product_mappings cpm
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id AND p.deleted_at IS NULL
            JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
            JOIN LATERAL (SELECT competitor_price_id, scraped_price, currency, observed_at FROM competitor_prices x
                          WHERE x.tenant_id = cpm.tenant_id AND x.mapping_id = cpm.mapping_id
                          ORDER BY observed_at DESC LIMIT 1) cp ON TRUE
            WHERE cpm.tenant_id = %s AND cpm.is_active;
            """,
            (tenant_id,),
        )
        price_rows = cursor.fetchall()
    relationships: Dict[str, int] = {}
    categories: Dict[str, int] = {}
    bands = {label: 0 for _limit, label in _DISTANCE_BANDS}
    chains = with_site = read = priced = 0
    manually_added = 0
    for relationship, distance, branches, cats, has_site, status, discovery_method in rows:
        manually_added += 1 if discovery_method is None else 0
        relationships[relationship] = relationships.get(relationship, 0) + 1
        for raw in (cats or [])[:1]:
            name = _category(raw)
            categories[name] = categories.get(name, 0) + 1
        if distance is not None:
            bands[next(label for limit, label in _DISTANCE_BANDS if distance < limit)] += 1
        chains += 1 if branches and branches > 1 else 0
        with_site += 1 if has_site else 0
        read += 1 if status in ("prices_found", "no_price_published", "no_relevant_page") else 0
        priced += 1 if status == "prices_found" else 0
    products: Dict[str, dict] = {}
    for name, own, own_currency, price, currency, competitor, url, observed, provenance in price_rows:
        if currency != own_currency:
            continue
        entry = products.setdefault(name, {"product": name, "your_price": float(own), "currency": own_currency, "prices": []})
        entry["prices"].append({"competitor": competitor, "price": float(price), "source_url": url,
                                "observed_at": observed.isoformat() if observed else None,
                                "provenance": provenance, "provider_verified": False})
    comparisons: List[dict] = []
    for entry in products.values():
        values = sorted(p["price"] for p in entry["prices"])
        middle = values[len(values) // 2] if len(values) % 2 else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2
        comparisons.append({**entry, "count": len(values), "min": values[0], "max": values[-1], "median": round(middle, 3),
                            "position": "above" if entry["your_price"] > values[-1] else
                                        "below" if entry["your_price"] < values[0] else "within"})
    comparisons.sort(key=lambda c: -c["count"])
    return {
        "businesses": len(rows),
        "registration": {"manual_or_unrecorded": manually_added, "automatically_discovered": len(rows)-manually_added},
        "by_relationship": relationships,
        "top_categories": sorted(({"category": k, "count": v} for k, v in categories.items()), key=lambda c: -c["count"])[:10],
        "distance_bands": bands,
        "chains": chains,
        "websites": {"known": with_site, "read": read, "with_prices": priced},
        "product_prices": comparisons,
    }
