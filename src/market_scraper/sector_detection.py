"""
CEOPRO AI - Dynamic Business-Vertical Detection.

Infers a tenant's business vertical from its own promoted product catalog
- no per-tenant/per-industry branching anywhere else in this codebase;
every caller (discovery.py's retail-vs-manufacturer filter, the search
query builder) takes whatever this returns and behaves the same way
regardless of which vertical it is. A new vertical is added by adding one
entry to _VERTICAL_KEYWORDS, not by writing new conditional logic per
industry.

Real constraint, flagged rather than hidden: this is a keyword-frequency
heuristic, not a trained classifier or an LLM call - no classification
API/model is configured with credentials in this environment (same
category of gap as the web-search backend documented in discovery.py).
It is genuinely dynamic (analyzes whatever catalog it's given - nothing
here is hardcoded to electronics or any other single vertical) but it is
a heuristic, and should be read as one: confident on a catalog with clear
vertical signal, degrades to "general_retail" (never a false, overconfident
guess) when it isn't.
"""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

_VERTICAL_KEYWORDS: Dict[str, List[str]] = {
    "electronics_hobbyist": [
        "arduino", "raspberry", "sensor", "resistor", "capacitor", "led", "module",
        "microcontroller", "breadboard", "diode", "transistor", "solder", "esp32", "esp8266",
        "battery", "motor", "wire", "circuit", "pcb", "usb", "relay", "stepper", "servo",
    ],
    "food_beverage": [
        "coffee", "tea", "burger", "pizza", "sandwich", "salad", "juice", "snack", "bakery",
        "menu", "dish", "meal", "beverage", "drink", "restaurant", "cafe", "bread", "cake",
    ],
    "apparel_fashion": [
        "shirt", "dress", "jacket", "jeans", "shoe", "sneaker", "hat", "sock", "coat",
        "sweater", "pants", "skirt", "scarf", "glove", "belt", "handbag", "apparel",
    ],
    "home_furniture": [
        "chair", "table", "sofa", "lamp", "shelf", "cabinet", "mattress", "rug", "curtain",
        "furniture", "desk", "drawer", "mirror", "cushion",
    ],
}

_WORD_RE = re.compile(r"[a-zA-Z]+")

# A human/search-engine-facing label per vertical - "electronics_hobbyist"
# is an internal key, nobody searches for that literal string. Used by
# build_industry_search_query() (domain-level discovery: find same-industry
# businesses, not sellers of one specific product) and infer_industry_sector()
# (best-effort backfill for an already-discovered competitor's industry).
VERTICAL_INDUSTRY_LABELS: Dict[str, str] = {
    "electronics_hobbyist": "electronics store",
    "food_beverage": "restaurant OR cafe",
    "apparel_fashion": "clothing store",
    "home_furniture": "furniture store",
    "general_retail": "retail store",
}


@dataclass(frozen=True)
class VerticalDetection:
    vertical: str  # one of _VERTICAL_KEYWORDS' keys, or "general_retail"
    confidence: float  # fraction of matched keyword hits belonging to the winning vertical
    matched_keywords: List[str]


def detect_vertical(product_names: List[str]) -> VerticalDetection:
    """Tokenizes every product name in the catalog and scores each known
    vertical by keyword-hit count; the highest-scoring vertical wins if it
    clears a low confidence floor, otherwise "general_retail" (a real,
    named fallback, not a silent electronics default)."""
    tokens = []
    for name in product_names:
        tokens.extend(word.lower() for word in _WORD_RE.findall(name or ""))
    token_set = set(tokens)

    scores = Counter()
    matched_by_vertical: Dict[str, List[str]] = {}
    for vertical, keywords in _VERTICAL_KEYWORDS.items():
        hits = [kw for kw in keywords if kw in token_set]
        scores[vertical] = len(hits)
        matched_by_vertical[vertical] = hits

    total_hits = sum(scores.values())
    if total_hits == 0:
        return VerticalDetection("general_retail", 0.0, [])

    winner, winner_hits = scores.most_common(1)[0]
    confidence = winner_hits / total_hits
    if confidence < 0.4:
        return VerticalDetection("general_retail", confidence, [])
    return VerticalDetection(winner, confidence, matched_by_vertical[winner])


# Vocabulary a search query should favor (retail/consumer-facing) or avoid
# (manufacturer/wholesale) - generic across every vertical, not electronics-
# specific: the same distinction ("who sells this to an end consumer" vs.
# "who makes/wholesales this") applies whether the catalog is resistors or
# restaurant dishes.
RETAIL_QUERY_HINTS = ["buy", "shop", "store", "price"]
MANUFACTURER_SIGNAL_WORDS = [
    "wholesale", "distributor", "b2b", "bulk order", "minimum order quantity", "moq",
    "manufacturer", "oem", "factory direct", "supplier portal",
]


def build_retail_search_query(product_name: str, geo_scope: str = None) -> str:
    """
    geo_scope: a region/country/city term ("Jordan", "New York", "USA") to
    bias discovery toward that market instead of searching globally -
    resolve_tenant_geo_scope() below is the tenant-level default this is
    normally called with; pass an explicit value to narrow/widen for one
    call without changing the tenant's stored default.
    """
    query = f'"{product_name}" ' + " ".join(RETAIL_QUERY_HINTS)
    if geo_scope:
        query += f" {geo_scope}"
    return query


def build_industry_search_query(vertical: str, geo_scope: str = None) -> str:
    """
    The domain-level counterpart to build_retail_search_query() - instead
    of "who sells THIS product", asks "who else operates in this INDUSTRY".
    This is the real query behind industry-keyword discovery
    (web_product_discovery.py::discover_industry_candidates()): no product
    name involved at all, so it can find a same-industry rival regardless
    of whether their product mix overlaps with the tenant's.

    An unrecognized vertical key falls back to VERTICAL_INDUSTRY_LABELS'
    "general_retail" entry rather than raising - same honest-degradation
    convention detect_vertical() itself already uses.
    """
    label = VERTICAL_INDUSTRY_LABELS.get(vertical, VERTICAL_INDUSTRY_LABELS["general_retail"])
    query = f"{label} " + " ".join(RETAIL_QUERY_HINTS)
    if geo_scope:
        query += f" {geo_scope}"
    return query


def infer_industry_sector(text: str) -> Optional[str]:
    """
    Best-effort industry_sector guess from a competitor's own name/title
    text, reusing the exact same _VERTICAL_KEYWORDS vocabulary detect_
    vertical() uses for a tenant's catalog - one shared vocabulary, two
    directions (tenant catalog -> vertical, competitor name -> sector).

    Cheap and local: no network call, no new dependency - just a keyword-
    frequency match against a single string. Returns None (never a guessed
    label) when nothing in the vocabulary matches - this is meant to
    backfill global_competitors.industry_sector for a competitor that
    already has a name on file, not to replace real classification.
    """
    detection = detect_vertical([text or ""])
    return detection.vertical if detection.matched_keywords else None


def resolve_tenant_geo_scope(conn, tenant_id: str, override: str = None) -> str:
    """
    Tenant-level default market scope for discovery, with no schema
    change: companies.country_code already exists and is already
    tenant-scoped - it's exactly "a clean, adaptable geographical scope
    ... regional, country-level" for the tenant's own primary market.
    `override` narrows ("Amman" - a city within it) or widens ("Middle
    East") the default for one call/run without touching the tenant's
    stored setting - the adjustability the discovery queries need to
    react to, per request, without a new config table.
    """
    if override:
        return override
    with conn.cursor() as cursor:
        cursor.execute("SELECT country_code FROM companies WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()
    return row[0] if row and row[0] else ""


def resolve_tenant_search_radius(conn, tenant_id: str, override_km: Optional[float] = None) -> Optional[float]:
    """
    Same override-over-stored-default pattern as resolve_tenant_geo_scope()
    above, for the proximity radius instead of the country scope - "expand
    or narrow the search area radius directly from the interface" is
    exactly override_km: a caller (the UI's request handler) passes
    whatever the user just set the slider to for this one call, without
    needing to persist it first via company_geo_profile.set_tenant_search_scope()
    (that's for when the user wants the new radius to become their
    standing default, a separate action from adjusting it for one search).

    "If the target region data is missing/empty, automatically fall back to
    the closest logically appropriate default scope or radius" - the real
    fix this implements: a tenant who never explicitly called
    company_geo_profile.py::set_tenant_search_scope() still has a real
    search_scope_level (the column's own DB default is 'PROVINCE'), but
    default_search_radius_km itself is NULL until that function resolves
    and stores a real preset. Rather than every caller of this function
    needing its own fallback constant, this resolves through the SAME
    preset table set_tenant_search_scope() itself uses
    (SCOPE_LEVEL_PRESET_RADIUS_KM) whenever the stored radius is missing
    but a scope_level is known - which, given the DB default, is always.

    The one genuine "no radius" case is COUNTRY scope: that's an explicit
    choice (this tenant's whole operating_countries list, not a distance
    ring), never confused with "never configured" - still returns None
    there, and callers (list_tenant_competitors_by_proximity(),
    tenant_discovery.py's Places gating) already treat that None correctly
    as "no radius filter" rather than a fallback failure.
    """
    if override_km is not None:
        return override_km
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT default_search_radius_km, search_scope_level FROM companies WHERE tenant_id = %s;",
            (tenant_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    radius_km, scope_level = row
    if radius_km is not None:
        return radius_km

    from src.market_scraper.company_geo_profile import (
        SCOPE_LEVEL_COUNTRY, SCOPE_LEVEL_PRESET_RADIUS_KM, SCOPE_LEVEL_PROVINCE,
    )
    if scope_level == SCOPE_LEVEL_COUNTRY:
        return None
    # Any other scope_level (including one this module doesn't recognize,
    # defensively) falls back to PROVINCE's own preset - "closest logically
    # appropriate default" per the product ask, never a silently-None
    # radius for a tenant who simply never explicitly configured one.
    return SCOPE_LEVEL_PRESET_RADIUS_KM.get(scope_level, SCOPE_LEVEL_PRESET_RADIUS_KM[SCOPE_LEVEL_PROVINCE])
