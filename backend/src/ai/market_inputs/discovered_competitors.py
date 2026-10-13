"""Read side of competitor discovery: every competitor a company knows of
(found by discovery or added by hand), with scores, branches and the public
sources each one was seen in, for the Competitors screen, the assistant and
the Command Center."""
from typing import Optional

from src.ai.market_inputs import public_sources

SORTS = {
    "relevance": "tc.relevance_score DESC NULLS LAST, tc.confidence DESC NULLS LAST, gc.competitor_name",
    "distance": "tc.distance_km ASC NULLS LAST, tc.relevance_score DESC NULLS LAST",
    "rating": "gc.rating DESC NULLS LAST, gc.review_count DESC NULLS LAST",
    "reviews": "gc.review_count DESC NULLS LAST",
    "name": "LOWER(gc.competitor_name)",
    "recent": "tc.first_seen_at DESC NULLS LAST, tc.added_at DESC",
}
# Customers see the kind of public source, never our providers (public_sources.py).
SOURCE_LABELS = public_sources.LABELS


def _row(r) -> dict:
    (cid, name, name_ar, website, phone, address, city, country, lat, lon, categories, rating, reviews, price_level,
     industry, tracked, tier, method, distance, relevance, confidence, source_count, branches, first_seen, last_seen,
     reasons, added_at, sources, demo_workspace, relationship, intel_status, intel_checked, items, priced_items,
     matched_prices, promotions) = r
    return {
        "competitor_id": str(cid), "name": name, "name_ar": name_ar, "website_url": website, "phone": phone,
        "address": address, "city": city, "country_code": country, "latitude": lat, "longitude": lon,
        "categories": categories or [], "rating": float(rating) if rating is not None else None, "review_count": reviews,
        "price_level": price_level, "industry": industry, "is_tracked": tracked, "tier": tier,
        "origin": "manual" if method is None else ("map" if method in ("MAP_LISTING", "PLACES_NEARBY") else "web"),
        "distance_km": round(distance, 2) if distance is not None else None,
        "relevance": float(relevance) if relevance is not None else None,
        "confidence": float(confidence) if confidence is not None else None,
        "source_count": source_count, "branch_count": branches,
        "first_seen_at": first_seen.isoformat() if first_seen else None,
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "added_at": added_at.isoformat() if added_at else None,
        "reasons": reasons or [],
        "sources": public_sources.merge_sources(sources),
        # Competitors entered by a demonstration workspace's seed are sample data.
        "is_demo": any(s["source"] == "demo" for s in (sources or [])) or bool(demo_workspace and method is None),
        # How it relates to the company and why (market_discovery/relevance.py).
        "relationship": relationship,
        # What its own website gave: when it was read, the outcome, and the
        # products / prices / offers found there; prices matched to the
        # company's own products.
        "website_read": {"status": intel_status, "checked_at": intel_checked.isoformat() if intel_checked else None,
                         "products": items or 0, "prices": priced_items or 0, "promotions": promotions or 0},
        "matched_prices": matched_prices or 0,
    }


_SELECT = """
    SELECT gc.global_competitor_id, gc.competitor_name, gc.name_ar, gc.website_url, gc.phone, gc.address, gc.city,
           gc.country_code, gc.latitude, gc.longitude, gc.categories, gc.rating, gc.review_count, gc.price_level,
           gc.industry_sector, tc.is_tracked, tc.tier, tc.discovery_method, tc.distance_km, tc.relevance_score,
           tc.confidence, tc.source_count, tc.branch_count, tc.first_seen_at, tc.last_seen_at, tc.match_reasons,
           tc.added_at,
           (SELECT json_agg(json_build_object('source', cs.source, 'url', cs.source_url, 'last_seen_at', cs.last_seen_at)
                            ORDER BY cs.last_seen_at DESC)
            FROM competitor_sources cs WHERE cs.tenant_id = tc.tenant_id AND cs.global_competitor_id = tc.global_competitor_id),
           (SELECT co.is_demo FROM companies co WHERE co.tenant_id = tc.tenant_id),
           tc.relationship, tc.intel_status, tc.intel_checked_at,
           (SELECT COUNT(*) FROM competitor_intel ci WHERE ci.tenant_id = tc.tenant_id
              AND ci.global_competitor_id = tc.global_competitor_id AND ci.kind = 'product'),
           (SELECT COUNT(*) FROM competitor_intel ci WHERE ci.tenant_id = tc.tenant_id
              AND ci.global_competitor_id = tc.global_competitor_id AND ci.kind = 'product' AND ci.payload->>'price' IS NOT NULL),
           (SELECT COUNT(*) FROM competitor_product_mappings cpm WHERE cpm.tenant_id = tc.tenant_id
              AND cpm.global_competitor_id = tc.global_competitor_id AND cpm.is_active
              AND EXISTS (SELECT 1 FROM competitor_prices cp WHERE cp.tenant_id = cpm.tenant_id AND cp.mapping_id = cpm.mapping_id)),
           (SELECT COUNT(*) FROM competitor_intel ci WHERE ci.tenant_id = tc.tenant_id
              AND ci.global_competitor_id = tc.global_competitor_id AND ci.kind = 'promotion')
    FROM tenant_competitors tc
    JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
    WHERE tc.tenant_id = %(t)s
"""


RELATIONSHIPS = ("DIRECT", "INDIRECT", "RELATED", "UNVERIFIED")


def list_competitors(conn, tenant_id: str, status: str = "all", sort: str = "relevance", search: Optional[str] = None,
                     origin: Optional[str] = None, min_confidence: Optional[float] = None, limit: int = 200, offset: int = 0,
                     relationship: Optional[str] = None) -> dict:
    where, params = [], {"t": tenant_id, "limit": limit, "offset": offset}
    if relationship in RELATIONSHIPS:
        where.append("tc.relationship = %(rel)s")
        params["rel"] = relationship
    elif relationship == "with_prices":
        where.append("""EXISTS (SELECT 1 FROM competitor_intel ci WHERE ci.tenant_id = tc.tenant_id
                         AND ci.global_competitor_id = tc.global_competitor_id AND ci.kind = 'product'
                         AND ci.payload->>'price' IS NOT NULL)""")
    if status == "tracked":
        where.append("tc.is_tracked")
    elif status == "suggested":
        where.append("NOT tc.is_tracked")
    if search:
        where.append("(gc.competitor_name ILIKE %(q)s OR gc.name_ar ILIKE %(q)s OR gc.address ILIKE %(q)s OR gc.website_url ILIKE %(q)s)")
        params["q"] = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if origin == "manual":
        where.append("tc.discovery_method IS NULL")
    elif origin == "map":
        where.append("tc.discovery_method IN ('MAP_LISTING', 'PLACES_NEARBY')")
    elif origin == "web":
        where.append("tc.discovery_method IN ('WEB_SEARCH', 'PRODUCT_SEARCH', 'INDUSTRY_KEYWORD_SEARCH', 'DIRECTORY')")
    if min_confidence is not None:
        where.append("COALESCE(tc.confidence, 1) >= %(minc)s")
        params["minc"] = min_confidence
    clause = "".join(f" AND {w}" for w in where)
    order = SORTS.get(sort, SORTS["relevance"])
    with conn.cursor() as cursor:
        cursor.execute(f"{_SELECT}{clause} ORDER BY tc.is_tracked DESC, {order} LIMIT %(limit)s OFFSET %(offset)s;"
                       if status == "all" else f"{_SELECT}{clause} ORDER BY {order} LIMIT %(limit)s OFFSET %(offset)s;", params)
        rows = [_row(r) for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE is_tracked), COUNT(*) FILTER (WHERE NOT is_tracked),
                   COUNT(*) FILTER (WHERE discovery_method IS NOT NULL), MAX(last_seen_at)
            FROM tenant_competitors WHERE tenant_id = %s;
            """,
            (tenant_id,),
        )
        total, tracked, suggested, discovered, last_seen = cursor.fetchone()
        cursor.execute("SELECT relationship, COUNT(*) FROM tenant_competitors WHERE tenant_id = %s AND relationship IS NOT NULL "
                       "GROUP BY 1;", (tenant_id,))
        by_relationship = {k: n for k, n in cursor.fetchall()}
        # How many match the current filters, so the list can page past the
        # first page ("Show more").
        cursor.execute(
            "SELECT COUNT(*) FROM tenant_competitors tc JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id"
            f" WHERE tc.tenant_id = %(t)s{clause};", params)
        matching = cursor.fetchone()[0]
    return {"competitors": rows, "counts": {"all": total, "tracked": tracked, "suggested": suggested, "discovered": discovered,
                                            "by_relationship": by_relationship},
            "matching": matching, "offset": offset, "limit": limit,
            "last_refreshed_at": last_seen.isoformat() if last_seen else None}


def get_competitor(conn, tenant_id: str, competitor_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(f"{_SELECT} AND tc.global_competitor_id = %(c)s;", {"t": tenant_id, "c": competitor_id})
        row = cursor.fetchone()
        if row is None:
            return None
        result = _row(row)
        cursor.execute(
            """
            SELECT source, source_ref, source_url, first_seen_at, last_seen_at, payload
            FROM competitor_sources WHERE tenant_id = %s AND global_competitor_id = %s ORDER BY last_seen_at DESC;
            """,
            (tenant_id, competitor_id),
        )
        rows = cursor.fetchall()
        result["source_records"] = [{
            "source": public_sources.category(s), "label": SOURCE_LABELS[public_sources.category(s)],
            "url": public_sources.public_url(public_sources.category(s), url),
            "first_seen_at": f.isoformat(), "last_seen_at": l.isoformat(),
            "name": (p or {}).get("name"), "address": (p or {}).get("address"), "phone": (p or {}).get("phone"),
            "rating": (p or {}).get("rating"), "reviews": (p or {}).get("reviews"),
            "latitude": (p or {}).get("lat"), "longitude": (p or {}).get("lon"),
            # What the business says about itself on its own website.
            "description": (p or {}).get("snippet") if s == "website" else None,
        } for s, _ref, url, f, l, p in rows]
    result["profiles"] = _profiles(p for *_rest, p in rows)
    return result


def _profiles(payloads) -> list:
    """Social profile links found for a competitor, from every source, once each."""
    seen, out = set(), []
    for payload in payloads:
        links = (payload or {}).get("social")
        for link in links if isinstance(links, list) else []:
            if isinstance(link, str) and link.startswith(("https://", "http://")):
                key = link.rstrip("/").lower().replace("://www.", "://")
                if key not in seen:
                    seen.add(key)
                    out.append(link)
    return out[:8]


def set_tracked(conn, tenant_id: str, competitor_id: str, tracked: bool) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE tenant_competitors SET is_tracked = %s,
                tier = CASE WHEN %s THEN (CASE WHEN tier = 'STRATEGIC' THEN tier ELSE 'RELEVANT' END) ELSE 'CANDIDATE' END
            WHERE tenant_id = %s AND global_competitor_id = %s;
            """,
            (tracked, tracked, tenant_id, competitor_id),
        )
        return cursor.rowcount == 1


def market_summary(conn, tenant_id: str) -> dict:
    """Compact numbers for the Command Center and the assistant."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FILTER (WHERE tc.is_tracked), COUNT(*) FILTER (WHERE NOT tc.is_tracked),
                   COUNT(*) FILTER (WHERE tc.distance_km <= 1), COUNT(*) FILTER (WHERE tc.distance_km <= 3),
                   ROUND(AVG(gc.rating) FILTER (WHERE gc.rating IS NOT NULL)::numeric, 2),
                   COUNT(*) FILTER (WHERE tc.first_seen_at >= NOW() - INTERVAL '30 days' AND tc.discovery_method IS NOT NULL)
            FROM tenant_competitors tc JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s;
            """,
            (tenant_id,),
        )
        tracked, suggested, within_1, within_3, avg_rating, new_30 = cursor.fetchone()
        cursor.execute(
            f"{_SELECT} AND tc.is_tracked ORDER BY tc.relevance_score DESC NULLS LAST, tc.distance_km ASC NULLS LAST LIMIT 5;",
            {"t": tenant_id},
        )
        top = [_row(r) for r in cursor.fetchall()]
    return {"tracked": tracked, "suggested": suggested, "within_1km": within_1, "within_3km": within_3,
            "average_rating": float(avg_rating) if avg_rating is not None else None, "new_last_30d": new_30,
            "top": [{k: c[k] for k in ("competitor_id", "name", "distance_km", "rating", "review_count", "relevance", "branch_count")} for c in top]}
