"""
Turns each competitor's published items into the price comparison ladder.

For every (company product, competitor item) pair in the same currency the
tier is decided by tiers.classify(); per product and competitor the closest
item of each tier is kept (so one long menu does not bury the ladder) and the
competitor's rows are replaced in one go - an item that disappeared from the
competitor's menu disappears from the ladder.

Written to product_price_comparisons, never to competitor_prices: those rows
are exact prices that feed pricing recommendations and analytics, while a
similar or scaled price is weaker evidence and is labelled as such
(migration 20261024000000). Runs from the discovery pipeline after the exact
matcher, and on demand from POST /pricing/comparisons/refresh; both read only
what is already stored, so it costs no external request.
"""
import json
import logging
from functools import lru_cache
from typing import Dict, List, Optional

from src.market_scraper.market_discovery import offerings
from src.market_scraper.name_matching import normalize
from src.market_scraper.price_comparison import adjudicate, attributes, tiers

logger = logging.getLogger("KEEL_PRICE_COMPARISON")


@lru_cache(maxsize=8192)
def _parse(name: str):
    """parse_offer, cached: a menu item is read once however many products it is compared with. The result is
    never modified (tiers.classify copies before changing anything)."""
    return attributes.parse_offer(name)


def load_prior_verdicts(conn, tenant_id: str, competitor_id: str) -> Dict[tuple, tuple]:
    """The AI's earlier verdicts for this competitor, read from the rows about to be replaced:
    {(product_id, name_key): (side, words, verdict)}. Reusing them means a recompute never asks the model the same
    question twice and never loses an answer. Tolerates a missing table."""
    with conn.cursor() as cursor:
        cursor.execute("SAVEPOINT price_comparison_prior_read;")
        try:
            cursor.execute(
                "SELECT product_id, competitor_item_name, reasons FROM product_price_comparisons "
                "WHERE tenant_id = %s AND global_competitor_id = %s AND method = 'AI_ASSISTED';", (tenant_id, competitor_id))
            rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT price_comparison_prior_read;")
            if getattr(exc, "pgcode", None) != "42P01":
                raise
            return {}
        cursor.execute("RELEASE SAVEPOINT price_comparison_prior_read;")
    out: Dict[tuple, tuple] = {}
    for product_id, item_name, reasons in rows:
        for reason in reasons or []:
            if isinstance(reason, dict) and reason.get("code") == "ai_judged":
                out[(str(product_id), name_key(item_name))] = (reason.get("side"), tuple(reason.get("words") or ()), reason.get("verdict"))
    return out


def _may_relate(own: attributes.Offer, item: attributes.Offer) -> bool:
    """A cheap test that drops the pairs tiers.classify would reject anyway (no word in common, not even a
    near-spelling or a compound): they share the start or the end of some word. Pure speed - the result of
    compare() is identical with or without it (checked on a 150k-pair synthetic menu)."""
    return any(a[:2] == b[:2] or a[-3:] == b[-3:] for a in own.words for b in item.words)


def name_key(name: str) -> str:
    return normalize(name or "", drop_generic=False)


def load_overrides(conn, tenant_id: str, competitor_id: str) -> Dict[tuple, str]:
    """{(product_id, name_key): ADDITION|VARIANT|NOT_COMPARABLE} for one competitor. A deployment without the table
    (migration 20261026000000) has no decisions, and the caller's transaction is not poisoned."""
    with conn.cursor() as cursor:
        cursor.execute("SAVEPOINT price_comparison_overrides_read;")
        try:
            cursor.execute(
                "SELECT product_id, name_key, verdict FROM product_price_comparison_overrides "
                "WHERE tenant_id = %s AND global_competitor_id = %s;", (tenant_id, competitor_id))
            rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT price_comparison_overrides_read;")
            if getattr(exc, "pgcode", None) != "42P01":
                raise
            return {}
        cursor.execute("RELEASE SAVEPOINT price_comparison_overrides_read;")
    return {(str(r[0]), r[1]): r[2] for r in rows}


def compare(product: dict, items: List[dict], judge: Optional[adjudicate.Judge] = None, budget: Optional[list] = None,
            overrides: Optional[Dict[tuple, str]] = None, verdicts: Optional[Dict[tuple, tuple]] = None) -> List[dict]:
    """The closest competitor item of each tier for one product:
    [{tier, item, comparison}], at most one per tier. `product`:
    {name, name_alt, price, currency}; `items`: priced competitor items."""
    own_names = [n for n in (product.get("name"), product.get("name_alt")) if n]
    own_offers = [_parse(n) for n in own_names]
    if not own_offers or not product.get("price"):
        return []
    best: Dict[str, tuple] = {}
    for item in items:
        if item.get("price") is None or item.get("currency") != product.get("currency"):
            continue
        item_offer = _parse(item.get("name") or "")
        for own in own_offers:
            if not _may_relate(own, item_offer):
                continue
            comparison = tiers.classify(own, item_offer, float(product["price"]), float(item["price"]))
            if comparison is None:
                continue
            decision = (overrides or {}).get((str(product["product_id"]), name_key(item.get("name") or "")))
            if decision == "NOT_COMPARABLE":
                continue
            if decision in ("ADDITION", "VARIANT"):
                comparison = tiers.force_verdict(comparison, decision.lower(), float(product["price"]))
            elif comparison.ambiguous and (prior := (verdicts or {}).get((str(product["product_id"]), name_key(item.get("name") or "")))) \
                    and prior[0] == comparison.ambiguous["side"] and prior[1] == tuple(comparison.ambiguous["words"]):
                comparison = tiers.apply_verdict(comparison, prior[2], float(product["price"]))
            elif comparison.ambiguous and judge is not None and (budget is None or budget[0] > 0):
                if budget is not None:
                    budget[0] -= 1
                verdict = judge(own_names[own_offers.index(own)], item.get("name") or "", comparison.ambiguous["side"],
                                comparison.ambiguous["words"])
                comparison = tiers.apply_verdict(comparison, verdict, float(product["price"])) if verdict else comparison
            # Closest first: higher name agreement, then the smaller price gap.
            rank = (comparison.match_score, -abs(comparison.price_delta_pct or 0))
            held = best.get(comparison.tier)
            if held is None or rank > held[0]:
                best[comparison.tier] = (rank, item, comparison)
    return [{"tier": tier, "item": best[tier][1], "comparison": best[tier][2]} for tier in tiers.TIERS if tier in best]


def refresh_for_competitor(conn, tenant_id: str, competitor_id: str, products: List[dict],
                           items: Optional[List[dict]] = None, judge: Optional[adjudicate.Judge] = None,
                           budget: Optional[list] = None) -> dict:
    """Replaces this competitor's comparison rows. Caller commits."""
    overrides = load_overrides(conn, tenant_id, competitor_id)
    verdicts = load_prior_verdicts(conn, tenant_id, competitor_id)
    items = [i for i in (items if items is not None else offerings.competitor_items(conn, tenant_id, competitor_id))
             if i.get("price") is not None and i.get("currency")]
    counts = {tier: 0 for tier in tiers.TIERS}
    unsettled = 0
    rows = []
    for product in products:
        for entry in compare(product, items, judge, budget, overrides, verdicts):
            item, comparison = entry["item"], entry["comparison"]
            counts[comparison.tier] += 1
            unsettled += 1 if comparison.ambiguous else 0
            rows.append((
                tenant_id, product["product_id"], competitor_id, comparison.tier, comparison.direction,
                comparison.match_score, comparison.scale_factor, (item.get("name") or "")[:200], float(item["price"]),
                comparison.comparable_price, item["currency"], comparison.price_delta_pct,
                json.dumps(comparison.reasons), json.dumps(comparison.premium) if comparison.premium else None,
                comparison.method, item.get("source_url"), item.get("retrieved_at"),
            ))
    with conn.cursor() as cursor:
        # A savepoint, so code deployed before migration 20261024000000 skips the ladder
        # (undefined_table) instead of poisoning the caller's transaction - reading a
        # competitor's site must never fail because of it.
        cursor.execute("SAVEPOINT price_comparison_write;")
        try:
            _replace_rows(cursor, tenant_id, competitor_id, rows)
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT price_comparison_write;")
            if getattr(exc, "pgcode", None) != "42P01":  # anything but undefined_table is a real error
                raise
            logger.warning("product_price_comparisons is missing - apply migration 20261024000000")
            return {"items_considered": len(items), "rows": 0, "by_tier": {tier: 0 for tier in tiers.TIERS}, "unsettled": 0, "skipped": "no_table"}
        cursor.execute("RELEASE SAVEPOINT price_comparison_write;")
    return {"items_considered": len(items), "rows": len(rows), "by_tier": counts, "unsettled": unsettled}


def _replace_rows(cursor, tenant_id: str, competitor_id: str, rows: List[tuple]) -> None:
    cursor.execute("DELETE FROM product_price_comparisons WHERE tenant_id = %s AND global_competitor_id = %s;",
                   (tenant_id, competitor_id))
    for row in rows:
        cursor.execute(
            """
            INSERT INTO product_price_comparisons
                (tenant_id, product_id, global_competitor_id, tier, direction, match_score, scale_factor,
                 competitor_item_name, competitor_price, comparable_price, currency, price_delta_pct, reasons,
                 premium, method, source_url, observed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                    COALESCE(%s, CURRENT_TIMESTAMP));
            """,
            row,
        )


def refresh_for_tenant(conn, tenant_id: str, judge: Optional[adjudicate.Judge] = None) -> dict:
    """Recomputes every tracked competitor from its stored items - no crawl. With a judge, ambiguous pairs are
    settled by the AI model, up to adjudicate.MAX_PAIRS_PER_RUN questions."""
    budget = [adjudicate.MAX_PAIRS_PER_RUN]
    products = offerings.company_products(conn, tenant_id)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ci.global_competitor_id
            FROM competitor_intel ci
            JOIN tenant_competitors tc ON tc.tenant_id = ci.tenant_id AND tc.global_competitor_id = ci.global_competitor_id
            WHERE ci.tenant_id = %s AND ci.kind = 'product' AND tc.is_tracked = TRUE;
            """,
            (tenant_id,),
        )
        competitor_ids = [str(r[0]) for r in cursor.fetchall()]
        # Also competitors that already have ladder rows but no items left (every item removed or rejected): their
        # stale rows must go. The table may not exist yet (migration 20261024000000).
        cursor.execute("SAVEPOINT price_comparison_stale_read;")
        try:
            cursor.execute("SELECT DISTINCT global_competitor_id FROM product_price_comparisons WHERE tenant_id = %s;", (tenant_id,))
            known = {str(r[0]) for r in cursor.fetchall()}
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT price_comparison_stale_read;")
            if getattr(exc, "pgcode", None) != "42P01":
                raise
            known = set()
        else:
            cursor.execute("RELEASE SAVEPOINT price_comparison_stale_read;")
        competitor_ids += sorted(known - set(competitor_ids))
    totals = {"competitors": 0, "rows": 0, "unsettled": 0, "by_tier": {tier: 0 for tier in tiers.TIERS}}
    for competitor_id in competitor_ids:
        result = refresh_for_competitor(conn, tenant_id, competitor_id, products, judge=judge, budget=budget)
        totals["competitors"] += 1
        totals["rows"] += result["rows"]
        totals["unsettled"] += result.get("unsettled", 0)
        for tier, count in result["by_tier"].items():
            totals["by_tier"][tier] += count
    return totals
