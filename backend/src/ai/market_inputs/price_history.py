"""Price history of a competitor's own items (menu, site, posts) and the changes in it.

competitor_intel rows are replaced on every re-read, so a price that moved would leave no trace. record() keeps one
history row per (item, currency, price) - first and last time seen - and a CHANGE is a row whose predecessor for the
same item has another price (competitor_price_history, migration 20261024000000).

What is recorded is what the site SHOWED, not the owner's corrections of it (a correction re-applied on a later read
must not look like the competitor changing a price). Reliability is kept: a change between two weak reads (OCR,
captions, vision) is listed only on request and never raises an alert, unless the owner confirmed the read.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from src.ai.market_inputs.intel_review import name_key

logger = logging.getLogger("KEEL_PRICE_HISTORY")

NO_CURRENCY = "XXX"  # ISO 4217 "no currency": the item had none printed
RELIABLE_CONFIDENCE = 0.6  # page text 0.6, structured data 0.9, a PDF text layer 0.7; OCR 0.5, captions 0.5, vision 0.55, inferred currency 0.45 are below
RELIABLE_SQL = "(COALESCE({a}.verified, FALSE) OR COALESCE({a}.confidence, 0) >= %(reliable)s)"


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def missing_table(exc, table: str) -> bool:
    """True only for 'relation <table> does not exist' - NOT for any other 42P01 (a typo'd alias in a query also
    raises undefined_table, and swallowing that would hide a real bug)."""
    return getattr(exc, "pgcode", None) == "42P01" and table in str(exc) and "does not exist" in str(exc)


def _tolerant(conn, fn, default=None):
    """Runs fn(cursor) inside a savepoint; a missing table (code deployed before migration 20261024000000) is
    'no history yet' and never poisons the caller's transaction - reading a site must not fail over history."""
    with conn.cursor() as cursor:
        cursor.execute("SAVEPOINT price_history;")
        try:
            result = fn(cursor)
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT price_history;")
            if not missing_table(exc, "competitor_price_history"):
                raise
            return default
        cursor.execute("RELEASE SAVEPOINT price_history;")
        return result


def record(conn, tenant_id: str, competitor_id: str, facts: List[dict], reviews: Optional[Dict[Tuple[str, Decimal], dict]] = None,
           observed_at: Optional[datetime] = None) -> dict:
    """Notes the priced product facts of one read. Returns {"new_items", "changes", "unchanged", "ambiguous"}.
    `reviews` are the owner's decisions (intel_review.load_reviews): a rejected read is not recorded, a confirmed or
    corrected one is marked verified. An item shown at two different prices in the same read is ambiguous and skipped."""
    observed_at = observed_at or datetime.now(timezone.utc)
    reviews = reviews or {}
    by_item: Dict[Tuple[str, str], Dict[Decimal, dict]] = {}
    for fact in facts:
        if fact.get("kind") != "product" or fact.get("price") is None or not fact.get("name"):
            continue
        key, currency = name_key(fact["name"]), (fact.get("currency") or NO_CURRENCY).upper()
        price = _money(fact["price"])
        review = reviews.get((key, price))
        if review and review["verdict"] == "REJECTED":
            continue
        entry = {**fact, "_key": key, "_currency": currency, "_price": price,
                 "_verified": bool(review) or bool(fact.get("verified"))}
        prices = by_item.setdefault((key, currency), {})
        if price not in prices or (entry.get("confidence") or 0) > (prices[price].get("confidence") or 0):
            prices[price] = entry
    summary = {"new_items": 0, "changes": 0, "unchanged": 0, "ambiguous": 0}
    if not by_item:
        return summary

    def run(cursor):
        cursor.execute(
            """
            SELECT DISTINCT ON (name_key, currency) history_id, name_key, currency, price, confidence, verified
            FROM competitor_price_history WHERE tenant_id = %s AND global_competitor_id = %s
            ORDER BY name_key, currency, first_seen_at DESC;
            """,
            (tenant_id, competitor_id),
        )
        latest = {(row[1], row[2]): row for row in cursor.fetchall()}
        for item_key, prices in by_item.items():
            if len(prices) > 1:
                summary["ambiguous"] += 1
                continue
            entry = next(iter(prices.values()))
            last = latest.get(item_key)
            if last is not None and last[3] == entry["_price"]:
                cursor.execute(
                    """
                    UPDATE competitor_price_history SET last_seen_at = %s,
                        confidence = GREATEST(COALESCE(confidence, 0), COALESCE(%s, 0)), verified = verified OR %s
                    WHERE tenant_id = %s AND history_id = %s AND last_seen_at < %s;
                    """,
                    (observed_at, entry.get("confidence"), entry["_verified"], tenant_id, last[0], observed_at),
                )
                summary["unchanged"] += 1
                continue
            cursor.execute(
                """
                INSERT INTO competitor_price_history (tenant_id, global_competitor_id, name_key, item_name, price, currency,
                    first_seen_at, last_seen_at, source_url, extracted_by, channel, confidence, verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (tenant_id, competitor_id, entry["_key"], str(entry["name"])[:200], entry["_price"], entry["_currency"], observed_at,
                 observed_at, entry.get("source_url"), entry.get("extracted_by"), entry.get("channel"), entry.get("confidence"),
                 entry["_verified"]),
            )
            summary["changes" if last is not None else "new_items"] += 1
        return summary

    return _tolerant(conn, run, default=summary)


def mark_verified(conn, tenant_id: str, competitor_id: str, item_key: str, read_price) -> None:
    """The owner confirmed / corrected this read: its history row counts as reliable from now on."""
    _tolerant(conn, lambda cursor: cursor.execute(
        "UPDATE competitor_price_history SET verified = TRUE WHERE tenant_id = %s AND global_competitor_id = %s "
        "AND name_key = %s AND price = %s;", (tenant_id, competitor_id, item_key, _money(read_price))))


_CHANGES_SQL = """
    SELECT r.global_competitor_id, gc.competitor_name, gc.name_ar, r.name_key, r.item_name, prev.price, r.price, r.currency,
           r.first_seen_at, prev.first_seen_at, r.source_url, r.extracted_by, r.channel,
           ({reliable_r} AND {reliable_p}) AS reliable, r.verified
    FROM competitor_price_history r
    JOIN global_competitors gc ON gc.global_competitor_id = r.global_competitor_id
    JOIN LATERAL (
        SELECT p.price, p.confidence, p.verified, p.first_seen_at FROM competitor_price_history p
        WHERE p.tenant_id = r.tenant_id AND p.global_competitor_id = r.global_competitor_id
          AND p.name_key = r.name_key AND p.currency = r.currency AND p.first_seen_at < r.first_seen_at
        ORDER BY p.first_seen_at DESC LIMIT 1
    ) prev ON TRUE
    WHERE r.tenant_id = %(tenant_id)s AND r.first_seen_at >= %(since)s {competitor_filter}
      AND ({reliable_r} AND {reliable_p} OR %(include_unreliable)s)
      AND (%(min_pct)s::numeric IS NULL OR (prev.price > 0 AND ABS(r.price - prev.price) / prev.price * 100 >= %(min_pct)s::numeric))
    ORDER BY r.first_seen_at DESC, r.history_id
    LIMIT %(limit)s OFFSET %(offset)s;
"""


def list_changes(conn, tenant_id: str, competitor_id: Optional[str] = None, days: int = 90, include_unreliable: bool = False,
                 limit: int = 50, offset: int = 0, now: Optional[datetime] = None, min_pct: Optional[float] = None) -> List[dict]:
    """Price changes of items (newest first). A change is reliable when both reads were (or the owner confirmed them);
    unreliable ones (OCR / caption / vision reads) come back only with include_unreliable."""
    now = now or datetime.now(timezone.utc)
    sql = _CHANGES_SQL.format(
        reliable_r=RELIABLE_SQL.format(a="r"), reliable_p=RELIABLE_SQL.format(a="prev"),
        competitor_filter="AND r.global_competitor_id = %(competitor_id)s" if competitor_id else "",
    )
    params = {"tenant_id": tenant_id, "since": now - timedelta(days=days), "include_unreliable": include_unreliable,
              "limit": limit, "offset": offset, "reliable": RELIABLE_CONFIDENCE, "competitor_id": competitor_id, "min_pct": min_pct}

    def run(cursor):
        cursor.execute(sql, params)
        return cursor.fetchall()

    rows = _tolerant(conn, run, default=[])
    out = []
    for (cid, name, name_ar, key, item, old, new, currency, changed_at, previous_at, url, by, channel, reliable, verified) in rows:
        old_f, new_f = float(old), float(new)
        out.append({
            "competitor_id": str(cid), "competitor": name, "competitor_ar": name_ar, "item_key": key, "item": item,
            "old_price": old_f, "new_price": new_f, "currency": None if currency == NO_CURRENCY else currency,
            "change_pct": round((new_f - old_f) / old_f * 100, 1) if old_f else None,
            "direction": "down" if new_f < old_f else "up", "changed_at": changed_at.isoformat(),
            "previous_seen_at": previous_at.isoformat(), "source_url": url,
            "origin": by or ("website" if not channel else channel), "channel": channel, "reliable": bool(reliable), "verified": bool(verified),
        })
    return out


def item_series(conn, tenant_id: str, competitor_id: str, item_key: str, currency: Optional[str] = None, limit: int = 30) -> List[dict]:
    """The price history of one item, oldest first - what a small trend line is drawn from."""
    def run(cursor):
        cursor.execute(
            """
            SELECT price, currency, first_seen_at, last_seen_at, source_url, extracted_by, verified
            FROM competitor_price_history
            WHERE tenant_id = %s AND global_competitor_id = %s AND name_key = %s AND (%s::text IS NULL OR currency = %s)
            ORDER BY first_seen_at DESC LIMIT %s;
            """,
            (tenant_id, competitor_id, item_key, currency, currency, limit),
        )
        return cursor.fetchall()

    rows = _tolerant(conn, run, default=[])
    return [{"price": float(p), "currency": None if c == NO_CURRENCY else c, "first_seen_at": f.isoformat(), "last_seen_at": l.isoformat(),
             "source_url": u, "origin": by or "page", "verified": bool(v)} for p, c, f, l, u, by, v in reversed(rows)]


def alert_changes(conn, tenant_id: str, days: int, min_pct: float, limit: int = 10, now: Optional[datetime] = None) -> List[dict]:
    """Reliable changes big enough to tell the owner about, biggest first. Items already matched to one of the company's
    products are left out: their moves reach the owner through the product comparison alert (competitor_price)."""
    changes = list_changes(conn, tenant_id, None, days, False, 200, 0, now, min_pct=min_pct)
    if not changes:
        return []
    matched = _tolerant(conn, lambda cursor: _matched_item_keys(cursor, tenant_id), default=set())
    changes = [c for c in changes if (c["competitor_id"], c["item_key"]) not in matched]
    changes.sort(key=lambda c: abs(c["change_pct"]), reverse=True)
    return changes[:limit]


def _matched_item_keys(cursor, tenant_id: str) -> set:
    cursor.execute("SELECT global_competitor_id, competitor_product_sku FROM competitor_product_mappings "
                   "WHERE tenant_id = %s AND is_active = TRUE AND competitor_product_sku IS NOT NULL;", (tenant_id,))
    return {(str(cid), name_key(sku)) for cid, sku in cursor.fetchall()}
