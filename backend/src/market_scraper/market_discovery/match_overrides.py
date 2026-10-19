"""The owner's decisions on which of a competitor's items is which of the company's products
(competitor_match_override, migration 20261024000000), read by offerings.record_matches on every pass.

  REJECTED  this competitor item is never matched to this product ("Mansaf tray" is not "Mansaf plate")
  MATCHED   the owner chose this item for this product (at most one per product and competitor)

Reads are tolerant of a missing table (code deployed before the migration): no decisions, and the caller's
transaction is not poisoned.
"""
from typing import Dict, Set, Tuple

from src.market_scraper.name_matching import normalize


def item_key(name: str) -> str:
    """Spelling-insensitive key of an item name; the same as intel_review.name_key."""
    return normalize(name or "", drop_generic=False)


def load(conn, tenant_id: str, competitor_id: str) -> Tuple[Set[Tuple[str, str]], Dict[str, str]]:
    """(rejected {(product_id, item_key)}, chosen {product_id: item_key})."""
    with conn.cursor() as cursor:
        cursor.execute("SAVEPOINT match_overrides_read;")
        try:
            cursor.execute(
                "SELECT product_id, item_key, verdict FROM competitor_match_override WHERE tenant_id = %s AND global_competitor_id = %s;",
                (tenant_id, competitor_id),
            )
            rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT match_overrides_read;")
            if not (getattr(exc, "pgcode", None) == "42P01" and "competitor_match_override" in str(exc) and "does not exist" in str(exc)):
                raise  # only a missing table is tolerated, not any other undefined-table error
            return set(), {}
        cursor.execute("RELEASE SAVEPOINT match_overrides_read;")
    rejected = {(str(pid), key) for pid, key, verdict in rows if verdict == "REJECTED"}
    chosen = {str(pid): key for pid, key, verdict in rows if verdict == "MATCHED"}
    return rejected, chosen
