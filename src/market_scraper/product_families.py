"""
CEOPRO AI - Family-Keyed Discovery (Architecture C).

The real scaling problem this session's own cost model identified: a
tenant with thousands of SKU-level variants ("1 Ohm resistor, 2 Ohm
resistor, ...") should not multiply scraping cost by SKU count - adding
another customer must not multiply cost the way SKU count does. This
module is that fix: group a tenant's catalog into families (variants of
the same underlying product), search ONCE per family using a real
representative SKU, then apply the SAME found competitors to every
family member - one real search instead of one per SKU, with zero loss
of per-SKU competitor_product_mappings coverage (every real SKU still
gets a real mapping row, just without a redundant re-search for it).

Representative selection is sales-volume-based when real transaction
data exists (the highest-selling variant is the one worth searching for
- it's the one a competitor is most likely to also carry and the one
whose pricing matters most), honestly falling back to alphabetical-first
when no sales data exists for a family - never silently pretended to be
volume-based when it wasn't (same "flag the real limit" discipline as
sector_detection.py's own keyword-heuristic caveat).

family_key() is a real, generic (not electronics-specific) heuristic:
strips bare numbers and common measurement-unit/size words, keeps the
remaining significant tokens. Two products differing only by a numeric
value or a size word ("1k Ohm Resistor" / "2k Ohm Resistor",
"T-Shirt Small" / "T-Shirt Large") land in the same family; two
genuinely different products do not. A heuristic, not a certainty -
collector_config/product.category could refine this later, but nothing
here is hardcoded to any one vertical.
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional

# Any token starting with a digit - covers bare numbers AND value
# notation with a unit glued on (e.g. "1k"/"2.2k" ohms, "100n" farads,
# "3xl") - a real fix, not a hypothetical one: "1k Ohm Resistor" vs
# "2k Ohm Resistor" (the literal SKU-explosion example this session's
# own earlier discussion used) does NOT get caught by a strict bare-
# number match, since "1k"/"2k" are alphanumeric tokens, not pure
# digits - it does get caught by "starts with a digit".

# Common measurement-unit and size words, generic across verticals -
# electronics values, apparel/furniture dimensions, food/beverage
# quantities all use these.
_VARIANT_WORDS = {
    "ohm", "ohms", "mm", "cm", "m", "kg", "g", "mg", "ml", "l", "in", "inch", "inches",
    "oz", "lb", "lbs", "w", "watt", "watts", "v", "volt", "volts", "amp", "amps", "a",
    "ft", "feet", "yd", "gb", "tb", "mb",
    "xs", "s", "m", "l", "xl", "xxl", "xxxl", "small", "medium", "large",
}

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def family_key(product_name: str) -> str:
    """Sorted, deduplicated significant tokens - order-independent so
    "Red Trail Shoe" and "Trail Shoe Red" land in the same family. Never
    collapses to an empty key: if every token happens to be a number/unit
    word, falls back to the full raw token set rather than grouping
    unrelated products under a blank key."""
    tokens = _TOKEN_RE.findall((product_name or "").lower())
    significant = [t for t in tokens if not t[0].isdigit() and t not in _VARIANT_WORDS]
    if not significant:
        significant = tokens
    return " ".join(sorted(set(significant)))


def _load_sales_volumes(conn, tenant_id: str, product_ids: List[str]) -> Dict[str, int]:
    if not product_ids:
        return {}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, SUM(quantity_sold)
            FROM transactions
            WHERE tenant_id = %s AND product_id = ANY(%s::uuid[])
            GROUP BY product_id;
            """,
            (tenant_id, product_ids),
        )
        return {str(product_id): int(total) for product_id, total in cursor.fetchall()}


def select_family_representatives(conn, tenant_id: str, products: List[dict]) -> List[dict]:
    """
    Groups `products` ([{"product_id", "product_name"}]) by family_key()
    and returns one representative dict per family, with two extra keys:
    "family_key" and "family_members" (every product in that family,
    representative included) - the caller uses family_members to apply
    the representative's search results to every real SKU without
    re-searching.

    Representative = highest total transactions.quantity_sold in this
    family; a family with no sales data anywhere falls back to the first
    product alphabetically by name (deterministic, not random) - real
    and stated, not disguised as volume-based.
    """
    families: Dict[str, List[dict]] = defaultdict(list)
    for product in products:
        families[family_key(product["product_name"])].append(product)

    volumes = _load_sales_volumes(conn, tenant_id, [p["product_id"] for p in products])

    representatives = []
    for key, members in families.items():
        ranked = sorted(members, key=lambda p: (-volumes.get(p["product_id"], 0), p["product_name"]))
        representative = dict(ranked[0])
        representative["family_key"] = key
        representative["family_members"] = members
        representatives.append(representative)
    return representatives


def recommended_collector_config(tier: Optional[str]) -> dict:
    """
    The real point of the 3-tier intelligence gate (tenant_competitors.
    tier, computed by competitor_classification.py::classify_competitor())
    is controlling COST by tier, not just labeling it: only a STRATEGIC
    competitor (passed manufacturer/region checks AND the product-overlap
    threshold) is worth the expensive paid-provider deep-collection
    (ScrapeCreators/Apify full comment-thread depth). A RELEVANT
    competitor (passed manufacturer/region, below the overlap threshold)
    still gets tracked and price-compared - just not the expensive social
    depth. A CANDIDATE (excluded outright - a manufacturer, or out of
    region) gets neither.

    Returns a collector_config fragment for the caller to merge into a
    source's real config when provisioning collection for this
    competitor - this function only recommends, it doesn't provision or
    run anything itself.
    """
    from src.ai.pricing.competitor_classification import TIER_STRATEGIC
    return {"fetch_comments": tier == TIER_STRATEGIC}
