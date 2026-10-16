"""
CEOPRO AI - Hierarchical Business-Category Taxonomy.

sector_detection.py's verticals are deliberately coarse ("food_beverage"
covers a burger joint and a donut shop alike), which is exactly why a
burger restaurant used to be shown a donut store as a "competitor". This
module adds the missing depth: every category is a PATH from broad to
specific, e.g.

    ("food", "snacks", "burger")      ("food", "desserts", "donuts")
    ("electronics", "components", "microcontrollers")

and category_similarity() scores how close two paths are. Two businesses
that only share the top level (food vs. food) are NOT competitors on that
basis alone; sharing the middle level (both food/snacks) is.

Evidence order (most to least reliable), mirrored by categorize():
1. Google Places `types` (a structured field the business itself maintains).
2. Keyword match against free text (a competitor's name/title, or a
   tenant's product names).
Nothing here is a trained model - it is a transparent keyword/type table,
so every categorization can be explained and corrected by editing one
entry. An unrecognized business returns None, never a guessed category.
"""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

CategoryPath = Tuple[str, ...]

# Both-sides-known similarity at or above this means "plausible rival";
# below it, the two businesses sit in different segments (food/snacks vs.
# food/desserts) and should not be listed as each other's competitors.
MIN_COMPETING_SIMILARITY = 0.5
# Same-segment bar (burger vs. pizza: both food/snacks) for the top tier.
STRONG_COMPETING_SIMILARITY = 0.66
# Returned when one side is only known at a broader level than the other
# (e.g. a generic "restaurant" vs. a burger place): same broad domain,
# can't tell more. Passes the competing bar, never the strong one.
BROADER_PATH_SIMILARITY = 0.5

# leaf label -> (path, keywords, google place types). Keywords are matched
# on word boundaries, lowercase; multi-word entries match as phrases.
_LEAVES: Dict[str, Tuple[CategoryPath, List[str], List[str]]] = {
    "burger": (("food", "snacks", "burger"),
               ["burger", "burgers", "hamburger", "cheeseburger", "برجر", "همبرغر"],
               ["hamburger_restaurant"]),
    "pizza": (("food", "snacks", "pizza"),
              ["pizza", "pizzeria", "بيتزا"],
              ["pizza_restaurant"]),
    "sandwich": (("food", "snacks", "sandwich"),
                 ["sandwich", "sandwiches", "shawarma", "falafel", "wrap", "wraps", "شاورما", "فلافل", "ساندويش"],
                 ["sandwich_shop"]),
    "fried_chicken": (("food", "snacks", "fried_chicken"),
                      ["fried chicken", "broasted", "chicken wings", "nuggets", "بروستد"],
                      []),
    "grill": (("food", "meals", "grill"),
              ["grill", "steakhouse", "steak", "bbq", "barbecue", "kebab", "mansaf", "مشاوي", "مندي"],
              ["steak_house", "barbecue_restaurant"]),
    "restaurant_other": (("food",),
                         ["restaurant", "diner", "bistro", "kitchen", "مطعم"],
                         ["restaurant", "meal_takeaway", "meal_delivery"]),
    "donuts": (("food", "desserts", "donuts"),
               ["donut", "donuts", "doughnut", "doughnuts", "دونات"],
               ["donut_shop"]),
    "ice_cream": (("food", "desserts", "ice_cream"),
                  ["ice cream", "gelato", "frozen yogurt", "بوظة", "آيس كريم"],
                  ["ice_cream_shop"]),
    "sweets": (("food", "desserts", "sweets"),
               ["cake", "cakes", "pastry", "patisserie", "dessert", "desserts", "sweets", "chocolate", "knafeh", "kunafa",
                "حلويات", "كنافة", "كيك"],
               ["dessert_shop", "dessert_restaurant", "confectionery", "chocolate_shop"]),
    # A bakery sells bread AND pastry/sweets/cakes, and sweets shops sell baked
    # goods - they compete, so they share a segment with the desserts leaves.
    "bakery": (("food", "desserts", "bakery"),
               ["bakery", "bread", "manakish", "مخبز", "فرن"],
               ["bakery"]),
    "coffee": (("food", "beverages", "coffee"),
               ["coffee", "cafe", "café", "espresso", "roastery", "قهوة", "كافيه"],
               ["cafe", "coffee_shop"]),
    "juice": (("food", "beverages", "juice"),
              ["juice", "smoothie", "smoothies", "عصير"],
              ["juice_shop"]),
    "grocery": (("grocery", "supermarket"),
                ["supermarket", "grocery", "minimart", "hypermarket", "سوبرماركت", "بقالة"],
                ["supermarket", "grocery_store", "convenience_store"]),
    "pharmacy": (("health", "pharmacy"),
                 ["pharmacy", "drugstore", "صيدلية"],
                 ["pharmacy", "drugstore"]),
    "components": (("electronics", "components", "parts"),
                   ["arduino", "raspberry", "resistor", "capacitor", "microcontroller", "breadboard", "diode",
                    "transistor", "esp32", "esp8266", "stepper", "servo", "relay", "pcb", "sensor", "solder"],
                   []),
    "accessories": (("electronics", "accessories", "cables_chargers"),
                    ["cable", "charger", "adapter", "usb", "headphones", "earbuds", "power bank", "case", "battery"],
                    []),
    "devices": (("electronics", "devices", "consumer"),
                ["phone", "smartphone", "laptop", "tablet", "television", "tv", "camera", "console", "smartwatch"],
                ["mobile_phone_store", "computer_store"]),
    # Store-level Places types are BROAD on purpose: an "electronics store"
    # sells components and gadgets alike, so a narrow path here would wrongly
    # rule it out against a tenant that sells either.
    "electronics_general": (("electronics",), ["electronics", "electronic", "إلكترونيات"], ["electronics_store"]),
    "apparel_general": (("apparel",), ["apparel", "clothing", "boutique", "fashion"], ["clothing_store"]),
    "home_general": (("home",), [], ["furniture_store", "home_goods_store"]),
    "clothing": (("apparel", "clothing", "general"),
                 ["shirt", "dress", "jacket", "jeans", "pants", "skirt", "coat", "sweater"],
                 []),
    "footwear": (("apparel", "footwear", "shoes"),
                 ["shoe", "shoes", "sneaker", "sneakers", "boots", "sandals"],
                 ["shoe_store"]),
    "furniture": (("home", "furniture", "general"),
                  ["chair", "table", "sofa", "mattress", "cabinet", "desk", "furniture", "shelf"],
                  []),
    "decor": (("home", "decor", "general"),
              ["lamp", "rug", "curtain", "mirror", "cushion", "decor"],
              []),
    "salon": (("beauty", "salon"),
              ["salon", "hairdresser", "barber", "barbershop", "hair", "nails", "manicure", "صالون", "حلاق"],
              ["hair_care", "beauty_salon", "barber_shop", "nail_salon"]),
    "spa": (("beauty", "spa"), ["spa", "massage", "wellness", "سبا"], ["spa"]),
    "cosmetics": (("beauty", "cosmetics"),
                  ["cosmetics", "makeup", "perfume", "fragrance", "skincare", "مكياج", "عطور"],
                  ["cosmetics_store"]),
    "gym": (("fitness", "gym"), ["gym", "fitness", "crossfit", "yoga", "pilates", "نادي"], ["gym", "fitness_center"]),
    "auto_parts": (("auto", "parts"),
                   ["auto parts", "car parts", "spare parts", "tires", "tyres", "قطع غيار"],
                   ["car_parts_store"]),
    "auto_repair": (("auto", "repair"),
                    ["garage", "mechanic", "car repair", "car wash", "ورشة"],
                    ["car_repair", "car_wash"]),
    "auto_sales": (("auto", "sales"), ["car dealer", "dealership", "showroom", "معرض سيارات"], ["car_dealer"]),
    "books": (("retail", "books_stationery"),
              ["book", "books", "bookstore", "bookshop", "stationery", "مكتبة", "قرطاسية"],
              ["book_store"]),
    "toys": (("retail", "toys"), ["toy", "toys", "lego", "ألعاب"], ["toy_store"]),
    "pets": (("retail", "pets"), ["pet", "pets", "petshop", "aquarium", "حيوانات"], ["pet_store"]),
    "jewelry": (("retail", "jewelry"),
                ["jewelry", "jewellery", "gold", "necklace", "bracelet", "مجوهرات", "ذهب"],
                ["jewelry_store"]),
    "gifts_flowers": (("retail", "gifts_flowers"),
                      ["florist", "flowers", "bouquet", "gift", "gifts", "ورد", "هدايا"],
                      ["florist", "gift_shop"]),
}

# What to type into a Places/web search to FIND businesses of a category -
# discovery searches for the tenant's actual segment ("burger restaurant"),
# not its whole vertical ("restaurant OR cafe"), so irrelevant businesses
# are never found in the first place instead of being found then excluded.
_SEARCH_LABELS: Dict[CategoryPath, str] = {
    ("food", "snacks", "burger"): "burger restaurant",
    ("food", "snacks", "pizza"): "pizza restaurant",
    ("food", "snacks", "sandwich"): "shawarma OR sandwich shop",
    ("food", "snacks", "fried_chicken"): "fried chicken restaurant",
    ("food", "meals", "grill"): "grill restaurant",
    ("food",): "restaurant",
    ("food", "desserts", "donuts"): "donut shop",
    ("food", "desserts", "ice_cream"): "ice cream shop",
    ("food", "desserts", "sweets"): "dessert shop",
    ("food", "desserts", "bakery"): "bakery",
    ("food", "beverages", "coffee"): "coffee shop",
    ("food", "beverages", "juice"): "juice bar",
    ("grocery", "supermarket"): "supermarket",
    ("health", "pharmacy"): "pharmacy",
    ("electronics", "components", "parts"): "electronic components store",
    ("electronics", "accessories", "cables_chargers"): "mobile accessories store",
    ("electronics", "devices", "consumer"): "electronics store",
    ("electronics",): "electronics store",
    ("apparel", "clothing", "general"): "clothing store",
    ("apparel", "footwear", "shoes"): "shoe store",
    ("apparel",): "clothing store",
    ("home", "furniture", "general"): "furniture store",
    ("home", "decor", "general"): "home decor store",
    ("home",): "home goods store",
    ("beauty", "salon"): "hair salon",
    ("beauty", "spa"): "spa",
    ("beauty", "cosmetics"): "cosmetics store",
    ("fitness", "gym"): "gym",
    ("auto", "parts"): "auto parts store",
    ("auto", "repair"): "car repair garage",
    ("auto", "sales"): "car dealership",
    ("retail", "books_stationery"): "bookstore",
    ("retail", "toys"): "toy store",
    ("retail", "pets"): "pet store",
    ("retail", "jewelry"): "jewelry store",
    ("retail", "gifts_flowers"): "florist OR gift shop",
}

_WORD_RE = re.compile(r"[\w'’]+", re.UNICODE)

_TYPE_TO_PATH: Dict[str, CategoryPath] = {
    t: path for path, _, types in _LEAVES.values() for t in types
}
# Google's generic place types carry no segment information - using them
# would only say "food", so they only count when nothing more specific
# is present (see categorize()).
_GENERIC_TYPES = {"restaurant", "meal_takeaway", "meal_delivery", "food", "store", "point_of_interest", "establishment"}

_PHRASES: List[Tuple[str, CategoryPath]] = sorted(
    ((kw, path) for path, kws, _ in _LEAVES.values() for kw in kws),
    key=lambda item: -len(item[0]),  # longest phrase first: "ice cream" before "cream"
)


@dataclass(frozen=True)
class Categorization:
    path: CategoryPath
    source: str  # "places_type" | "keyword"
    evidence: str  # the type/keyword that decided it, for audit

    @property
    def label(self) -> str:
        return " > ".join(part.replace("_", " ") for part in self.path)


def _tokens_text(text: str) -> str:
    return " " + " ".join(m.group(0).lower() for m in _WORD_RE.finditer(text or "")) + " "


def _keyword_hits(text: str) -> Counter:
    haystack = _tokens_text(text)
    hits: Counter = Counter()
    for kw, path in _PHRASES:
        if f" {kw.lower()} " in haystack:
            hits[path] += 1
    return hits


def categorize(name: Optional[str] = None, place_types: Optional[Iterable[str]] = None) -> Optional[Categorization]:
    """Best single category for ONE business (a competitor). Specific Places
    types win, then name keywords, then a generic Places type as a last
    resort ("restaurant" -> just "food": a broad domain, no segment). None when nothing
    matches - never a guess."""
    types = [t for t in (place_types or []) if t]
    specific = [t for t in types if t in _TYPE_TO_PATH and t not in _GENERIC_TYPES]
    if specific:
        best = max(specific, key=lambda t: len(_TYPE_TO_PATH[t]))  # deepest path wins
        return Categorization(_TYPE_TO_PATH[best], "places_type", best)

    hits = _keyword_hits(name or "")
    if hits:
        # Prefer the most specific (deepest) path; ties broken by hit count.
        path, _ = max(hits.items(), key=lambda item: (item[1], len(item[0])))
        evidence = next(kw for kw, p in _PHRASES if p == path and f" {kw.lower()} " in _tokens_text(name or ""))
        return Categorization(path, "keyword", evidence)

    for t in types:
        if t in _TYPE_TO_PATH:
            return Categorization(_TYPE_TO_PATH[t], "places_type", t)
    return None


def categorize_catalog(
    product_names: Sequence[str], business_type: Optional[str] = None, min_share: float = 0.25, max_paths: int = 3,
) -> List[CategoryPath]:
    """The categories a TENANT operates in, derived from its own product
    names (plus companies.business_type when set). A tenant can span more
    than one segment (a cafe that sells burgers and desserts), so this
    returns every path holding at least `min_share` of all keyword hits,
    most frequent first. [] when the catalog gives no signal."""
    hits: Counter = Counter()
    for name in product_names:
        hits.update(_keyword_hits(name))
    if business_type:
        hits.update({path: 2 * n for path, n in _keyword_hits(business_type).items()})
    # A generic path ("food", from the word "restaurant") says nothing the
    # specific one ("food > snacks > burger") doesn't already say better, and
    # kept alongside it would make every other food business look compatible.
    for path in list(hits):
        if any(other != path and other[:len(path)] == path for other in hits):
            del hits[path]
    total = sum(hits.values())
    if total == 0:
        return []
    return [path for path, n in hits.most_common(max_paths) if n / total >= min_share]


def category_similarity(a: Optional[CategoryPath], b: Optional[CategoryPath]) -> Optional[float]:
    """0.0-1.0 closeness of two category paths; None if either is unknown.

    - different top level (food vs. electronics): 0.0
    - same leaf: 1.0
    - same segment, different leaf (burger vs. pizza): shared/depth, e.g. 0.67
    - same top level only (burger vs. donuts): 0.33 - below the competing bar
    - one path just a broader form of the other: BROADER_PATH_SIMILARITY
    """
    if not a or not b:
        return None
    shared = 0
    for x, y in zip(a, b):
        if x != y:
            break
        shared += 1
    if shared == 0:
        return 0.0
    if a == b:
        return 1.0
    if shared == min(len(a), len(b)):
        return BROADER_PATH_SIMILARITY
    return round(shared / max(len(a), len(b)), 2)


def best_similarity(tenant_paths: Sequence[CategoryPath], competitor_path: Optional[CategoryPath]) -> Optional[float]:
    """A multi-category tenant competes wherever ANY of its categories
    lines up, so take the best match. None if either side is unknown."""
    scores = [s for s in (category_similarity(tp, competitor_path) for tp in tenant_paths) if s is not None]
    return max(scores) if scores else None


def search_keyword_for_path(path: Optional[CategoryPath]) -> Optional[str]:
    """The search phrase that finds businesses of this category, falling back
    to the nearest broader category's phrase; None for an unknown path."""
    path = tuple(path or ())
    while path:
        if path in _SEARCH_LABELS:
            return _SEARCH_LABELS[path]
        path = path[:-1]
    return None
