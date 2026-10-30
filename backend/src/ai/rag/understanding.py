"""
What a question asks for, and what it is about.

Two things are read from every question, in English and Arabic (including
everyday Levantine, Gulf and Egyptian wording):

- intents: which kinds of evidence the answer needs - the company's own
  records (sales, costs, stock, ...), its documents, or outside research
  (customer preferences, products and sellers, the market, regulations,
  trade and customs, landed cost);
- slots: the specifics - products, countries and trade route, period,
  quantities, amounts with their currency, rates, HS code, Incoterm and
  any link the user pasted.

A follow-up ("and for 500 units?", "طيب وفي السعودية؟") keeps the previous
question's intents and slots and changes only what the new message
states, so the right records and calculations are used without the user
repeating everything. The resulting state is stored with the conversation.

Everything here is deterministic pattern matching: no model call, nothing
inferred that the text does not say.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from src.ai.extraction.numerals import to_ascii_digits
from src.ai.rag import periods as _periods

# --- intents -----------------------------------------------------------------

SALES, FINANCIALS, PRODUCTS, PRICING, INVENTORY, FORECAST = "sales", "financials", "products", "pricing", "inventory", "forecast"
MARKETING, COMPETITORS, REVIEWS, DOCUMENTS = "marketing", "competitors", "reviews", "documents"
COMPANY = "company"
CUSTOMER_PREFERENCE, PRODUCT_RESEARCH, MARKET_RESEARCH = "customer_preference", "product_research", "market_research"
REGULATION, TRADE, LANDED_COST, ADVICE = "regulation", "trade", "landed_cost", "advice"

EXTERNAL_INTENTS = frozenset({CUSTOMER_PREFERENCE, PRODUCT_RESEARCH, MARKET_RESEARCH, REGULATION, TRADE, LANDED_COST})

_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    SALES: ("sale", "sold", "sell", "revenue", "income", "turnover", "invoice", "orders", "selling",
            "earned", "earnings", "takings", "how much did we make", "how much did i make",
            "مبيع", "بعت", "بعنا", "بيعنا", "باع", "بيع", "ايراد", "إيراد", "دخل", "فاتور", "فواتير", "طلبات"),
    FINANCIALS: ("profit", "margin", "cost", "loss", "gross", "expensive to make", "break even", "break-even",
                 "ربح", "أرباح", "ارباح", "هامش", "تكلف", "تكاليف", "خسار", "كلفة"),
    PRODUCTS: ("product", "item", "catalog", "catalogue", "sku", "منتج", "صنف", "اصناف", "أصناف", "سلعة", "سلع"),
    PRICING: ("price", "pricing", "charge", "expensive", "cheap", "سعر", "أسعار", "اسعار", "تسعير", "غالي", "رخيص"),
    INVENTORY: ("stock", "inventory", "restock", "reorder", "out of", "warehouse",
                "مخزون", "مخزن", "نفاد", "نفد", "خلص", "إعادة الطلب", "اعادة الطلب"),
    FORECAST: ("forecast", "demand", "predict", "next month", "next week", "expected sales",
               "توقع", "الطلب", "تنبؤ", "الشهر الجاي", "الشهر القادم"),
    MARKETING: ("campaign", "marketing", "advert", " ad ", "ads", "promotion", "promo",
                "حملة", "حملات", "تسويق", "اعلان", "إعلان", "ترويج"),
    COMPETITORS: ("competitor", "competition", "rival", "منافس", "المنافسة"),
    REVIEWS: ("review", "rating", "feedback", "complain", "sentiment", "customers say", "customers think",
              "customer opinion", "satisf", "opinion of us", "think of us", "say about us",
              "تقييم", "مراجع", "آراء", "اراء", "شكاو", "شكوى", "رضا", "رأي الزبائن", "راي الزبائن", "رأي العملاء",
              "راي العملاء", "رايهم", "رأيهم", "انطباع"),
    DOCUMENTS: ("document", "file", "contract", "agreement", "policy", "uploaded", "pdf",
                "مستند", "ملف", "عقد", "اتفاقي", "سياسة"),
    CUSTOMER_PREFERENCE: ("why do customers", "why customers", "why people", "prefer", "choose", "rather buy",
                          "switch to", "what do customers like", "what customers like", "why do they buy",
                          "why is it popular", "why are they buying", "reject",
                          "يفضل", "بيفضل", "يفضلون", "يختار", "بيختار", "ليش الزبائن", "ليش الناس", "لماذا يفضل",
                          "لماذا يشتري", "ليش بيشتروا", "بيحبوا", "يحبون"),
    PRODUCT_RESEARCH: ("who sells", "who else sells", "where can i buy", "where to buy", "alternative", "substitute",
                       "supplier", "suppliers", "manufacturer", "distributor", "wholesale", "specification", "spec ",
                       "مين بيبيع", "مين يبيع", "من يبيع", "وين بلاقي", "أين أشتري", "اين اشتري", "بديل", "بدائل",
                       "مورد", "موردين", "مصنع", "موزع", "جملة", "مواصفات"),
    MARKET_RESEARCH: ("market", "trend", "opportunit", "expand", "expansion", "new branch", "new location", "industry",
                      "risk", "should i open", "worth opening", "segment",
                      "السوق", "سوق", "اتجاه", "فرص", "فرصة", "توسع", "فرع جديد", "موقع جديد", "قطاع", "مخاطر",
                      "مخاطرة", "أفتح", "افتح"),
    REGULATION: ("licen", "permit", "regulation", "regulat", "law", "legal", "tax", "vat", "gst", "excise",
                 "label", "standard", "certif", "registration", "requirement", "compliance", "allowed to",
                 "ترخيص", "رخصة", "تصريح", "قانون", "نظام", "ضريبة", "ضريبه", "القيمة المضافة", "ملصق", "بطاقة البيان",
                 "مواصفة", "مواصفات قياسية", "شهادة", "تسجيل", "متطلبات", "اشتراطات", "مسموح"),
    # "customs", never "custom": every question about customers would otherwise be a customs question.
    TRADE: ("import", "export", "customs", "tariff", "duty", "duties", "hs code", "hs-code", "country of origin", "of origin", "origin country", "shipping",
            "freight", "incoterm", "clearance", "ship it", "shipment", "border crossing", "port of entry",
            "via jaber", "jaber crossing", "jaber border",
            "استيراد", "استورد", "تصدير", "صدر", "جمارك", "جمرك", "تعرفة", "تعرفه", "رسوم جمركية", "شحن", "منشأ",
            "بند جمركي", "تخليص", "معبر", "عبر جابر", "ميناء"),
    # The business itself: its profile, what it sells, where it is, who runs it.
    COMPANY: ("my company", "our company", "the company", "my business", "our business", "tell me about us", "who we are", "about my shop",
              "about my store", "company profile", "business profile", "who are we", "what do we sell",
              "what does my company", "what does our company", "opening hours", "our stores", "our branches",
              "شركتي", "شركتنا", "عن الشركه", "عن شركتي", "مشروعي", "متجري", "نبذه عن", "ملف الشركه",
              "ساعات العمل", "مواعيد العمل", "فروعنا", "فروعي"),
    ADVICE: ("should i", "should we", "recommend", "advice", "what can i do", "what should", "how can i improve",
             "how do i increase", "how to increase", "how to grow",
             "شو لازم", "شو بنصح", "انصح", "أنصح", "تنصح", "نصيحة", "توصية", "ماذا أفعل", "كيف ازيد", "كيف أزيد",
             "كيف بقدر"),
}

_LANDED_COST_CUES = ("cheaper", "cheapest", "landed", "worth it", "more economical", "economical", "save", "saving",
                     "compare", "cost to import", "cost of importing", "total cost",
                     "أرخص", "ارخص", "أوفر", "اوفر", "توفير", "يستحق", "بيستاهل", "مقارنة", "قارن", "التكلفة الكلية",
                     "تكلفة الاستيراد", "كلفة الاستيراد")

# Say "landed cost" on their own: a trade question even with no other trade word.
_LANDED_COST_STRONG = ("landed cost", "landed price", "landed per", "cost landed", "التكلفه الواصله", "تكلفه واصله",
                       "الكلفه الواصله", "كلفه واصله", "سعر واصل")

# A question about the world rather than this business: answered from public
# sources even when its only topic word is a private-sounding one ("price").
_PUBLIC_CUES = ("average", "national", "official", "government", "nationwide", "country-wide", "per cubic",
                "how can i check", "how do i check", "how to check", "where can i check", "how do i find out",
                "متوسط", "معدل", "رسمي", "الحكومه", "حكومي", "وطني", "كيف اعرف", "كيف بعرف", "كيف اتحقق", "وين بلاقي")
_SELF_REFERENCE = re.compile(
    r"(?<![\w])(my|our|we|mine|ours)(?![\w])|"
    r"عندي|لدي|لدينا|عندنا|تبعي|تبعنا|خاصتي|منتجاتي|منتجي|مبيعاتي|زبائني|محلي التجاري|شركتي|متجري|مطعمي|بضاعتي")
_TOP_PRODUCT = ("top product", "top-selling", "top selling", "best seller", "best-seller", "best selling",
                "best-selling", "most sold", "top seller", "number one product",
                "اكثر منتج", "الاكثر مبيعا", "افضل منتج", "المنتج الاول", "اعلى منتج")
_ROUTE = re.compile(r"(?:\bvia|\bthrough|عبر|عن طريق)\s+((?:معبر\s+|the\s+)?[^\s,.?!؟]+(?:\s+(?:border|crossing|port))?)")

_FOLLOW_UP_CUES = ("and ", "what about", "how about", "and what", "same for", "also", "instead", "then", "why?",
                   "و", "طيب", "وماذا", "وشو", "شو عن", "ماذا عن", "وكمان", "وفي", "بدلا", "بدل", "كمان", "ليش؟", "لماذا؟")
# A short question that points back at the product just discussed ("what is its price?").
_REFERS_BACK = re.compile(
    r"(?<![\w])(it|its|it's|that|this|those|these|them|their)(?![\w])|"
    r"(?<![\w])(that|this|the same)\s+(product|item|one)(?![\w])|"
    r"(?<![\w])(سعره|سعرها|سعرهم|كميته|مخزونه|مبيعاته|مبيعاتها|هذا المنتج|هاد المنتج|نفس المنتج|هذه|هاي|هاد|هذا|منه|منها)(?![\w])|"
    # "How many did we sell?" names no product: it is the one just discussed.
    r"(?<![\w])how (many|much) (did|do|have|were|was|are|is)(?![\w])|(?<![\w])(كم بعنا|كم بعت|قديش بعنا|قديش بعت)(?![\w])")
_REFERS_BACK_MAX_WORDS = 8
# A question that points back at the period just discussed ("which product sold the most then?").
_REFERS_BACK_TIME = re.compile(
    r"(?<![\w])(then|that period|that month|that quarter|that year|that time|same period|during that|in that period)"
    r"(?![\w])|وقتها|بهاي الفتره|بهذه الفتره|بنفس الفتره|في نفس الفتره|خلال هذه الفتره|بهديك الفتره|بذلك الشهر|بهذاك الشهر")


def _norm(text: str) -> str:
    text = to_ascii_digits(text or "").lower()
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    return text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))


_KEYWORD_PATTERNS: Dict[str, "re.Pattern"] = {}


def _keyword_pattern(keyword: str) -> "re.Pattern":
    """A Latin-script keyword matches at the start of a word ("review" in "reviews", never "tax" in "syntax" or
    "sale" in "wholesale"); Arabic ones anywhere, since Arabic attaches prefixes ("بمبيعات")."""
    pattern = _KEYWORD_PATTERNS.get(keyword)
    if pattern is None:
        normalized = _norm(keyword)
        lead = "(?<![a-z])" if re.match(r"[a-z]", normalized) else ""
        pattern = _KEYWORD_PATTERNS[keyword] = re.compile(lead + re.escape(normalized))
    return pattern


def _has(text: str, keywords) -> bool:
    return any(_keyword_pattern(keyword).search(text) for keyword in keywords)


def detect_intents(text: str) -> List[str]:
    lowered = f" {_norm(text)} "
    found = [intent for intent, keywords in _KEYWORDS.items() if _has(lowered, keywords)]
    if _has(lowered, _LANDED_COST_STRONG):
        found += [intent for intent in (TRADE, LANDED_COST) if intent not in found]
    elif TRADE in found and _has(lowered, _LANDED_COST_CUES):
        found.append(LANDED_COST)
    return found


def is_public_scope(text: str, intents: List[str], slots: dict) -> bool:
    """True when the question is about the world, not this business: a public
    cue ("average", "official", "how can I check", a named country with no
    product of theirs) and no word pointing at the business itself."""
    lowered = f" {_norm(text)} "
    # A product named only in part ("olive oil") may be the world's product, not theirs: "the average retail
    # price of olive oil in Jordan" is still a public question.
    named = [p for p in slots.get("products") or [] if not p.get("partial")]
    if _SELF_REFERENCE.search(lowered) or named or slots.get("top_product"):
        return False
    if _has(lowered, _PUBLIC_CUES):
        return True
    return bool(slots.get("countries")) and bool(intents) and set(intents) <= {PRICING, PRODUCTS, FINANCIALS}


_GREETING_AND_SMALLTALK = {
    "hi", "hello", "hey", "hiya", "yo", "hi there", "hello there",
    "thanks", "thank you", "thx", "ok thanks", "okay thanks",
    "how are you", "how's it going", "what's up", "whats up",
    "مرحبا", "مرحبأ", "هاي", "هلا", "هلا والله", "أهلا", "اهلا", "اهلين",
    "كيفك", "كيفك؟", "شو اخبارك", "ازيك", "ازيك؟", "عامل ايه", "شعلومك", "شعلومك؟",
    "شكرا", "شكرا لك", "شكرا جزيلا", "مشكور", "يعطيك العافية", "تسلم",
    "مساء الخير", "صباح الخير", "مساء النور", "صباح النور",
}


def is_answerable(query_text: str) -> bool:
    """False for an empty message, a bare greeting or thanks, or a fragment
    too short to research - those get a warm reply with no searching."""
    normalized = (query_text or "").strip().lower()
    if not normalized:
        return False
    if normalized.strip("!؟?. ") in _GREETING_AND_SMALLTALK:
        return False
    word_count = len(normalized.split())
    if word_count < 3 and len(normalized) < 12:
        return False
    return True


# --- slots -------------------------------------------------------------------

_COUNTRIES: Dict[str, Tuple[str, ...]] = {
    "JO": ("jordan", "jordanian", "amman", "irbid", "zarqa", "aqaba", "الاردن", "اردني", "اربد", "الزرقاء", "العقبه"),
    "SA": ("saudi", "ksa", "riyadh", "jeddah", "dammam", "mecca", "medina", "السعوديه", "سعودي", "المملكه العربيه السعوديه",
           "الرياض", "جده", "الدمام"),
    "AE": ("uae", "emirates", "emirati", "dubai", "abu dhabi", "sharjah", "الامارات", "اماراتي", "دبي", "ابوظبي", "ابو ظبي",
           "الشارقه"),
    "KW": ("kuwait", "الكويت", "كويتي"),
    "QA": ("qatar", "doha", "قطر", "الدوحه", "قطري"),
    "BH": ("bahrain", "manama", "البحرين", "بحريني"),
    "OM": ("oman", "muscat", "سلطنه عمان", "مسقط", "عماني"),
    "EG": ("egypt", "egyptian", "cairo", "alexandria", "مصر", "مصري", "القاهره", "الاسكندريه"),
    "LB": ("lebanon", "lebanese", "beirut", "لبنان", "لبناني", "بيروت"),
    "SY": ("syria", "syrian", "سوريا", "سوري"),
    "IQ": ("iraq", "iraqi", "baghdad", "erbil", "العراق", "عراقي", "بغداد", "اربيل"),
    "PS": ("palestine", "palestinian", "فلسطين", "فلسطيني"),
    "YE": ("yemen", "اليمن", "يمني"),
    "MA": ("morocco", "moroccan", "casablanca", "المغرب", "مغربي"),
    "DZ": ("algeria", "الجزائر", "جزائري"),
    "TN": ("tunisia", "تونس", "تونسي"),
    "LY": ("libya", "ليبيا", "ليبي"),
    "SD": ("sudan", "السودان", "سوداني"),
    "TR": ("turkey", "turkiye", "türkiye", "turkish", "istanbul", "ankara", "izmir", "bursa", "تركيا", "تركي", "اسطنبول"),
    "CN": ("china", "chinese", "shenzhen", "guangzhou", "shanghai", "yiwu", "الصين", "صيني"),
    "IN": ("india", "indian", "الهند", "هندي"),
    "PK": ("pakistan", "pakistani", "باكستان"),
    "US": ("united states", "usa", "u.s.", "america", "american", "امريكا", "الولايات المتحده", "امريكي"),
    "GB": ("united kingdom", "uk", "britain", "british", "england", "بريطانيا", "بريطاني"),
    "DE": ("germany", "german", "المانيا", "الماني"),
    "IT": ("italy", "italian", "ايطاليا", "ايطالي"),
    "FR": ("france", "french", "فرنسا", "فرنسي"),
    "ES": ("spain", "spanish", "اسبانيا", "اسباني"),
    "NL": ("netherlands", "dutch", "هولندا", "هولندي"),
    "VN": ("vietnam", "vietnamese", "فيتنام"),
    "TH": ("thailand", "thai", "تايلاند"),
    "MY": ("malaysia", "malaysian", "ماليزيا"),
    "ID": ("indonesia", "indonesian", "اندونيسيا"),
    "BR": ("brazil", "brazilian", "البرازيل"),
}

_CURRENCIES: Dict[str, Tuple[str, ...]] = {
    "JOD": ("jod", "jd", "jordanian dinar", "دينار اردني", "د.ا"),
    "SAR": ("sar", "saudi riyal", "riyal", "ريال سعودي", "ر.س", "⃁"),
    "AED": ("aed", "dirham", "dhs", "درهم", "د.إ", "د.ا."),
    "KWD": ("kwd", "kuwaiti dinar", "دينار كويتي", "د.ك"),
    "QAR": ("qar", "qatari riyal", "ريال قطري", "ر.ق"),
    "BHD": ("bhd", "bahraini dinar", "دينار بحريني"),
    "OMR": ("omr", "omani rial", "ريال عماني"),
    "EGP": ("egp", "egyptian pound", "le", "جنيه", "ج.م"),
    "TRY": ("try", "lira", "turkish lira", "ليره", "ليرة", "ليره تركيه", "₺"),
    "USD": ("usd", "us$", "dollar", "dollars", "$", "دولار"),
    "EUR": ("eur", "euro", "euros", "€", "يورو"),
    "GBP": ("gbp", "pound sterling", "£", "استرليني"),
    "CNY": ("cny", "rmb", "yuan", "يوان"),
    "INR": ("inr", "rupee", "روبيه"),
}
_GENERIC_DINAR = ("dinar", "دينار", "دنانير")
_DINAR_CURRENCIES = ("JOD", "KWD", "BHD", "IQD", "LYD", "TND", "DZD")
_RIYAL_CURRENCIES = ("SAR", "QAR", "OMR", "YER")

_UNITS = r"(units?|pieces?|pcs|items?|cartons?|boxes?|packs?|packets?|bottles?|cans?|jars?|bags?|sacks?|pallets?|dozens?|" \
         r"kg|kilos?|kilograms?|tons?|tonnes?|litres?|liters?|" \
         r"وحده|وحدات|قطعه|قطع|حبه|حبات|كرتونه|كراتين|علبه|علب|قنينه|قناني|زجاجه|زجاجات|عبوه|عبوات|كيس|اكياس|" \
         r"صندوق|صناديق|طرد|طرود|درزن|كيلو|كغ|طن|اطنان|لتر|لترات)"
_NUMBER = r"(\d+(?:[.,]\d+)*)"
_QUANTITY = re.compile(_NUMBER + r"\s*" + _UNITS + r"(?![a-z])")
_PERCENT = re.compile(_NUMBER + r"\s*(%|٪|percent|بالمئه|بالميه|في المئه)")
_INCOTERM = re.compile(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b")
_HS_CODE = re.compile(r"(?:hs(?:\s*code)?|البند(?:\s*الجمركي)?|رمز\s*(?:النظام\s*)?المنسق)\s*[:#]?\s*(\d{4}(?:[.\s]?\d{2}){0,3})",
                      re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"'()]+")
_FX_RATE = re.compile(r"(?:exchange rate|fx rate|conversion rate|سعر الصرف|سعر التحويل)\s*(?:is|of|at|=|:|هو|بـ|ب)?\s*"
                      r"(\d+(?:\.\d+)?)")
# Ranking customers ("my best customers", "أكبر زبائني") needs the per-customer sales breakdown.
_CUSTOMER_RANKING = re.compile(r"(?<![a-z])(top|best|biggest|largest|main|most valuable|key|loyal)\s+(\w+\s+)?"
                               r"(customers?|clients?|buyers?|accounts?)|"
                               r"(افضل|اكبر|اهم|اكثر)\s+(ال)?(زبائن|زبون|عملاء|عميل|الزبائن|العملاء)|"
                               r"(زبائني|عملائي)\s+(ال)?(اكبر|اهم|افضل)")
# Asking for the change over time: a month-by-month series for the period.
_SERIES_CUES = ("by month", "per month", "each month", "every month", "monthly", "month by month", "month-by-month",
                "over time", "trend", "شهريا", "كل شهر", "حسب الشهر", "بالشهر", "على مدار", "تطور")
_COMPARE_CUES = ("compare", "compared", "comparison", " vs", "versus", "against", "than", "difference between",
                 "قارن", "مقارنه", "مقابل", "بالمقارنه", "الفرق بين")


@dataclass
class Money:
    amount: str
    currency: Optional[str]
    context: str      # the words just before the amount
    after: str = ""   # and just after it


@dataclass
class Understanding:
    question: str
    intents: List[str]
    slots: dict
    follow_up: bool = False
    effective_question: str = ""
    history_intents: List[str] = field(default_factory=list)
    public_scope: bool = False

    @property
    def needs_research(self) -> bool:
        return bool(set(self.intents) & EXTERNAL_INTENTS) or self.public_scope

    def state(self) -> dict:
        return {"question": self.question, "intents": self.intents, "slots": self.slots}


def _decimal(text: str) -> Optional[str]:
    raw = text.replace(",", "") if text.count(",") and "." in text else text.replace(",", "")
    try:
        return str(Decimal(raw))
    except InvalidOperation:
        return None


def _countries(text: str) -> List[Tuple[int, str]]:
    found = []
    for code, names in _COUNTRIES.items():
        for name in names:
            pattern = r"(?<![\w])" + re.escape(name) + r"(?![\w])" if re.search(r"[a-z]", name) else re.escape(name)
            for match in re.finditer(pattern, text):
                found.append((match.start(), code))
    return sorted(found)


# Adjectives of origin ("Syrian cucumbers", "خيار سوري") say where goods come from, never where they go.
_DEMONYM = re.compile(r"^(?:[a-z]+(?:ian|ish|ese|ean|ani)|emirati|iraqi|kuwaiti|qatari|omani|yemeni|thai|"
                      r"(?:ال)?[؀-ۿ]{2,}ي)(?![\w])")
_NOT_DEMONYM = ("دبي", "ابوظبي", "ابو ظبي")


def _is_demonym(text: str, position: int) -> bool:
    word = text[position:position + 24]
    return bool(_DEMONYM.match(word)) and not any(word.startswith(city) for city in _NOT_DEMONYM)


def _trade_route(text: str, mentions: List[Tuple[int, str]]) -> Tuple[Optional[str], Optional[str]]:
    origin = destination = None
    for position, code in mentions:
        before = text[max(0, position - 14):position]
        if re.search(r"(from|من|مِن)\s*(?:ال)?\s*$", before):
            origin = origin or code
        elif _is_demonym(text, position):
            continue
        # text is normalised (إلى -> الي); a lone "ل" must stand before the word, not be the article's own letter.
        elif re.search(r"(?:(?<![\w])(?:to|into|in|for)|الي|في|(?<![؀-ۿ])(?:ل|ع)(?:ل)?)\s*(?:ال)?\s*$", before):
            destination = destination or code
    demonyms = [code for position, code in mentions if _is_demonym(text, position) and code != destination]
    if not origin and len(set(demonyms)) == 1:
        origin = demonyms[0]
    if destination and not origin:
        # "Syrian cucumbers to Amman": the one other country named is where the goods come from.
        others = list(dict.fromkeys(code for _, code in mentions if code != destination))
        if len(others) == 1:
            origin = others[0]
    return origin, destination


def _currency_at(text: str, start: int, end: int, company_currency: Optional[str]) -> Optional[str]:
    window_before, window_after = text[max(0, start - 12):start], text[end:end + 16]
    for code, names in _CURRENCIES.items():
        for name in names:
            escaped = re.escape(name)
            if re.search(escaped + r"\s*$", window_before) or re.search(r"^\s*" + escaped + r"(?![a-z])", window_after):
                if code in ("SAR",) and name == "riyal" and company_currency in _RIYAL_CURRENCIES:
                    return company_currency
                return code
    for name in _GENERIC_DINAR:
        if re.search(r"^\s*" + re.escape(name), window_after) or re.search(re.escape(name) + r"\s*$", window_before):
            return company_currency if company_currency in _DINAR_CURRENCIES else "JOD"
    if re.search(r"^\s*ريال", window_after):
        return company_currency if company_currency in _RIYAL_CURRENCIES else "SAR"
    return None


def _money(text: str, company_currency: Optional[str]) -> List[Money]:
    amounts = []
    for match in re.finditer(_NUMBER, text):
        currency = _currency_at(text, match.start(), match.end(), company_currency)
        if not currency:
            continue
        value = _decimal(match.group(1))
        if value is None:
            continue
        # What the amount is (a supplier price, freight, a local price...) is
        # said just before it ("freight 300 JOD") or right after ("4.5 JOD locally").
        amounts.append(Money(value, currency, text[max(0, match.start() - 30):match.start()].strip(),
                             text[match.end():match.end() + 24].strip()))
    return amounts


def _period_days(text: str) -> Optional[int]:
    """A rolling window ("the last 90 days", "past 3 months"); calendar periods are `periods`."""
    return _periods.rolling_days(text)


# Size and packaging words, and words that describe rather than name a product: a question that shares only
# one of these with a product name ("the 1kg pack", "premium") is not about that product.
_GENERIC_NAME_WORDS = {
    "pack", "packs", "box", "jar", "tin", "bottle", "bag", "set", "kit", "mix", "blend", "gift", "premium", "extra",
    "fresh", "loose", "per", "medium", "large", "small", "mini", "new", "classic", "original", "special", "drink",
    "with", "and", "the", "for", "item", "product", "case", "cover", "service", "repair", "plus", "pro", "max",
    "علبه", "عبوه", "كيس", "مرطبان", "تنكه", "هديه", "ممتاز", "فاخر", "طازج", "صغير", "كبير", "وسط", "خلطه", "منتج",
    "غرام", "لتر", "مل", "كيلو", "قطعه", "حبه",
}
_ARTICLE = re.compile(r"(?<![\w])(?:وال|بال|لل|فال|كال|ال)(?=[\u0621-\u064a]{2,})")
_SIZE_TOKEN = re.compile(r"^\d+(?:[.,]\d+)?(?:[a-z]+)?$|^(?:ml|l|g|kg|gm|gb|tb|mm|cm|m|pcs|x)$")


def _name_tokens(text: str) -> List[str]:
    """Words of a product name or question, the Arabic article removed ("زيت الزيتون" -> "زيت زيتون"),
    a plural -s folded ("olives" -> "olive")."""
    words = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?[a-z]*|[\u0621-\u064a]+", _ARTICLE.sub("", text))
    return [w[:-1] if len(w) > 4 and w.endswith("s") and re.match("[a-z]", w) else w for w in words]


def _core(tokens: List[str]) -> List[str]:
    return [t for t in tokens if not _SIZE_TOKEN.match(t) and t not in _GENERIC_NAME_WORDS and len(t) > 1]


def _contains_run(haystack: List[str], needle: List[str]) -> bool:
    return any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def _all_history(text: str) -> bool:
    return bool(re.search(
        r"\b(?:all[- ]time|lifetime|all (?:of )?(?:our |the )?(?:sales )?history|all historical sales|"
        r"entire (?:sales )?history|since (?:the )?beginning)\b|"
        r"(?:كامل|كل|جميع) (?:سجل |تاريخ |تاريخية )?(?:المبيعات|الفترات)|منذ البداية|على مر التاريخ", text))


def _products(text: str, catalog: List[dict]) -> List[dict]:
    """Catalog products named in the question: whole names first (either language); when none is named in
    full, the products a partial name points at ("olive oil", "the honey", "زيت الزيتون", "التمر"): two
    consecutive words of a product's name, or one distinctive word of it (not a size or packaging word)."""
    matched = []
    for product in catalog:
        for name in filter(None, (product.get("name"), product.get("name_alt"))):
            normalized = _norm(name).strip()
            if len(normalized) < 3:
                continue
            if re.search(r"(?<![\w])" + re.escape(normalized) + r"(?![\w])", text):
                matched.append({"product_id": product["product_id"], "name": product.get("name") or name})
                break
    if matched:
        return matched[:5]
    question = _name_tokens(text)
    if not question:
        return []
    partial = []
    for product in catalog:
        best = 0
        for name in filter(None, (product.get("name"), product.get("name_alt"))):
            core = _core(_name_tokens(_norm(name)))
            if len(core) >= 2 and any(_contains_run(question, core[i:i + 2]) for i in range(len(core) - 1)):
                best = max(best, 2)
            elif any(len(word) >= 4 and word in question for word in core):
                best = max(best, 1)
        if best:
            partial.append((best, product))
    if not partial:
        return []
    strongest = max(score for score, _ in partial)
    # "Olive oil" names five products; "extra virgin olive oil" fewer - keep the closest matches only.
    return [{"product_id": p["product_id"], "name": p.get("name") or p.get("name_alt"), "partial": True}
            for score, p in partial if score == strongest][:8]


def extract_slots(question: str, catalog: Optional[List[dict]] = None, company_currency: Optional[str] = None,
                  today: Optional[date] = None) -> dict:
    raw = to_ascii_digits(question or "")
    text = _norm(question)
    mentions = _countries(text)
    origin, destination = _trade_route(text, mentions)
    slots: dict = {}
    if mentions:
        slots["countries"] = list(dict.fromkeys(code for _, code in mentions))
    if origin:
        slots["origin_country"] = origin
    if destination:
        slots["destination_country"] = destination
    period = _period_days(text)
    if _all_history(text):
        slots["all_history"] = True
    elif period:
        slots["period_days"] = period
    calendar_periods = _periods.resolve_periods(text, today or date.today())
    if calendar_periods:
        slots["periods"] = calendar_periods
    if _has(f" {text} ", _SERIES_CUES):
        slots["series"] = True
    if _has(f" {text} ", _COMPARE_CUES):
        slots["compare"] = True
    if _CUSTOMER_RANKING.search(text):
        slots["customer_ranking"] = True
    quantity = _QUANTITY.search(text)
    if quantity and _decimal(quantity.group(1)):
        slots["quantity"] = {"value": _decimal(quantity.group(1)), "unit": quantity.group(2)}
    money = _money(raw.lower(), company_currency)
    if money:
        slots["amounts"] = [{"amount": m.amount, "currency": m.currency, "context": m.context, "after": m.after}
                            for m in money[:8]]
        slots["currency"] = money[0].currency
    percents = []
    for match in _PERCENT.finditer(text):
        value = _decimal(match.group(1))
        if value is not None:
            percents.append({"value": value, "context": text[max(0, match.start() - 30):match.start()].strip(),
                             "after": text[match.end():match.end() + 24].strip()})
    if percents:
        slots["percentages"] = percents[:6]
    fx_rate = _FX_RATE.search(text)
    if fx_rate and _decimal(fx_rate.group(1)):
        slots["fx_rate"] = _decimal(fx_rate.group(1))
    hs_code = _HS_CODE.search(raw)
    if hs_code:
        slots["hs_code"] = re.sub(r"[\s.]", "", hs_code.group(1))
    incoterm = _INCOTERM.search(raw.upper())
    if incoterm:
        slots["incoterm"] = incoterm.group(1)
    route = _ROUTE.search(text)
    if route:
        slots["route"] = route.group(1).strip()
    if _has(f" {text} ", _TOP_PRODUCT):
        slots["top_product"] = True
    urls = _URL.findall(raw)
    if urls:
        slots["urls"] = list(dict.fromkeys(url.rstrip(".,;:!?") for url in urls))[:3]
    if catalog:
        products = _products(text, catalog)
        if products:
            slots["products"] = products
    return slots


_SLOT_KEYS_REPLACED_TOGETHER = {("origin_country", "destination_country", "countries")}


def understand(question: str, previous: Optional[dict] = None, catalog: Optional[List[dict]] = None,
               company_currency: Optional[str] = None, today: Optional[date] = None) -> Understanding:
    """The intents and slots of `question`, carrying over the previous
    turn's (`previous`, the stored state) when this is a follow-up.
    `today` is the company's own date (business_time.business_today), which
    "last month" and "this year" are counted from."""
    intents = detect_intents(question)
    slots = extract_slots(question, catalog, company_currency, today)
    if slots.get("customer_ranking") and SALES not in intents:
        intents.append(SALES)
    previous = previous or {}
    text = _norm(question).strip()
    words = text.split()
    cue = any(text.startswith(_norm(c)) for c in _FOLLOW_UP_CUES)
    previous_intents = list(previous.get("intents") or [])
    # A follow-up either says so ("and ...", "what about ..."), asks nothing new,
    # or is a short message about the same things as before.
    refers_back = (len(words) <= _REFERS_BACK_MAX_WORDS and not slots.get("products")
                   and bool((previous.get("slots") or {}).get("products")) and bool(_REFERS_BACK.search(text)))
    earlier_periods = (previous.get("slots") or {}).get("periods") or []
    # "and the month before?", "same period last year?": relative to the period just discussed - which wins
    # over reading "previous month" / "last year" from today.
    relative = _periods.relative_to(text, earlier_periods)
    if relative:
        slots["periods"] = relative
    refers_to_period = bool(relative) or (bool(earlier_periods) and "periods" not in slots
                                          and bool(_REFERS_BACK_TIME.search(text)))
    follow_up = bool(previous.get("question")) and (
        cue or refers_back or refers_to_period or not intents
        or (len(words) <= 5 and set(intents) <= set(previous_intents)))
    if not follow_up:
        if slots.get("periods") and not intents:
            # "Compare March with February", "how was Q3?": a period with no other topic is about sales.
            intents.append(SALES)
        return Understanding(question, intents, slots, False, question,
                             public_scope=is_public_scope(question, intents, slots))

    merged = dict(previous.get("slots") or {})
    if (slots.get('all_history') or slots.get('period_days')) and merged.get('top_product') and not slots.get('products'):
        # A product resolved as "top" in the previous window must be ranked
        # again when the user changes the period, rather than becoming a name filter.
        merged.pop('products', None)
    if slots.get("all_history"):
        merged.pop("period_days", None)
        merged.pop("periods", None)
    elif slots.get("period_days") or slots.get("periods"):
        merged.pop("all_history", None)
    if any(key in slots for key in ("origin_country", "destination_country", "countries")):
        for key in ("origin_country", "destination_country", "countries"):
            merged.pop(key, None)
    # A new period replaces the earlier one ("and in August?") - or joins it when the follow-up compares
    # ("how does that compare with August?"). A rolling window and a calendar period never both stand.
    if "periods" in slots or "period_days" in slots:
        earlier = merged.pop("periods", None) or []
        merged.pop("period_days", None)
        if slots.get("compare") and "periods" in slots and earlier:
            combined = {(p["start"], p["end"]): p for p in earlier + slots["periods"]}
            slots["periods"] = list(combined.values())[-4:]
    if slots.get("products"):
        merged.pop("products", None)
    merged.update(slots)
    combined = list(dict.fromkeys(previous_intents + intents)) if intents else previous_intents
    effective = f"{previous.get('question', '')} {question}".strip()
    return Understanding(question, combined, merged, True, effective, previous_intents,
                         public_scope=is_public_scope(effective, combined, merged))
