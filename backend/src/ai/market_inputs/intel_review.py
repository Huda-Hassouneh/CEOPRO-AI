"""Owner verification of competitor prices read from a website or menu
(competitor_intel_review, migration 20261023000000).

A decision is keyed by what was READ - (normalized item name, price as read) -
so it survives the replace-on-re-read that competitor_intel rows go through,
and never vouches for a different price the site shows later:
  CONFIRMED  -> fact marked verified, confidence 1.0
  CORRECTED  -> the owner's price replaces the one read (read price kept)
  REJECTED   -> fact dropped
apply_to_facts() is used by save_site_intel on every re-read; review_fact()
applies a new decision to the stored row immediately.
"""
import json
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from src.market_scraper.name_matching import normalize

VERDICTS = ("CONFIRMED", "CORRECTED", "REJECTED")
REVIEW_ROLES = {"owner", "admin"}


class ReviewError(ValueError):
    pass


def name_key(name: str) -> str:
    """Spelling-insensitive key: Arabic folding, accents and case removed; generic words kept (an item
    called "Coffee" must not collapse to an empty key)."""
    return normalize(name or "", drop_generic=False)


def _price(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001"))
    except Exception:  # noqa: BLE001
        return None


def load_reviews(conn, tenant_id: str, competitor_id: str) -> Dict[Tuple[str, Decimal], dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT name_key, read_price, verdict, corrected_price, currency, reviewed_at FROM competitor_intel_review "
            "WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        return {(row[0], _price(row[1])): {"verdict": row[2], "corrected_price": row[3], "currency": row[4],
                                            "reviewed_at": row[5].isoformat() if row[5] else None} for row in cursor.fetchall()}


def apply_to_facts(facts: List[dict], reviews: Dict[Tuple[str, Decimal], dict]) -> List[dict]:
    """Facts with the owner's decisions applied (new list; input untouched)."""
    if not reviews:
        return facts
    out = []
    for fact in facts:
        review = None
        if fact.get("kind") == "product" and fact.get("price") is not None and fact.get("name"):
            review = reviews.get((name_key(fact["name"]), _price(fact["price"])))
        if review is None:
            out.append(fact)
        elif review["verdict"] == "REJECTED":
            continue
        elif review["verdict"] == "CONFIRMED":
            out.append({**fact, "verified": True, "verdict": "CONFIRMED", "confidence": 1.0})
        else:
            fact = {**fact, "verified": True, "verdict": "CORRECTED", "read_price": fact["price"], "confidence": 1.0,
                    "price": float(review["corrected_price"])}
            if review.get("currency"):
                fact["currency"] = review["currency"]
            out.append(fact)
    return out


def review_fact(conn, tenant_id: str, competitor_id: str, intel_id: str, verdict: str, user_id: str,
                corrected_price=None, currency: Optional[str] = None, note: Optional[str] = None) -> dict:
    """Records a decision on one stored product fact and applies it to the
    stored row now. Caller commits. Raises ReviewError / LookupError."""
    if verdict not in VERDICTS:
        raise ReviewError(f"verdict must be one of {list(VERDICTS)}")
    corrected = _price(corrected_price) if corrected_price is not None else None
    if verdict == "CORRECTED" and (corrected is None or corrected < 0):
        raise ReviewError("a correction needs corrected_price (0 or more)")
    if verdict != "CORRECTED" and corrected_price is not None:
        raise ReviewError("corrected_price only goes with verdict CORRECTED")
    if currency is not None and (len(currency) != 3 or not currency.isalpha()):
        raise ReviewError("currency must be a 3-letter code")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT payload, confidence FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s "
            "AND intel_id = %s AND kind = 'product';",
            (tenant_id, competitor_id, intel_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError(intel_id)
        payload = dict(row[0] or {})
        name = payload.get("name")
        # The price as READ: a row already corrected keeps it in read_price.
        read = _price(payload.get("read_price", payload.get("price")))
        if not name or read is None:
            raise ReviewError("only a priced product can be reviewed")
        key = name_key(name)
        cursor.execute(
            """
            INSERT INTO competitor_intel_review (tenant_id, global_competitor_id, name_key, read_price, verdict, item_name,
                                                 corrected_price, currency, note, reviewed_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, global_competitor_id, name_key, read_price) DO UPDATE SET
                verdict = EXCLUDED.verdict, corrected_price = EXCLUDED.corrected_price, currency = EXCLUDED.currency,
                note = EXCLUDED.note, reviewed_by = EXCLUDED.reviewed_by, reviewed_at = CURRENT_TIMESTAMP;
            """,
            (tenant_id, competitor_id, key, read, verdict, name, corrected, (currency or "").upper() or None, note, user_id),
        )
        if verdict == "REJECTED":
            cursor.execute("DELETE FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s AND intel_id = %s;",
                           (tenant_id, competitor_id, intel_id))
        else:
            payload.pop("read_price", None)
            payload["price"] = float(read)  # start from the read value, then apply the decision
            fact = apply_to_facts([{**payload, "kind": "product", "confidence": float(row[1] or 0)}],
                                  {(key, read): {"verdict": verdict, "corrected_price": corrected,
                                                 "currency": (currency or "").upper() or None}})[0]
            fact.pop("kind", None)
            confidence = fact.pop("confidence", None)
            cursor.execute(
                "UPDATE competitor_intel SET payload = %s::jsonb, confidence = %s WHERE tenant_id = %s AND global_competitor_id = %s AND intel_id = %s;",
                (json.dumps(fact), confidence, tenant_id, competitor_id, intel_id),
            )
    return {"intel_id": intel_id, "verdict": verdict, "item": name, "read_price": float(read),
            "price": float(corrected) if corrected is not None else (None if verdict == "REJECTED" else float(read))}


def clear_review(conn, tenant_id: str, competitor_id: str, intel_id: str) -> bool:
    """Withdraws the decision made on this fact. The stored row keeps its current state until the next
    read of the site (a rejected fact is back then); returns whether a decision existed."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT payload FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s AND intel_id = %s;",
                       (tenant_id, competitor_id, intel_id))
        row = cursor.fetchone()
        if row is None:
            raise LookupError(intel_id)
        payload = row[0] or {}
        read = _price(payload.get("read_price", payload.get("price")))
        cursor.execute(
            "DELETE FROM competitor_intel_review WHERE tenant_id = %s AND global_competitor_id = %s AND name_key = %s AND read_price = %s;",
            (tenant_id, competitor_id, name_key(payload.get("name", "")), read),
        )
        return cursor.rowcount > 0


def can_review(conn, tenant_id: str, user_id: str) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
                       (tenant_id, user_id))
        row = cursor.fetchone()
    return row is not None and row[0] in REVIEW_ROLES
