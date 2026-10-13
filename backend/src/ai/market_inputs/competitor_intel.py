"""Competitor intelligence: storing and reading what each competitor's own
website says (market_discovery/intel.py) and the AI analysis of it
(market_discovery/analysis.py). Every fact keeps its page and the time it
was read; reading a site again replaces what that site said before."""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from src.market_scraper.market_discovery import intel

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
# Websites read per scan (the most relevant first) and in parallel.
INTEL_MAX_SITES = int(os.getenv("DISCOVERY_INTEL_MAX_SITES", "60"))
INTEL_WORKERS = int(os.getenv("DISCOVERY_INTEL_WORKERS", "8"))
WEBSITE_KINDS = ("product", "promotion", "message", "social")


def competitor_website(conn, tenant_id: str, competitor_id: str) -> Optional[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.website_url FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.global_competitor_id = %s;
            """,
            (tenant_id, competitor_id),
        )
        row = cursor.fetchone()
    if row is None:
        raise LookupError(competitor_id)
    return row[0]


def save_site_intel(conn, tenant_id: str, competitor_id: str, result: dict) -> str:
    """Replaces the competitor's website facts with `result` (intel.collect's
    output). A site that couldn't be read keeps what was read before; a
    link found not to be the business's own site drops what was read from it,
    and the prices matched from it."""
    status = result.get("status") or ("ok" if result["facts"] or result["pages_read"] else (result.get("error") or "empty"))
    with conn.cursor() as cursor:
        if status in (intel.STATUS_OTHER_BUSINESS, intel.STATUS_NOT_OWN_SITE):
            cursor.execute("DELETE FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s AND kind = ANY(%s);",
                           (tenant_id, competitor_id, list(WEBSITE_KINDS)))
            cursor.execute("UPDATE competitor_product_mappings SET is_active = FALSE WHERE tenant_id = %s AND global_competitor_id = %s;",
                           (tenant_id, competitor_id))
        if result["pages_read"]:
            cursor.execute("DELETE FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s AND kind = ANY(%s);",
                           (tenant_id, competitor_id, list(WEBSITE_KINDS)))
            for fact in result["facts"]:
                payload = {k: v for k, v in fact.items() if k not in ("kind", "source_url", "retrieved_at", "confidence")}
                cursor.execute(
                    """
                    INSERT INTO competitor_intel (tenant_id, global_competitor_id, kind, payload, source_url, confidence, retrieved_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (tenant_id, competitor_id, fact["kind"], json.dumps(payload), fact["source_url"], fact["confidence"],
                     fact["retrieved_at"]),
                )
        cursor.execute(
            "UPDATE tenant_competitors SET intel_checked_at = CURRENT_TIMESTAMP, intel_status = %s WHERE tenant_id = %s AND global_competitor_id = %s;",
            (status, tenant_id, competitor_id),
        )
    return status


def refresh_competitor(conn, tenant_id: str, competitor_id: str, collect=intel.collect) -> dict:
    """Reads one competitor's website now. Caller commits."""
    website = competitor_website(conn, tenant_id, competitor_id)
    if not website:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE tenant_competitors SET intel_checked_at = CURRENT_TIMESTAMP, intel_status = 'no_website' WHERE tenant_id = %s AND global_competitor_id = %s;",
                (tenant_id, competitor_id),
            )
        return {"status": "no_website", "pages_read": 0, "facts": 0}
    with conn.cursor() as cursor:
        cursor.execute("SELECT competitor_name, name_ar, country_code FROM global_competitors WHERE global_competitor_id = %s;",
                       (competitor_id,))
        name, name_ar, country = cursor.fetchone() or (None, None, None)
    try:
        result = collect(website, country=country, names=[n for n in (name, name_ar) if n])
    except TypeError:  # a reader that takes only the address (tests)
        result = collect(website)
    status = save_site_intel(conn, tenant_id, competitor_id, result)
    matched = 0
    if result["pages_read"]:
        from src.market_scraper.market_discovery import pipeline

        matched = pipeline._match_prices(conn, tenant_id, [competitor_id])["prices_matched"]  # noqa: SLF001
    return {"status": status, "pages_read": len(result["pages_read"]), "facts": len(result["facts"]), "prices_matched": matched}


def refresh_strongest(conn, tenant_id: str, limit: int = INTEL_MAX_SITES, collect=intel.collect,
                      country: Optional[str] = None) -> dict:
    """After a discovery run: reads the websites of the tracked, then most
    relevant (direct before indirect) competitors not read in the last day.
    Returns counts per stage and per outcome (intel.STATUS_*)."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT tc.global_competitor_id, gc.website_url, COALESCE(gc.country_code, %s), gc.competitor_name, gc.name_ar
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND gc.website_url IS NOT NULL
              AND (tc.intel_checked_at IS NULL OR tc.intel_checked_at < CURRENT_TIMESTAMP - INTERVAL '1 day')
            ORDER BY tc.is_tracked DESC, (tc.relationship = 'DIRECT') DESC NULLS LAST, tc.relevance_score DESC NULLS LAST
            LIMIT %s;
            """,
            (country, tenant_id, limit),
        )
        targets = cursor.fetchall()
    counts = {"checked": len(targets), "read": 0, "pages": 0, "facts": 0, "products": 0, "prices": 0,
              "promotions": 0, "statuses": {}, "competitor_ids": []}
    if not targets:
        return counts

    def read(target):
        try:
            return collect(target[1], country=target[2], names=[n for n in target[3:5] if n])
        except TypeError:  # a reader that takes only the address (tests)
            return collect(target[1])

    with ThreadPoolExecutor(max_workers=max(1, min(INTEL_WORKERS, len(targets)))) as pool:
        results = list(pool.map(read, targets))
    for (competitor_id, *_rest), result in zip(targets, results):
        status = save_site_intel(conn, tenant_id, str(competitor_id), result)
        counts["statuses"][status] = counts["statuses"].get(status, 0) + 1
        if result["pages_read"]:
            counts["read"] += 1
            counts["competitor_ids"].append(str(competitor_id))
        counts["pages"] += len(result["pages_read"])
        counts["facts"] += len(result["facts"])
        products = [f for f in result["facts"] if f["kind"] == "product"]
        counts["products"] += len(products)
        counts["prices"] += sum(1 for f in products if f.get("price") is not None)
        counts["promotions"] += sum(1 for f in result["facts"] if f["kind"] == "promotion")
    return counts


def get_intel(conn, tenant_id: str, competitor_id: str) -> dict:
    """Facts grouped for the competitor screen, each with its page and time."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT kind, payload, source_url, confidence, retrieved_at FROM competitor_intel
            WHERE tenant_id = %s AND global_competitor_id = %s ORDER BY confidence DESC NULLS LAST, retrieved_at DESC;
            """,
            (tenant_id, competitor_id),
        )
        rows = cursor.fetchall()
        cursor.execute("SELECT intel_checked_at, intel_status FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
                       (tenant_id, competitor_id))
        checked = cursor.fetchone() or (None, None)
    out = {"products": [], "promotions": [], "messages": [], "social": [], "analysis": None,
           "checked_at": checked[0].isoformat() if checked[0] else None, "status": checked[1]}
    groups = {"product": "products", "promotion": "promotions", "message": "messages", "social": "social"}
    for kind, payload, url, confidence, retrieved in rows:
        entry = {**(payload or {}), "source_url": url, "confidence": float(confidence) if confidence is not None else None,
                 "retrieved_at": retrieved.isoformat()}
        if kind == "analysis":
            out["analysis"] = entry
        else:
            out[groups[kind]].append(entry)
    out["price_conflicts"] = _conflicts(out["products"])
    return out


def _conflicts(products: List[dict]) -> List[str]:
    """Product names published at more than one price (shown, not resolved)."""
    prices = {}
    for product in products:
        if product.get("price") is not None:
            prices.setdefault(product["name"].lower(), set()).add((product["price"], product.get("currency")))
    return sorted(name for name, values in prices.items() if len(values) > 1)


def save_analysis(conn, tenant_id: str, competitor_id: str, analysis: dict) -> None:
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s AND kind = 'analysis';",
                       (tenant_id, competitor_id))
        cursor.execute(
            "INSERT INTO competitor_intel (tenant_id, global_competitor_id, kind, payload) VALUES (%s, %s, 'analysis', %s);",
            (tenant_id, competitor_id, json.dumps(analysis)),
        )
