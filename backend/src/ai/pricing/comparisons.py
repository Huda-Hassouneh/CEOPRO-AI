"""
KEEL - Price comparison ladder (read side).

How each product's price relates to what competitors sell, in four tiers
(EXACT / EQUIVALENT / SIMILAR / ADDED_VALUE - see market_scraper/price_comparison/
and PRICE_COMPARISON_TIERS_PLAN.md). The rows are written by the market scraper
service's code path (product_price_comparisons); this module only reads them,
adds the exact prices already recorded in competitor_prices, and shapes the
ladder the Pricing screen and the product page show.

Only tracked, non-manufacturer competitors count, the same filter pricing uses.
Prices are never blended across tiers: each tier has its own low/median/high
and the headline comes from the best tier available: exact, equivalent, similar
(only when like for like), then added value, then similar items that have more or
less in them than yours. ADDED_VALUE never sets the headline while a like-for-like
tier exists - the company's richer product is not what the market average measures.
"""
import statistics
from typing import Dict, Iterable, List, Optional

from src.ai.pricing import data_access
from src.market_scraper.price_comparison.tiers import ADDED_VALUE, EQUIVALENT, EXACT, SIMILAR, TIERS

MAX_PRODUCTS_PER_REQUEST = 100


def _pct(own: float, other: float) -> Optional[float]:
    return round((own - other) / other * 100, 1) if other else None


def _tier_summary(your_price: float, items: List[dict]) -> dict:
    prices = [i["comparable_price"] for i in items]
    median = statistics.median(prices) if prices else None
    directions = {i["direction"] for i in items}
    return {
        "count": len(items),
        # Who has more in it: "same", "own_richer", "own_leaner", or "mixed" when the items disagree.
        "direction": (directions.pop() if len(directions) == 1 else "mixed") if directions else None,
        "items": items,
        "low": min(prices) if prices else None,
        "median": round(median, 4) if median is not None else None,
        "high": max(prices) if prices else None,
        # Positive = you are dearer than the middle of this tier.
        "your_position_pct": _pct(your_price, median) if median else None,
    }


def build_ladder(product: dict, comparison_rows: Iterable[dict], exact_price_rows: Iterable[dict]) -> dict:
    """`product`: {product_id, current_price, currency}. Rows are plain dicts (see the loaders).
    A competitor with a recorded exact price and an EXACT comparison row is listed once."""
    your_price = float(product["current_price"])
    by_tier: Dict[str, List[dict]] = {tier: [] for tier in TIERS}
    for row in comparison_rows:
        by_tier[row["tier"]].append(row)
    exact_seen = {r["competitor_id"] for r in by_tier[EXACT]}
    for row in exact_price_rows:
        if row["competitor_id"] in exact_seen:
            continue
        by_tier[EXACT].append({
            "tier": EXACT, "competitor_id": row["competitor_id"], "competitor_name": row["competitor_name"],
            "item_name": None, "competitor_price": row["price"], "scale_factor": 1.0, "comparable_price": row["price"],
            "currency": row["currency"], "price_delta_pct": _pct(your_price, row["price"]), "direction": "same",
            "match_score": 1.0, "reasons": [{"code": "recorded_price"}], "premium": None,
            "source_url": row.get("source_url"), "observed_at": row["observed_at"],
        })
    for items in by_tier.values():
        items.sort(key=lambda i: (-i["match_score"], abs(i["price_delta_pct"] or 0), i["competitor_name"] or ""))

    tiers = {tier: _tier_summary(your_price, items) for tier, items in by_tier.items()}
    # Similar items that are not like for like (they have more or less in them than yours) only speak for the
    # product when nothing better exists: "you are 43 % above similar items" is misleading for a richer product.
    order = [EXACT, EQUIVALENT] + ([SIMILAR] if tiers[SIMILAR]["direction"] == "same" else []) + [ADDED_VALUE, SIMILAR]
    best = next((t for t in order if tiers[t]["count"]), None)
    headline = None if best is None else {
        "tier": best, "count": tiers[best]["count"], "median_comparable": tiers[best]["median"],
        "position_pct": tiers[best]["your_position_pct"], "direction": tiers[best]["direction"],
    }
    return {
        "product_id": str(product["product_id"]), "currency": product["currency"], "your_price": your_price,
        "tiers": tiers, "headline": headline, "covered": best is not None,
    }


def _rows(conn, sql: str, params: tuple) -> list:
    """A read that tolerates the table not existing yet (code deployed before migration
    20261024000000): empty, and the caller's transaction is not poisoned."""
    with conn.cursor() as cursor:
        cursor.execute("SAVEPOINT price_comparison_read;")
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            cursor.execute("ROLLBACK TO SAVEPOINT price_comparison_read;")
            if getattr(exc, "pgcode", None) != "42P01":
                raise
            return []
        cursor.execute("RELEASE SAVEPOINT price_comparison_read;")
    return rows


def load_products(conn, tenant_id: str, product_ids: List[str]) -> List[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, current_price, currency FROM products "
            "WHERE tenant_id = %s AND deleted_at IS NULL AND product_id = ANY(%s::uuid[]);",
            (tenant_id, product_ids),
        )
        return [{"product_id": str(r[0]), "current_price": float(r[1]), "currency": r[2]} for r in cursor.fetchall()]


def load_comparison_rows(conn, tenant_id: str, product_ids: List[str]) -> Dict[str, List[dict]]:
    rows = _rows(
        conn,
        """
        SELECT c.product_id, c.tier, c.direction, c.match_score, c.scale_factor, c.competitor_item_name,
               c.competitor_price, c.comparable_price, c.currency, c.price_delta_pct, c.reasons, c.premium,
               c.source_url, c.observed_at, c.global_competitor_id, gc.competitor_name, c.method
        FROM product_price_comparisons c
        JOIN tenant_competitors tc ON tc.tenant_id = c.tenant_id AND tc.global_competitor_id = c.global_competitor_id
        JOIN global_competitors gc ON gc.global_competitor_id = c.global_competitor_id
        WHERE c.tenant_id = %s AND c.product_id = ANY(%s::uuid[]) AND tc.is_tracked = TRUE AND gc.is_manufacturer = FALSE
          AND c.observed_at >= NOW() - (%s || ' days')::interval;
        """,
        (tenant_id, product_ids, str(data_access.MAX_PRICE_AGE_DAYS)),
    )
    out: Dict[str, List[dict]] = {}
    for r in rows:
        out.setdefault(str(r[0]), []).append({
            "tier": r[1], "direction": r[2], "match_score": float(r[3]), "scale_factor": float(r[4]),
            "item_name": r[5], "competitor_price": float(r[6]), "comparable_price": float(r[7]), "currency": r[8],
            "price_delta_pct": float(r[9]) if r[9] is not None else None, "reasons": r[10] or [], "premium": r[11],
            "source_url": r[12], "observed_at": r[13], "competitor_id": str(r[14]), "competitor_name": r[15], "method": r[16],
        })
    return out


def load_exact_price_rows(conn, tenant_id: str, products: List[dict]) -> Dict[str, List[dict]]:
    """Each tracked competitor's latest exact price per product (competitor_prices), same currency as the product."""
    if not products:
        return {}
    currencies = {p["product_id"]: p["currency"] for p in products}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (cpm.product_id, tc.global_competitor_id)
                   cpm.product_id, tc.global_competitor_id, gc.competitor_name, cp.scraped_price, cp.currency,
                   cp.observed_at, cpm.competitor_product_url
            FROM competitor_prices cp
            JOIN competitor_product_mappings cpm ON cpm.mapping_id = cp.mapping_id AND cpm.tenant_id = cp.tenant_id
            JOIN tenant_competitors tc ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE cp.tenant_id = %s AND cpm.product_id = ANY(%s::uuid[])
              AND cp.is_exact_data = TRUE AND cp.source_status = 'ALLOWED' AND cp.is_available = TRUE
              AND cpm.is_active = TRUE AND tc.is_tracked = TRUE AND gc.is_manufacturer = FALSE
              AND cp.observed_at >= NOW() - (%s || ' days')::interval
            ORDER BY cpm.product_id, tc.global_competitor_id, cp.observed_at DESC;
            """,
            (tenant_id, list(currencies), str(data_access.MAX_PRICE_AGE_DAYS)),
        )
        rows = cursor.fetchall()
    out: Dict[str, List[dict]] = {}
    for product_id, competitor_id, name, price, currency, observed_at, url in rows:
        if currency != currencies.get(str(product_id)):
            continue
        out.setdefault(str(product_id), []).append({
            "competitor_id": str(competitor_id), "competitor_name": name, "price": float(price), "currency": currency,
            "observed_at": observed_at, "source_url": url,
        })
    return out


def get_ladders(conn, tenant_id: str, product_ids: List[str]) -> Dict[str, dict]:
    """{product_id: ladder} for the tenant's products among product_ids (unknown ids are absent)."""
    products = load_products(conn, tenant_id, product_ids)
    comparisons = load_comparison_rows(conn, tenant_id, [p["product_id"] for p in products])
    exact = load_exact_price_rows(conn, tenant_id, products)
    return {p["product_id"]: build_ladder(p, comparisons.get(p["product_id"], []), exact.get(p["product_id"], []))
            for p in products}


def summarize(ladder: dict) -> dict:
    """The compact form for lists: counts per tier, the headline, nothing per item."""
    return {
        "product_id": ladder["product_id"], "currency": ladder["currency"], "your_price": ladder["your_price"],
        "covered": ladder["covered"], "headline": ladder["headline"],
        "counts": {tier: ladder["tiers"][tier]["count"] for tier in TIERS},
    }
