"""
KEEL - Dynamic Business-Vertical Detection.

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
    "pharmacy": [
        "pharmacy", "medicine", "medication", "prescription", "antibiotic", "analgesic",
        "antiseptic", "syrup", "ointment", "vitamin", "supplement", "capsule", "pharmaceutical",
        "bandage", "dosage", "otc", "paracetamol", "ibuprofen", "lotion", "inhaler",
    ],
    "hospitality": [
        "hotel", "resort", "suite", "reservation", "checkin", "checkout", "amenity",
        "amenities", "lobby", "concierge", "minibar", "housekeeping", "booking", "guesthouse",
        "فندق", "حجز", "hôtel", "réservation",
    ],
    # Added after first-customer testing across business types: beauty,
    # grocery, services, manufacturing and automotive catalogs all fell to
    # "general_retail" and were searched as a "retail store".
    "beauty_personal_care": [
        "shampoo", "conditioner", "cream", "serum", "lipstick", "mascara", "perfume", "fragrance",
        "makeup", "cosmetic", "cosmetics", "skincare", "moisturizer", "cleanser", "nail", "salon",
        "haircut", "manicure", "pedicure", "facial", "waxing", "soap",
        "شامبو", "كريم", "عطر", "مكياج", "صابون", "صالون", "قص", "بشرة",
        "crème", "parfum", "maquillage", "savon", "coiffure",
    ],
    "grocery": [
        "rice", "flour", "sugar", "oil", "olive", "dates", "honey", "spice", "spices", "zaatar",
        "sumac", "tomato", "tomatoes", "potato", "onion", "milk", "cheese", "yogurt", "egg",
        "eggs", "lentils", "beans", "pasta", "grocery", "vegetables", "fruit",
        "أرز", "رز", "طحين", "سكر", "زيت", "زيتون", "تمر", "عسل", "زعتر", "سماق", "بندورة",
        "طماطم", "حليب", "جبنة", "لبن", "بيض", "عدس",
        "riz", "farine", "sucre", "huile", "olive", "miel", "épices", "lait", "fromage", "oeufs",
    ],
    "professional_services": [
        "consulting", "consultation", "service", "services", "session", "hour", "hours",
        "audit", "installation", "repair", "maintenance", "training", "course", "subscription",
        "retainer", "design", "cleaning", "legal", "accounting", "tutoring", "therapy",
        "استشارة", "خدمة", "خدمات", "جلسة", "ساعة", "صيانة", "تركيب", "تدريب", "اشتراك", "تصميم",
        "conseil", "séance", "heure", "réparation", "entretien", "formation", "abonnement",
    ],
    "industrial_manufacturing": [
        "steel", "aluminium", "aluminum", "fabric", "cotton", "yarn", "pipe", "pipes", "valve",
        "bolt", "bolts", "sheet", "panel", "cement", "resin", "pallet", "granules", "polymer",
        "machining", "casting", "raw", "industrial", "component", "components", "ton", "tons",
        "حديد", "فولاذ", "قماش", "قطن", "خيوط", "أنابيب", "مواسير", "إسمنت", "اسمنت", "ألواح",
        "acier", "tissu", "coton", "tuyau", "ciment", "résine",
    ],
    "automotive": [
        "tire", "tyre", "tires", "brake", "brakes", "engine", "filter", "spark", "plug", "car",
        "vehicle", "spare", "radiator", "clutch", "wiper",
        "إطار", "اطارات", "فرامل", "محرك", "فلتر", "سيارة", "قطع",
        "pneu", "frein", "moteur", "voiture",
    ],
}

# Unicode letters, not just [a-zA-Z]: an Arabic- or French-named catalog
# ("زيت زيتون", "crème") used to produce zero tokens and always fell back
# to general_retail. Same fix product_families.py already carries.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

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
    "pharmacy": "pharmacy",
    "hospitality": "hotel OR resort",
    "beauty_personal_care": "beauty salon OR cosmetics store",
    "grocery": "grocery store OR supermarket",
    "professional_services": "services company",
    "industrial_manufacturing": "manufacturer OR industrial supplier",
    "automotive": "auto parts store OR car service",
    "general_retail": "retail store",
}


@dataclass(frozen=True)
class VerticalDetection:
    vertical: str  # one of _VERTICAL_KEYWORDS' keys, or "general_retail"
    confidence: float  # fraction of matched keyword hits belonging to the winning vertical
    matched_keywords: List[str]


def detect_vertical(product_names: List[str], business_type: Optional[str] = None) -> VerticalDetection:
    """Tokenizes every product name in the catalog and scores each known
    vertical by keyword-hit count; the highest-scoring vertical wins if it
    clears a low confidence floor, otherwise "general_retail" (a real,
    named fallback, not a silent electronics default).

    business_type is the owner's own description of their business
    (companies.business_type, free text from settings/onboarding). When it
    clearly names a vertical it wins outright - "Hair salon" is a better
    signal than guessing from product names."""
    if business_type:
        declared = detect_vertical([business_type])
        if declared.vertical != "general_retail" and declared.confidence >= 0.6:
            return declared
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

# How a tenant describes ITSELF as a maker/wholesaler (companies.business_type).
# Broader than the candidate-page signals above: onboarding's own option is
# "manufacturing", and owners write "industrial supplies", "factory",
# "food producer", in Arabic or French - all of whom compete with other
# manufacturers, so the manufacturer exclusion must not apply to them.
TENANT_MANUFACTURER_SELF_DESCRIPTIONS = [
    "manufactur", "wholesal", "distribut", "b2b", "oem", "factory", "industrial", "industry",
    "producer", "production", "supplier", "fabricat",
    "مصنع", "تصنيع", "صناع", "جملة", "توزيع", "موزع", "مورد", "إنتاج", "انتاج",
    "fabricant", "grossiste", "industriel", "usine", "fournisseur", "producteur",
]


def load_business_type(conn, tenant_id: str) -> Optional[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT business_type FROM companies WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()
    return row[0] if row and isinstance(row[0], str) else None


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
    Tenant-level default market scope for discovery, built from the
    tenant's own real search_scope_level/city/operating_countries
    (company_geo_profile.py) - the actual text a search query is biased
    toward, not a schema change. `override` narrows ("Amman" - a city
    within it) or widens ("Middle East") the default for one call/run
    without touching the tenant's stored setting.

    Two real bugs this fixes over the previous bare-country_code version:
    - GLOBAL scope now returns "" (no geographic bias at all) instead of
      still appending the tenant's primary country - a tenant who
      explicitly chose worldwide discovery was previously getting every
      query silently narrowed to one country anyway.
    - A REGIONAL tenant (operating_countries holds more than one code -
      "selected countries") previously only ever got their single primary
      country_code in the query text, so "regional" scope had zero actual
      effect on what discovery searched for. Every operating country is
      now included.
    - CITY scope now actually uses the tenant's stored city name when one
      is on file, instead of falling back to the country regardless of
      scope level - a real fix for "local: city" actually biasing queries
      toward the city, not just the whole country.

    Country codes are resolved to real, human-readable names
    (iso_countries.py) since a bare 2-letter code ("JO") appended to a
    free-text search query is close to useless as a geographic signal to
    a real search engine - "Jordan" is not.
    """
    if override:
        return override
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT country_code, operating_countries, city, search_scope_level "
            "FROM companies WHERE tenant_id = %s;",
            (tenant_id,),
        )
        row = cursor.fetchone()
    if not row:
        return ""
    country_code, operating_countries, city, search_scope_level = row

    from src.market_scraper.company_target_markets import (
        extract_country_codes, extract_region_names, get_tenant_target_markets, has_global_target_market,
    )
    tenant_target_markets = get_tenant_target_markets(conn, tenant_id)

    # A declared GLOBAL Target Market (company_target_markets.py) is its
    # own real, human-declared "compete everywhere" fact, independent of
    # search_scope_level - honored here exactly like search_scope_level=
    # GLOBAL already is: no geographic bias text at all. Never the
    # reverse (a GLOBAL search scope does NOT get written back as a
    # declared target market - the two stay separately stored facts).
    if search_scope_level == "GLOBAL" or has_global_target_market(tenant_target_markets):
        return ""
    if search_scope_level == "CITY" and city:
        return city

    from src.market_scraper.iso_countries import country_name
    codes = list(operating_countries) if operating_countries else ([country_code] if country_code else [])
    # Explicit commercial Target Markets - real, human-declared "search
    # here too" signal, appended on top of (never instead of)
    # operating_countries. Never inferred: a tenant with no declared
    # target markets adds nothing here, same as before this existed.
    # COUNTRY-type entries resolve to a real country name; REGION-type
    # entries are already free text a search engine can use directly
    # (e.g. "Middle East") - the one place that free text is actually
    # used (see company_target_markets.py's own docstring for why
    # classification never uses it).
    codes.extend(extract_country_codes(tenant_target_markets))
    names = [country_name(code) for code in codes if code]
    names.extend(extract_region_names(tenant_target_markets))
    return " OR ".join(dict.fromkeys(names))  # de-duped, order preserved


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
