"""
KEEL - how to use the product, for the assistant.

Each section is a task a user can ask about ("how do I add a product?",
"where do I upload my sales file?", "why is this forecast so low?"), with
step-by-step directions through the screens that actually exist.

Every screen, tab and button is written as [[English label||Arabic label]],
exactly as the interface shows it - and
src/ai/tests/test_product_guide.py fails if any of them is not a real label
in frontend/src/assets/locales/en.json and ar.json. So the assistant can
only name buttons that exist, in the language the user is reading.

select_sections() picks the sections relevant to a question (keyword match
in English and Arabic) so the whole guide isn't sent with every question.
"""
import re
from typing import List

_LABEL = re.compile(r"\[\[(.+?)\|\|(.+?)\]\]")

# (key, keywords - English and Arabic, lowercase stems; steps)
SECTIONS = [
    ("add_product",
     ["add product", "add a product", "add products", "add a new product", "create a product", "new product", "create product", "edit product", "product catalog", "catalogue",
      "منتج جديد", "إضافة منتج", "اضافة منتج", "أضيف منتج", "اضيف منتج", "منتجاتي"],
     "Add a product: open [[Products||المنتجات]] in the top navigation bar, choose [[Add Product||إضافة منتج]], fill in the "
     "name, price, currency, cost (optional, used for margins) and starting stock, then choose "
     "[[Create product||إنشاء المنتج]]. Products sold by weight, length, volume or time and services without stock "
     "are supported. Many products at once: use [[Import products||استيراد المنتجات]] (see uploading data). "
     "Click a product's name to open its page with its sales, forecast, stock, competitor prices and reviews."),
    ("upload_sales",
     ["upload", "import", "sales file", "excel", "csv", "spreadsheet", "my data", "connect data", "pos", "erp",
      "رفع", "استيراد", "ملف المبيعات", "ملف", "اكسل", "إكسل", "بياناتي", "ربط البيانات"],
     "Upload a sales or product file: open [[Data & Documents||البيانات والمستندات]] in the top navigation bar. Under "
     "[[Upload Files||رفع الملفات]] choose [[Select Files||اختيار الملفات]] (CSV, Excel or PDF; "
     "[[Download Template||تنزيل القالب]] shows the expected columns, but most real exports work as they are), then "
     "[[Prepare Import||تجهيز الاستيراد]]. The result appears under [[Recent Data Activity||نشاط البيانات الأخير]]. "
     "Re-uploading the same file does not duplicate sales. A business system can be linked with "
     "[[Add Data Source||إضافة مصدر بيانات]]."),
    ("record_sale",
     ["record a sale", "record sale", "manual sale", "point of sale", "sell", "تسجيل بيع", "تسجيل عملية بيع", "بيع يدوي"],
     "Record a sale by hand: open [[Products||المنتجات]] and choose [[Record sale||تسجيل بيع]] at the top, pick the "
     "product, enter the quantity and confirm. You can also use [[Sell||بيع]] on a product's row, or "
     "[[Record sale||تسجيل بيع]] on the product's own page. Forecasts update automatically after new sales."),
    ("product_page",
     ["sales history", "product sales", "product page", "one product", "this product", "how is my", "product performance", "sold of",
      "مبيعات المنتج", "صفحة المنتج", "أداء المنتج", "سجل المبيعات"],
     "Everything about one product: open [[Products||المنتجات]] and click the product's name. Its page shows "
     "[[What needs attention||ما يحتاج انتباهك]], units and revenue for the last 30 days, the [[Sales and forecast||المبيعات والتوقع]] "
     "chart, [[Competitor prices for this product||أسعار المنافسين لهذا المنتج]], [[Reviews of this product||تقييمات هذا المنتج]] "
     "and [[Recent sales||أحدث المبيعات]]."),
    ("reviews",
     ["review", "reviews", "customer feedback", "ratings", "sentiment", "تقييم", "تقييمات", "مراجعات", "آراء العملاء"],
     "Import customer reviews: open [[Data & Documents||البيانات والمستندات]], go to [[Customer Reviews||تقييمات العملاء]] and "
     "choose [[Import reviews||استيراد التقييمات]] (CSV or Excel with at least a review column). Each review's "
     "sentiment is analysed automatically."),
    ("competitors",
     ["competitor", "competitors", "rival", "add competitor", "track competitor", "competitor price",
      "منافس", "منافسين", "المنافسون", "منافسيني", "إضافة منافس", "سعر المنافس"],
     "Competitors: open [[Competitors||المنافسون]] in the top navigation bar. Choose [[Add competitor||إضافة منافس]], enter the "
     "name and website, and say how they compete: [[Competes with my whole business||ينافس نشاطي كله]] (another "
     "shop in your market) or [[Competes on specific products||ينافس على منتجات محددة]] (then tick the products). "
     "The [[Competition for each product||المنافسة على كل منتج]] table shows which products have competitor prices; "
     "[[Add a competitor||إضافة منافس]] on a row fills a gap. To record a price you saw, open the competitor and use "
     "[[Record a competitor price||تسجيل سعر منافس]], then [[Save price||حفظ السعر]]."),
    ("search_scope",
     ["search scope", "radius", "how far", "local competitors", "discovery", "نطاق البحث", "نصف القطر", "المنطقة"],
     "Change where competitors are searched for: open [[Competitors||المنافسون]], choose "
     "[[Search area||نطاق البحث]], pick city, region, country, global or a custom radius, then "
     "[[Save Scope||حفظ النطاق]]."),
    ("target_markets",
     ["target market", "target markets", "markets i sell", "countries", "expand", "الأسواق المستهدفة", "السوق المستهدف", "دول"],
     "Change your target markets: open [[Settings||الإعدادات]], the [[Company||الشركة]] tab, and the "
     "[[Target Markets||الأسواق المستهدفة]] section; enter a country code (or a region) and choose [[Add||إضافة]]. "
     "Target markets are where you want to compete; they are separate from where your company is registered."),
    ("forecast",
     ["forecast", "demand", "prediction", "predict", "restock", "inventory", "stock", "how much will i sell",
      "توقع", "التنبؤ", "الطلب", "المخزون", "إعادة التخزين", "كم سأبيع"],
     "Forecasts: open [[Demand||الطلب]]. It shows the demand expected over the next 30 days for every product with "
     "sales, whether it is rising or falling compared with the last 30 days, how long the stock lasts and whether to "
     "restock. Forecasts update automatically after new sales; [[Refresh forecasts||تحديث التوقعات]] recalculates them "
     "now. Click a product to open its page and chart. A forecast is learned from that product's own past sales, so a "
     "product needs some sales history first."),
    ("pricing",
     ["price", "pricing", "margin", "price recommendation", "should i raise", "should i lower", "سعر", "التسعير", "الهامش", "توصية السعر"],
     "Pricing advice: open [[Pricing||التسعير]] and choose [[Get Recommendation||احصل على توصية]] on a product, or "
     "[[Price advice||نصيحة السعر]] on the product's page. It compares your price with competitor prices recorded in "
     "the last 30 days and suggests raise, lower or hold, never below your minimum margin over cost and never a very "
     "large jump at once. With no recent competitor price it says so instead of guessing - record one under Competitors."),
    ("campaign",
     ["campaign", "marketing", "ad", "advert", "post", "image", "social media post", "حملة", "تسويق", "إعلان", "صورة", "منشور"],
     "Create a marketing campaign: open [[Marketing||التسويق]] (or [[Promote||روّج له]] on a product's page) and follow "
     "the steps: what you're marketing (a product, a link or a short description, plus an optional photo), what you "
     "want to create, who it's for, the look, your creative instruction and the timing; then choose "
     "[[Create my campaign||أنشئ حملتي]]. The result has posts for Instagram, Facebook, TikTok and a Google ad. "
     "AI images only work when they are enabled for your account."),
    ("assistant_documents",
     ["document", "documents", "knowledge", "policy", "pdf", "upload document", "مستند", "مستندات", "سياسة", "رفع مستند"],
     "Teach the assistant your documents: open [[Assistant||المساعد]] and choose "
     "[[Upload Document||رفع مستند]] (PDF, Word, Excel, text). Once a document shows as ready, ask about it; a "
     "document that failed can be processed again with its retry button. [[New chat||محادثة جديدة]] starts a "
     "fresh conversation."),
    ("team",
     ["team", "invite", "employee", "staff", "user", "member", "role", "فريق", "دعوة", "موظف", "عضو", "صلاحيات"],
     "Invite a colleague: open [[Settings||الإعدادات]], the [[Team Members||أعضاء الفريق]] tab, and choose "
     "[[Invite Member||دعوة عضو]]; enter their email and role."),
    ("billing",
     ["billing", "plan", "subscription", "usage", "limit", "upgrade", "how many questions", "الفوترة", "الباقة", "الاشتراك", "الاستخدام", "الحد", "ترقية"],
     "See your plan and usage: open [[Billing||الفوترة]]. It shows your plan, the current billing period and how much "
     "of each allowance is used (assistant questions, web searches, AI images, products, competitors, document "
     "storage)."),
    ("language",
     ["language", "arabic", "english", "translate", "اللغة", "عربي", "انجليزي", "إنجليزي"],
     "Change the language: use the language button in the top bar, or [[Settings||الإعدادات]] → "
     "[[Preferences||التفضيلات]]."),
    ("dashboard",
     ["dashboard", "overview", "kpi", "summary", "home", "لوحة التحكم", "ملخص", "نظرة عامة"],
     "The [[Dashboard||لوحة التحكم]] shows today's sales, revenue and units for the chosen period (7, 30 or 90 "
     "days) with the change versus the previous period, the 30-day forecast, products to restock, the next best "
     "actions, top and falling products, recent competitor price changes and price opportunities. "
     "[[Reports||التقارير]] has detailed sales reports to export."),
]


def _render(text: str, language: str) -> str:
    index = 1 if language == "ar" else 0
    return _LABEL.sub(lambda m: f"«{m.group(index + 1)}»", text)


def labels() -> List[tuple]:
    """Every (English, Arabic) label pair the guide names - for the test."""
    return [pair for _key, _kw, text in SECTIONS for pair in _LABEL.findall(text)]


# A navigation question asks how/where to do something in the product, as
# opposed to a business question ("which product sells best?") that happens
# to share a keyword with a section ("product", "price").
_HOW_TO = re.compile(
    r"\b(how (do|can|should|would) i|how to|how does|where (do|can|is|are)|where's|which (page|screen|button|tab|menu)"
    r"|steps?\b|set ?up|walk me through|show me how|can i (add|change|upload|import|create|invite|see|find|record|connect)"
    r"|why (am i|do i) see|what does .+ mean)"
    r"|كيف|كيفية|وين|أين|اين|فين|شلون|ازاي|إزاي|طريقة|خطوات|أقدر|اقدر|مكان|لماذا أرى|ليش بشوف|ليش اشوف",
    re.IGNORECASE,
)
_ARABIC = re.compile(r"[\u0600-\u06FF]")


def is_how_to_question(question: str) -> bool:
    return bool(_HOW_TO.search(question or ""))


def question_language(question: str) -> str:
    """'ar' when most words are Arabic, else 'en' - picks which label to quote."""
    words = (question or "").split()
    arabic = sum(1 for w in words if _ARABIC.search(w))
    return "ar" if arabic and arabic * 2 >= len(words) else "en"


def _matches(keyword: str, question: str) -> bool:
    if _ARABIC.search(keyword):
        return keyword in question  # Arabic attaches prefixes (ال، و، ب) to words
    return re.search(r"\b" + re.escape(keyword) + r"s?\b", question) is not None


# The screen each section starts from (frontend/src/app/router/routePaths.js),
# so a reference to the guide opens that screen.
SCREENS = {
    "add_product": "/products", "upload_sales": "/connect-data", "record_sale": "/products",
    "product_page": "/products", "reviews": "/connect-data", "competitors": "/market/competitors",
    "search_scope": "/market/search-scope", "target_markets": "/settings", "forecast": "/demand",
    "pricing": "/pricing", "campaign": "/marketing", "assistant_documents": "/ai-advisor",
    "team": "/settings/team", "billing": "/billing", "language": "/settings", "dashboard": "/dashboard",
}


def _selected(question: str, limit: int) -> List[tuple]:
    q = (question or "").lower()
    scored = []
    for key, keywords, text in SECTIONS:
        score = sum(len(k) for k in keywords if _matches(k, q))
        if score:
            scored.append((score, key, text))
    scored.sort(reverse=True)
    return [(key, text) for _score, key, text in scored[:limit]]


def select_sections(question: str, language: str = "en", limit: int = 3) -> List[str]:
    return [_render(text, language) for _key, text in _selected(question, limit)]


def guide_screens(question: str) -> List[str]:
    """The screen of each section build_guide_block() returns, in the same order."""
    if not is_how_to_question(question):
        return []
    return [SCREENS.get(key) for key, _text in _selected(question, limit=2)]


def build_guide_block(question: str, language: str = None) -> str:
    """The guide sections for a how/where question, or "" for anything else."""
    if not is_how_to_question(question):
        return ""
    sections = select_sections(question, language or question_language(question), limit=2)
    if not sections:
        return ""
    return (
        "How to do this in KEEL (source: the product's own screens - quote the «labels» exactly as written, "
        "never mention a screen or button that isn't listed here):\n- " + "\n- ".join(sections)
    )
