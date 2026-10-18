"""
Industry taxonomy for competitor discovery.

One table describes every supported industry: how OpenStreetMap tags such
businesses, which Google Places types cover them, and which words people
search for them with (English and Arabic). The discovery pipeline reads this
table and nothing else about industries, so a restaurant, a pharmacy and a
hotel go through exactly the same code. Adding an industry means adding a row.

OSM tags follow https://wiki.openstreetmap.org/wiki/Map_features; Google
types follow the Places API (New) type table.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.market_scraper.sector_detection import detect_vertical


@dataclass(frozen=True)
class Industry:
    key: str
    label_en: str
    label_ar: str
    osm_tags: Tuple[Tuple[str, str], ...]          # (key, value) pairs, any match
    google_types: Tuple[str, ...]                  # Places API (New) includedTypes
    keywords_en: Tuple[str, ...]                   # search phrases
    keywords_ar: Tuple[str, ...] = ()
    local: bool = True                             # competitors are mostly nearby shops
    default_radius_km: float = 5.0
    related: Tuple[str, ...] = field(default=())   # neighbouring industries (weaker match)


INDUSTRIES: Dict[str, Industry] = {i.key: i for i in [
    Industry("restaurant", "Restaurant", "مطعم",
             (("amenity", "restaurant"), ("amenity", "fast_food"), ("amenity", "food_court")),
             ("restaurant", "fast_food_restaurant", "meal_takeaway", "meal_delivery"),
             ("restaurant", "food delivery"), ("مطعم", "مطاعم"), related=("cafe", "bakery")),
    Industry("cafe", "Café / coffee shop", "مقهى",
             (("amenity", "cafe"), ("shop", "coffee"), ("shop", "tea")),
             ("cafe", "coffee_shop", "tea_house"),
             ("coffee shop", "cafe"), ("مقهى", "كافيه", "قهوة"), related=("restaurant", "bakery")),
    Industry("bakery", "Bakery & sweets", "مخبز وحلويات",
             (("shop", "bakery"), ("shop", "pastry"), ("shop", "confectionery")),
             ("bakery", "confectionery_store", "dessert_shop"),
             ("bakery", "sweets shop"), ("مخبز", "حلويات"), related=("cafe",)),
    Industry("hotel", "Hotel & accommodation", "فندق وإقامة",
             (("tourism", "hotel"), ("tourism", "guest_house"), ("tourism", "hostel"), ("tourism", "apartment"), ("tourism", "motel")),
             ("hotel", "lodging", "resort_hotel", "guest_house", "hostel", "motel", "bed_and_breakfast"),
             ("hotel", "guest house"), ("فندق", "فنادق", "شقق فندقية"), default_radius_km=10.0),
    Industry("supermarket", "Supermarket & grocery", "سوبرماركت وبقالة",
             (("shop", "supermarket"), ("shop", "convenience"), ("shop", "grocery"), ("shop", "greengrocer"), ("shop", "deli")),
             ("supermarket", "grocery_store", "convenience_store", "food_store"),
             ("supermarket", "grocery store"), ("سوبرماركت", "بقالة", "مواد غذائية"), related=("bakery",)),
    Industry("pharmacy", "Pharmacy", "صيدلية",
             (("amenity", "pharmacy"), ("healthcare", "pharmacy"), ("shop", "chemist")),
             ("pharmacy", "drugstore"),
             ("pharmacy", "drugstore"), ("صيدلية", "صيدليات"), related=("cosmetics",)),
    Industry("cosmetics", "Cosmetics & perfume", "مستحضرات تجميل وعطور",
             (("shop", "cosmetics"), ("shop", "perfumery"), ("shop", "beauty")),
             ("beauty_salon", "store"),
             ("cosmetics store", "perfume shop", "beauty products"), ("مستحضرات تجميل", "عطور", "عطورات"), related=("pharmacy", "salon")),
    Industry("salon", "Salon & spa", "صالون وسبا",
             (("shop", "hairdresser"), ("shop", "beauty"), ("leisure", "spa"), ("amenity", "spa")),
             ("beauty_salon", "hair_salon", "spa", "nail_salon", "barber_shop"),
             ("beauty salon", "spa", "barber"), ("صالون", "سبا", "حلاق"), related=("cosmetics",)),
    Industry("electronics", "Electronics & phones", "إلكترونيات وهواتف",
             (("shop", "electronics"), ("shop", "mobile_phone"), ("shop", "computer"), ("shop", "hifi"), ("shop", "appliance")),
             ("electronics_store", "cell_phone_store"),
             ("electronics store", "mobile phone shop", "computer store"), ("إلكترونيات", "موبايلات", "هواتف", "كمبيوتر"), default_radius_km=10.0),
    Industry("fashion", "Fashion & clothing", "أزياء وملابس",
             (("shop", "clothes"), ("shop", "boutique"), ("shop", "fashion"), ("shop", "shoes"), ("shop", "bag"), ("shop", "fashion_accessories")),
             ("clothing_store", "shoe_store", "store"),
             ("clothing store", "fashion boutique", "shoe store"), ("ملابس", "أزياء", "بوتيك", "أحذية"), default_radius_km=8.0),
    Industry("jewelry", "Jewelry & watches", "مجوهرات وساعات",
             (("shop", "jewelry"), ("shop", "watches")),
             ("jewelry_store",),
             ("jewelry store", "gold shop", "watch store"), ("مجوهرات", "ذهب", "ساعات"), default_radius_km=8.0),
    Industry("furniture", "Furniture & home", "أثاث ومستلزمات منزلية",
             (("shop", "furniture"), ("shop", "interior_decoration"), ("shop", "houseware"), ("shop", "bed"), ("shop", "kitchen")),
             ("furniture_store", "home_goods_store"),
             ("furniture store", "home decor"), ("أثاث", "مفروشات", "ديكور"), default_radius_km=15.0),
    Industry("hardware", "Hardware & building supplies", "عدد ومواد بناء",
             (("shop", "hardware"), ("shop", "doityourself"), ("shop", "trade"), ("shop", "paint")),
             ("hardware_store", "home_improvement_store"),
             ("hardware store", "building supplies"), ("عدد صناعية", "مواد بناء", "أدوات"), default_radius_km=15.0),
    Industry("books_stationery", "Books & stationery", "كتب وقرطاسية",
             (("shop", "books"), ("shop", "stationery")),
             ("book_store",),
             ("bookstore", "stationery shop"), ("مكتبة", "قرطاسية")),
    Industry("sports", "Sports & outdoor", "رياضة",
             (("shop", "sports"), ("shop", "outdoor"), ("shop", "bicycle")),
             ("sporting_goods_store",),
             ("sports store",), ("مستلزمات رياضية",), default_radius_km=10.0),
    Industry("toys_baby", "Toys & baby", "ألعاب ومستلزمات أطفال",
             (("shop", "toys"), ("shop", "baby_goods")),
             ("store",),
             ("toy store", "baby shop"), ("ألعاب", "مستلزمات أطفال"), default_radius_km=10.0),
    Industry("optician", "Optician", "نظارات وبصريات",
             (("shop", "optician"), ("healthcare", "optometrist")),
             ("store",),
             ("optician", "eyewear store"), ("نظارات", "بصريات")),
    Industry("florist", "Flowers & gifts", "زهور وهدايا",
             (("shop", "florist"), ("shop", "gift")),
             ("florist", "gift_shop"),
             ("florist", "gift shop"), ("ورود", "زهور", "هدايا")),
    Industry("pet", "Pet shop & vet", "حيوانات أليفة",
             (("shop", "pet"), ("amenity", "veterinary")),
             ("pet_store", "veterinary_care"),
             ("pet shop", "veterinary clinic"), ("مستلزمات حيوانات", "بيطري")),
    Industry("clinic", "Clinic & medical", "عيادة وخدمات طبية",
             (("amenity", "clinic"), ("amenity", "doctors"), ("amenity", "dentist"), ("healthcare", "clinic"), ("healthcare", "dentist")),
             ("doctor", "dentist", "medical_clinic", "dental_clinic", "medical_lab"),
             ("clinic", "dentist", "medical center"), ("عيادة", "طبيب أسنان", "مركز طبي"), related=("pharmacy",)),
    Industry("fitness", "Gym & fitness", "نوادي رياضية",
             (("leisure", "fitness_centre"), ("leisure", "sports_centre")),
             ("gym", "fitness_center"),
             ("gym", "fitness center"), ("نادي رياضي", "جيم")),
    Industry("automotive", "Car services & parts", "خدمات وقطع سيارات",
             (("shop", "car_repair"), ("shop", "car_parts"), ("shop", "tyres"), ("amenity", "car_wash"), ("shop", "car")),
             ("car_repair", "car_wash", "car_dealer", "auto_parts_store"),
             ("car repair", "auto parts", "car wash"), ("صيانة سيارات", "قطع سيارات", "غسيل سيارات"), default_radius_km=10.0),
    Industry("education", "Education & training", "تعليم وتدريب",
             (("amenity", "school"), ("amenity", "language_school"), ("amenity", "training"), ("amenity", "college"), ("amenity", "kindergarten")),
             ("school", "preschool", "primary_school", "secondary_school"),
             ("training center", "language school"), ("مركز تدريب", "معهد", "مدرسة"), default_radius_km=10.0),
    Industry("professional_services", "Professional services", "خدمات مهنية",
             (("office", "company"), ("office", "consulting"), ("office", "accountant"), ("office", "lawyer"), ("office", "it"), ("office", "estate_agent")),
             ("accounting", "lawyer", "real_estate_agency", "insurance_agency"),
             ("consulting company", "agency"), ("شركة استشارات", "مكتب"), local=False, default_radius_km=25.0),
    Industry("online_retail", "Online store", "متجر إلكتروني",
             (), (), ("online store",), ("متجر إلكتروني",), local=False, default_radius_km=0.0),
    Industry("general_retail", "Retail shop", "متجر تجزئة",
             (("shop", "variety_store"), ("shop", "department_store"), ("shop", "general"), ("shop", "mall")),
             ("store", "department_store", "discount_store"),
             ("store",), ("متجر",)),
]}

# The older sector_detection verticals (inferred from product names) -> the
# closest discovery industry, used when a company hasn't picked one.
_VERTICAL_TO_INDUSTRY = {
    "electronics_hobbyist": "electronics", "food_beverage": "restaurant", "apparel_fashion": "fashion",
    "home_furniture": "furniture", "pharmacy": "pharmacy", "hospitality": "hotel",
    "beauty_personal_care": "cosmetics", "grocery": "supermarket", "professional_services": "professional_services",
    "industrial_manufacturing": "hardware", "automotive": "automotive", "general_retail": "general_retail",
}

# Free-text business types people type at sign-up -> industry key.
_TYPE_WORDS = [
    ("supermarket", ("supermarket", "grocery", "minimarket", "food retail", "سوبرماركت", "بقالة", "مواد غذائية")),
    ("restaurant", ("restaurant", "kitchen", "grill", "diner", "eatery", "مطعم", "مطاعم")),
    ("cafe", ("cafe", "café", "coffee", "مقهى", "كافيه", "قهوة")),
    ("bakery", ("bakery", "sweets", "pastry", "dessert", "مخبز", "حلويات")),
    ("hotel", ("hotel", "resort", "hostel", "guest", "lodging", "فندق", "فنادق", "منتجع")),
    ("pharmacy", ("pharmacy", "drugstore", "chemist", "صيدلية")),
    ("cosmetics", ("cosmetic", "perfume", "beauty products", "makeup", "تجميل", "عطور")),
    ("salon", ("salon", "spa", "barber", "hair", "nail", "صالون", "حلاق")),
    ("electronics", ("electronic", "phone", "mobile", "computer", "gadget", "إلكترون", "موبايل", "هواتف")),
    ("fashion", ("fashion", "cloth", "apparel", "boutique", "shoe", "أزياء", "ملابس", "أحذية")),
    ("jewelry", ("jewel", "gold", "watch", "مجوهرات", "ذهب")),
    ("furniture", ("furniture", "home decor", "interior", "أثاث", "مفروشات")),
    ("hardware", ("hardware", "building", "construction", "tools", "مواد بناء", "عدد")),
    ("books_stationery", ("book", "stationery", "مكتبة", "قرطاسية")),
    ("sports", ("sport", "outdoor", "bicycle", "رياض")),
    ("toys_baby", ("toy", "baby", "ألعاب", "أطفال")),
    ("optician", ("optic", "eyewear", "glasses", "نظارات")),
    ("florist", ("flower", "florist", "gift", "زهور", "ورود", "هدايا")),
    ("pet", ("pet", "veterin", "حيوانات", "بيطر")),
    ("clinic", ("clinic", "medical", "dental", "dentist", "doctor", "عيادة", "طبي", "أسنان")),
    ("fitness", ("gym", "fitness", "جيم", "نادي")),
    ("automotive", ("car", "auto", "garage", "tyre", "tire", "سيارات")),
    ("education", ("school", "training", "academy", "course", "تعليم", "تدريب", "معهد")),
    ("professional_services", ("consult", "conseil", "cabinet", "b2b", "agency", "law", "account", "marketing agency", "استشار", "محاسب", "محام")),
    ("online_retail", ("online", "e-commerce", "ecommerce", "متجر إلكتروني")),
    ("general_retail", ("retail", "shop", "store", "متجر", "محل")),
]


# A business type outside the table ("car rental", "law firm", "مكتب سفريات")
# is searched by its own words - map listings whose name contains them, web
# search and company databases for the phrase - never as some other
# industry. Its key is CUSTOM; its label is the owner's own description.
CUSTOM = "custom"
_CUSTOM_BASE = Industry(CUSTOM, "Your business type", "نوع عملك", (), (), (), default_radius_km=10.0)


def custom(business_type: str) -> Industry:
    text = re.sub(r"\s+", " ", business_type or "").strip()[:80]
    return Industry(CUSTOM, text or _CUSTOM_BASE.label_en, text or _CUSTOM_BASE.label_ar, (), (),
                    (text,) if text else (), default_radius_km=10.0)


def get(key: Optional[str]) -> Optional[Industry]:
    return INDUSTRIES.get(key or "") or (_CUSTOM_BASE if key == CUSTOM else None)


def trade_words() -> set:
    """Every industry's own name and search words, lower-cased - a business
    "named" only one of these is a map placeholder, not a competitor."""
    words = set()
    for industry in INDUSTRIES.values():
        for word in (industry.label_en, industry.label_ar, *industry.keywords_en, *industry.keywords_ar):
            words.add(word.lower().strip())
    return words


def choices() -> List[dict]:
    """The industry picker's options."""
    return [{"key": i.key, "label": {"en": i.label_en, "ar": i.label_ar}} for i in INDUSTRIES.values()]


def _starts_a_word(word: str, text: str) -> bool:
    """The word at the start of a word of the text: "pharmac" matches
    "Pharmacy", "consult" "consulting". Words of three letters or fewer must
    be the whole word (or its plural), so "car" doesn't match "Cardiology"
    and "law" doesn't match "Lawn care". An Arabic word may carry a leading
    ال (the) or و/ب/ل."""
    end = r"(?:s|es)?(?![\w\u0600-\u06ff])" if len(word) <= 3 else ""
    return re.search(r"(?:^|[^\w\u0600-\u06ff])(?:ال|وال|بال|لل)?" + re.escape(word) + end, text) is not None


def resolve(industry_key: Optional[str], business_type: Optional[str], product_names: List[str]) -> Tuple[Industry, str]:
    """The company's industry and how it was decided: chosen explicitly,
    read from its business type, or inferred from its products."""
    if industry_key in INDUSTRIES:
        return INDUSTRIES[industry_key], "chosen"
    text = (business_type or "").lower()
    if text:
        for key, words in _TYPE_WORDS:
            if key == "general_retail" and product_names:
                continue  # "shop"/"store" alone: the products say what kind
            if any(_starts_a_word(word, text) for word in words):
                return INDUSTRIES[key], "business_type"
    # The owner's own description says more than a guess from product names
    # ("Software company" selling an "Accounting app" is not an accountant),
    # unless it has no word that names a trade ("My shop").
    if _names_a_trade(text):
        return custom(business_type), "business_type"
    if product_names:
        vertical = detect_vertical(product_names, business_type).vertical
        return INDUSTRIES[_VERTICAL_TO_INDUSTRY.get(vertical, "general_retail")], "products"
    return INDUSTRIES["general_retail"], "default"


_NOT_A_TRADE = {"my", "our", "the", "and", "a", "an", "shop", "store", "business", "company", "co", "llc", "ltd",
                "group", "online", "local", "small", "family", "new", "best", "متجر", "محل", "شركة", "شركه", "مؤسسة",
                "مؤسسه", "عمل", "مشروع", "صغير", "خاص"}


def _names_a_trade(text: str) -> bool:
    words = [w for w in re.split(r"[^\w\u0600-\u06ff]+", (text or "").lower()) if len(w) >= 3]
    return any(w not in _NOT_A_TRADE for w in words)


def classify_tags(tags: Dict[str, str]) -> Optional[str]:
    """OSM tags -> industry key (first exact tag match)."""
    for industry in INDUSTRIES.values():
        for key, value in industry.osm_tags:
            if tags.get(key) == value:
                return industry.key
    return None


def classify_google_types(types: List[str]) -> Optional[str]:
    """Google Places types -> the most specific industry key."""
    best, best_score = None, 0
    type_set = set(types or [])
    for industry in INDUSTRIES.values():
        specific = [t for t in industry.google_types if t not in ("store",)]
        score = len(type_set.intersection(specific))
        if score > best_score:
            best, best_score = industry.key, score
    return best
