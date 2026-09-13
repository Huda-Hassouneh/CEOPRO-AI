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

Collapsing into a family search is gated on price, not applied blindly:
only a product priced below COLLAPSE_ELIGIBLE_PRICE_THRESHOLD for its own
currency is eligible to share a search with same-family_key() products at
all (see is_price_collapse_eligible()) - a family_key match on its own
groups nothing. A tenant/vertical where every item is individually
valuable regardless of price (jewelry, for example) can disable
collapsing entirely via select_family_representatives()'s never_collapse
param. Precision is the priority this gate protects: an ineligible
product is always returned as its own single-member family, tracked and
searched on its own, never folded into a group for the sake of cost.

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

# \w is Unicode-aware by default in Python 3 (matches Arabic, and any
# other script, not just ASCII) - a real, previously-live bug: an
# ASCII-only [a-zA-Z0-9]+ pattern found zero tokens in any pure-Arabic
# product name, so every Arabic-named product collapsed into one single
# family (the empty-key fallback), regardless of whether they were
# actually related - exactly the wrong behavior for a platform whose own
# products.product_name is natively bilingual en/ar.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


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


# Below this price (exclusive), in the product's OWN currency, a product
# is *eligible* to be collapsed into a family search - collapsing is a
# cost/politeness optimization that only makes sense when the item's own
# value is negligible (the vision's own example: basic resistors, whose
# price essentially never moves and whose per-SKU tracking precision the
# business doesn't need). A currency this map doesn't recognize is never
# treated as eligible - a silent FX guess would be a fake precision claim,
# and "track it individually" is the safe fallback, never "assume it's
# cheap". Values are a dynamic baseline (~1 USD), not a fixed calendar
# schedule - this replaces the earlier "poll cheap items monthly" idea
# entirely: an eligible item still gets searched every real discovery run,
# just once per family instead of once per SKU.
COLLAPSE_ELIGIBLE_PRICE_THRESHOLD: Dict[str, float] = {
    "JOD": 0.70,
    "USD": 1.00,
}


def is_price_collapse_eligible(current_price: Optional[float], currency: Optional[str]) -> bool:
    """True only when both the price and currency are known and the price
    is strictly below this currency's threshold. Missing price, missing
    currency, or an unrecognized currency code all return False - grouping
    is an optimization the system must earn evidence for, not a default."""
    if current_price is None or not currency:
        return False
    threshold = COLLAPSE_ELIGIBLE_PRICE_THRESHOLD.get(currency.upper())
    if threshold is None:
        return False
    return float(current_price) < threshold


def _load_prices(conn, tenant_id: str, product_ids: List[str]) -> Dict[str, "tuple[Optional[float], Optional[str]]"]:
    if not product_ids:
        return {}
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, current_price, currency FROM products "
            "WHERE tenant_id = %s AND product_id = ANY(%s::uuid[]);",
            (tenant_id, product_ids),
        )
        return {
            str(product_id): (float(price) if price is not None else None, currency)
            for product_id, price, currency in cursor.fetchall()
        }


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


def select_family_representatives(
    conn, tenant_id: str, products: List[dict], never_collapse: bool = False,
) -> List[dict]:
    """
    Groups `products` ([{"product_id", "product_name"}]) by family_key()
    and returns one representative dict per family, with two extra keys:
    "family_key" and "family_members" (every product in that family,
    representative included) - the caller uses family_members to apply
    the representative's search results to every real SKU without
    re-searching.

    Precision-first collapse gate (the real fix for "cheap resistors
    should share one search, but a gold ring never should"): a product
    only ever enters a multi-member family when its OWN current_price is
    below COLLAPSE_ELIGIBLE_PRICE_THRESHOLD for its OWN currency (see
    is_price_collapse_eligible()) - matching family_key() alone is never
    enough. Any product that fails that price check - missing price,
    unrecognized currency, or price at/above the threshold - is returned
    as its own single-member family regardless of what family_key()
    would have grouped it with; a family_key match still narrows WHICH
    eligible products can share a search, it just no longer decides
    collapse on its own. never_collapse=True (pass this for a tenant/
    vertical where every item is individually valuable - see
    sector_detection.HIGH_VALUE_VERTICALS) disables collapsing entirely
    regardless of any product's price: every product comes back as its
    own single-member family.

    Representative = highest total transactions.quantity_sold in this
    family; a family with no sales data anywhere falls back to the first
    product alphabetically by name (deterministic, not random) - real
    and stated, not disguised as volume-based.
    """
    prices = _load_prices(conn, tenant_id, [p["product_id"] for p in products])

    families: Dict[str, List[dict]] = defaultdict(list)
    singles: List[dict] = []
    for product in products:
        price, currency = prices.get(product["product_id"], (None, None))
        if never_collapse or not is_price_collapse_eligible(price, currency):
            singles.append(product)
        else:
            families[family_key(product["product_name"])].append(product)

    volumes = _load_sales_volumes(conn, tenant_id, [p["product_id"] for p in products])

    representatives = []
    for key, members in families.items():
        ranked = sorted(members, key=lambda p: (-volumes.get(p["product_id"], 0), p["product_name"]))
        representative = dict(ranked[0])
        representative["family_key"] = key
        representative["family_members"] = members
        representatives.append(representative)

    for product in singles:
        representative = dict(product)
        representative["family_key"] = family_key(product["product_name"])
        representative["family_members"] = [product]
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
