"""Which of a competitor's items is which of the company's products, and the owner's corrections.

The automatic match (market_discovery/offerings.py) can be wrong - "Mansaf tray" matched to "Mansaf plate" feeds a wrong
price comparison, recommendation and alert. The owner can say "not this item" (REJECTED) or pick the right item
(MATCHED); decisions are kept in competitor_match_override and respected by every later pass.
"""
from typing import Dict, List, Optional

from src.market_scraper.market_discovery import match_overrides, offerings

REVIEW_ROLES = {"owner", "admin"}


class MatchError(ValueError):
    pass


def _product(conn, tenant_id: str, product_id: str) -> Optional[dict]:
    return next((p for p in offerings.company_products(conn, tenant_id) if p["product_id"] == str(product_id)), None)


def list_matches(conn, tenant_id: str, competitor_id: str) -> dict:
    """{"matches": [...], "items": [...], "rejected": [...]}: the active matches (with the item and price they rest on),
    the competitor's priced items an owner may choose from, and the pairs the owner rejected."""
    rejected_keys, chosen = match_overrides.load(conn, tenant_id, competitor_id)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT cpm.mapping_id, cpm.product_id, localized_text(p.product_name), p.current_price, p.currency,
                   cpm.competitor_product_sku, cpm.competitor_product_url, lp.scraped_price, lp.currency, lp.observed_at
            FROM competitor_product_mappings cpm
            JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id AND p.deleted_at IS NULL
            LEFT JOIN LATERAL (SELECT scraped_price, currency, observed_at FROM competitor_prices cp
                               WHERE cp.tenant_id = cpm.tenant_id AND cp.mapping_id = cpm.mapping_id
                               ORDER BY observed_at DESC LIMIT 1) lp ON TRUE
            WHERE cpm.tenant_id = %s AND cpm.global_competitor_id = %s AND cpm.is_active = TRUE
            ORDER BY localized_text(p.product_name);
            """,
            (tenant_id, competitor_id),
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT o.product_id, localized_text(p.product_name), o.item_name, o.decided_at FROM competitor_match_override o "
            "JOIN products p ON p.tenant_id = o.tenant_id AND p.product_id = o.product_id "
            "WHERE o.tenant_id = %s AND o.global_competitor_id = %s AND o.verdict = 'REJECTED' ORDER BY o.decided_at DESC;",
            (tenant_id, competitor_id),
        ) if rejected_keys else None
        rejected_rows = cursor.fetchall() if rejected_keys else []
        cursor.execute(
            "SELECT intel_id, payload, source_url, confidence FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s "
            "AND kind = 'product' ORDER BY (payload->>'name');", (tenant_id, competitor_id))
        intel_rows = cursor.fetchall()
    matches = []
    for mapping_id, pid, name, price, currency, sku, url, scraped, scraped_currency, observed in rows:
        key = match_overrides.item_key(sku or "")
        matches.append({
            "mapping_id": str(mapping_id), "product_id": str(pid), "product": name,
            "your_price": float(price) if price is not None else None, "currency": currency, "item": sku, "item_url": url,
            "their_price": float(scraped) if scraped is not None else None, "their_currency": scraped_currency,
            "observed_at": observed.isoformat() if observed else None, "owner_chosen": chosen.get(str(pid)) == key,
        })
    items = []
    for intel_id, payload, url, confidence in intel_rows:
        payload = payload or {}
        if payload.get("price") is None or not payload.get("name"):
            continue
        social_unconfirmed = payload.get("channel") not in (None, "website") and not payload.get("verified")
        items.append({"intel_id": str(intel_id), "name": payload["name"], "price": payload["price"], "currency": payload.get("currency"),
                      "source_url": url, "needs_confirmation": social_unconfirmed})
    return {"matches": matches, "items": items,
            "rejected": [{"product_id": str(pid), "product": name, "item": item, "decided_at": at.isoformat()} for pid, name, item, at in rejected_rows]}


def _rematch(conn, tenant_id: str, competitor_id: str, product: dict) -> Optional[dict]:
    result = offerings.record_matches(conn, tenant_id, competitor_id, [product], update_rate=False)
    return result["matches"][0] if result["matches"] else None


def reject_match(conn, tenant_id: str, competitor_id: str, product_id: str, user_id: str) -> dict:
    """"This item is not that product": never match it again, switch the mapping off and look for another item."""
    product = _product(conn, tenant_id, product_id)
    if product is None:
        raise LookupError(product_id)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT competitor_product_sku FROM competitor_product_mappings WHERE tenant_id = %s AND global_competitor_id = %s "
            "AND product_id = %s AND is_active = TRUE;", (tenant_id, competitor_id, product_id))
        row = cursor.fetchone()
        if row is None or not row[0]:
            raise LookupError("no active match for this product")
        sku = row[0]
        key = match_overrides.item_key(sku)
        cursor.execute("DELETE FROM competitor_match_override WHERE tenant_id = %s AND global_competitor_id = %s AND product_id = %s "
                       "AND verdict = 'MATCHED';", (tenant_id, competitor_id, product_id))
        cursor.execute(
            """
            INSERT INTO competitor_match_override (tenant_id, global_competitor_id, product_id, item_key, item_name, verdict, decided_by)
            VALUES (%s, %s, %s, %s, %s, 'REJECTED', %s)
            ON CONFLICT (tenant_id, global_competitor_id, product_id, item_key) DO UPDATE
                SET verdict = 'REJECTED', decided_by = EXCLUDED.decided_by, decided_at = CURRENT_TIMESTAMP;
            """,
            (tenant_id, competitor_id, product_id, key, sku, user_id),
        )
        cursor.execute("UPDATE competitor_product_mappings SET is_active = FALSE WHERE tenant_id = %s AND global_competitor_id = %s "
                       "AND product_id = %s;", (tenant_id, competitor_id, product_id))
    return {"product_id": str(product_id), "rejected_item": sku, "new_match": _rematch(conn, tenant_id, competitor_id, product)}


def choose_match(conn, tenant_id: str, competitor_id: str, product_id: str, intel_id: str, user_id: str) -> dict:
    """The owner picks the competitor item that IS this product."""
    product = _product(conn, tenant_id, product_id)
    if product is None:
        raise LookupError(product_id)
    with conn.cursor() as cursor:
        cursor.execute("SELECT payload FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s AND intel_id = %s "
                       "AND kind = 'product';", (tenant_id, competitor_id, intel_id))
        row = cursor.fetchone()
    if row is None:
        raise LookupError(intel_id)
    payload = row[0] or {}
    if payload.get("price") is None or not payload.get("name"):
        raise MatchError("only a priced item can be matched")
    if (payload.get("currency") or None) != (product.get("currency") or None):
        raise MatchError("the item is priced in another currency than the product; prices in different currencies are never compared")
    if payload.get("channel") not in (None, "website") and not payload.get("verified"):
        raise MatchError("confirm this price first: a price read from a post is only used once you have confirmed it")
    key = match_overrides.item_key(payload["name"])
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM competitor_match_override WHERE tenant_id = %s AND global_competitor_id = %s AND product_id = %s "
                       "AND (verdict = 'MATCHED' OR item_key = %s);", (tenant_id, competitor_id, product_id, key))
        cursor.execute(
            "INSERT INTO competitor_match_override (tenant_id, global_competitor_id, product_id, item_key, item_name, verdict, decided_by) "
            "VALUES (%s, %s, %s, %s, %s, 'MATCHED', %s);",
            (tenant_id, competitor_id, product_id, key, payload["name"], user_id),
        )
    return {"product_id": str(product_id), "new_match": _rematch(conn, tenant_id, competitor_id, product)}


def clear_match(conn, tenant_id: str, competitor_id: str, product_id: str) -> dict:
    """Back to automatic matching for this product."""
    product = _product(conn, tenant_id, product_id)
    if product is None:
        raise LookupError(product_id)
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM competitor_match_override WHERE tenant_id = %s AND global_competitor_id = %s AND product_id = %s;",
                       (tenant_id, competitor_id, product_id))
        removed = cursor.rowcount
    return {"product_id": str(product_id), "cleared": removed, "new_match": _rematch(conn, tenant_id, competitor_id, product)}


def can_manage(conn, tenant_id: str, user_id: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;", (tenant_id, user_id))
        row = cursor.fetchone()
    return row is not None and row[0] in REVIEW_ROLES
