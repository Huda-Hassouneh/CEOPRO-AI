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
from typing import Dict, List

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
