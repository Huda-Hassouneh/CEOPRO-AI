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
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

from src.ai.extraction.numerals import to_ascii_digits

# --- intents -----------------------------------------------------------------

SALES, FINANCIALS, PRODUCTS, PRICING, INVENTORY, FORECAST = "sales", "financials", "products", "pricing", "inventory", "forecast"
MARKETING, COMPETITORS, REVIEWS, DOCUMENTS = "marketing", "competitors", "reviews", "documents"
CUSTOMER_PREFERENCE, PRODUCT_RESEARCH, MARKET_RESEARCH = "customer_preference", "product_research", "market_research"
REGULATION, TRADE, LANDED_COST, ADVICE = "regulation", "trade", "landed_cost", "advice"

EXTERNAL_INTENTS = frozenset({CUSTOMER_PREFERENCE, PRODUCT_RESEARCH, MARKET_RESEARCH, REGULATION, TRADE, LANDED_COST})

_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    SALES: ("sale", "sold", "revenue", "income", "turnover", "invoice", "orders", "selling",
            "مبيع", "بعت", "بعنا", "ايراد", "إيراد", "دخل", "فاتور", "فواتير", "طلبات"),
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
    REVIEWS: ("review", "rating", "feedback", "complain", "sentiment", "customers say", "satisf",
              "تقييم", "مراجع", "آراء", "اراء", "شكاو", "شكوى", "رضا", "رأي الزبائن", "راي الزبائن"),
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
    TRADE: ("import", "export", "custom", "tariff", "duty", "duties", "hs code", "hs-code", "origin", "shipping",
            "freight", "incoterm", "clearance", "ship it", "shipment",
            "استيراد", "استورد", "تصدير", "صدر", "جمارك", "جمرك", "تعرفة", "تعرفه", "رسوم جمركية", "شحن", "منشأ",
            "بند جمركي", "تخليص"),
    ADVICE: ("should i", "should we", "recommend", "advice", "what can i do", "what should", "how can i improve",
             "how do i increase", "how to increase", "how to grow",
             "شو لازم", "شو بنصح", "انصح", "أنصح", "تنصح", "نصيحة", "توصية", "ماذا أفعل", "كيف ازيد", "كيف أزيد",
             "كيف بقدر"),
}

_LANDED_COST_CUES = ("cheaper", "cheapest", "landed", "worth it", "more economical", "economical", "save", "saving",
                     "compare", "cost to import", "cost of importing", "total cost",
                     "أرخص", "ارخص", "أوفر", "اوفر", "توفير", "يستحق", "بيستاهل", "مقارنة", "قارن", "التكلفة الكلية",
                     "تكلفة الاستيراد", "كلفة الاستيراد")

_FOLLOW_UP_CUES = ("and ", "what about", "how about", "and what", "same for", "also", "instead", "then", "why?",
                   "و", "طيب", "وماذا", "وشو", "شو عن", "ماذا عن", "وكمان", "وفي", "بدلا", "بدل", "كمان", "ليش؟", "لماذا؟")


def _norm(text: str) -> str:
    text = to_ascii_digits(text or "").lower()
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    return text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))


def _has(text: str, keywords) -> bool:
    return any(_norm(keyword) in text for keyword in keywords)


def detect_intents(text: str) -> List[str]:
    lowered = f" {_norm(text)} "
    found = [intent for intent, keywords in _KEYWORDS.items() if _has(lowered, keywords)]
    if TRADE in found and _has(lowered, _LANDED_COST_CUES):
        found.append(LANDED_COST)
    return found


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
_PERIOD_PATTERNS = (
    (re.compile(r"(?:last|past|previous)\s+(\d+)\s+days?|(?:اخر|آخر)\s+(\d+)\s+(?:يوم|ايام)"), 1),
    (re.compile(r"(?:last|past|previous)\s+(\d+)\s+weeks?|(?:اخر|آخر)\s+(\d+)\s+(?:اسبوع|اسابيع)"), 7),
    (re.compile(r"(?:last|past|previous)\s+(\d+)\s+months?|(?:اخر|آخر)\s+(\d+)\s+(?:شهر|اشهر|شهور)"), 30),
)
_NAMED_PERIODS = (
    (("last week", "past week", "this week", "الاسبوع الماضي", "هالاسبوع", "هذا الاسبوع"), 7),
    (("last month", "past month", "this month", "الشهر الماضي", "الشهر اللي فات", "هالشهر", "هذا الشهر"), 30),
    (("last quarter", "past quarter", "this quarter", "last 3 months", "الربع الماضي", "اخر ثلاث اشهر", "اخر 3 اشهر"), 90),
    (("last year", "past year", "this year", "السنه الماضيه", "العام الماضي", "هالسنه", "هذه السنه"), 365),
)


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

    @property
    def needs_research(self) -> bool:
        return bool(set(self.intents) & EXTERNAL_INTENTS)

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


def _trade_route(text: str, mentions: List[Tuple[int, str]]) -> Tuple[Optional[str], Optional[str]]:
    origin = destination = None
    for position, code in mentions:
        before = text[max(0, position - 14):position]
        if re.search(r"(from|من|مِن)\s*(?:ال)?\s*$", before):
            origin = origin or code
        elif re.search(r"(to|into|in|for|الي|ل|في|ع)\s*(?:ال)?\s*$", before):  # text is normalised: إلى -> الي
            destination = destination or code
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
    for pattern, unit in _PERIOD_PATTERNS:
        match = pattern.search(text)
        if match:
            number = next(group for group in match.groups() if group)
            return max(1, min(int(number) * unit, 730))
    for phrases, days in _NAMED_PERIODS:
        if _has(text, phrases):
            return days
    return None


def _products(text: str, catalog: List[dict]) -> List[dict]:
    """Catalog products named in the question (whole names, either language)."""
    matched = []
    for product in catalog:
        for name in filter(None, (product.get("name"), product.get("name_alt"))):
            normalized = _norm(name).strip()
            if len(normalized) < 3:
                continue
            if re.search(r"(?<![\w])" + re.escape(normalized) + r"(?![\w])", text):
                matched.append({"product_id": product["product_id"], "name": product.get("name") or name})
                break
    return matched[:5]


def extract_slots(question: str, catalog: Optional[List[dict]] = None, company_currency: Optional[str] = None) -> dict:
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
    if period:
        slots["period_days"] = period
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
               company_currency: Optional[str] = None) -> Understanding:
    """The intents and slots of `question`, carrying over the previous
    turn's (`previous`, the stored state) when this is a follow-up."""
    intents = detect_intents(question)
    slots = extract_slots(question, catalog, company_currency)
    previous = previous or {}
    text = _norm(question).strip()
    words = text.split()
    cue = any(text.startswith(_norm(c)) for c in _FOLLOW_UP_CUES)
    previous_intents = list(previous.get("intents") or [])
    # A follow-up either says so ("and ...", "what about ..."), asks nothing new,
    # or is a short message about the same things as before.
    follow_up = bool(previous.get("question")) and (
        cue or not intents or (len(words) <= 5 and set(intents) <= set(previous_intents)))
    if not follow_up:
        return Understanding(question, intents, slots, False, question)

    merged = dict(previous.get("slots") or {})
    if any(key in slots for key in ("origin_country", "destination_country", "countries")):
        for key in ("origin_country", "destination_country", "countries"):
            merged.pop(key, None)
    merged.update(slots)
    combined = list(dict.fromkeys(previous_intents + intents)) if intents else previous_intents
    effective = f"{previous.get('question', '')} {question}".strip()
    return Understanding(question, combined, merged, True, effective, previous_intents)
