"""SEALED understanding test set - written 2026-11-05 before any model result was seen.
Never used to change rules or prompts. Score it only for aggregate results at decision points.
Author-written (not independent of the developer): see the report's limitations.

Fields as in understanding_benchmark.py, plus:
  lang: en | msa | jo | lev | eg | gulf | mix
  allowed: extra intents that are acceptable (anything else detected counts against intent precision).
"""
from src.ai.rag import understanding as U

S, F, P, PR, I, FC = U.SALES, U.FINANCIALS, U.PRODUCTS, U.PRICING, U.INVENTORY, U.FORECAST
C, R, D, CO = U.COMPETITORS, U.REVIEWS, U.DOCUMENTS, U.COMPANY

OCT = [("2026-10-01", "2026-11-01")]
SEP = [("2026-09-01", "2026-10-01")]
AUG = [("2026-08-01", "2026-09-01")]
JUL = [("2026-07-01", "2026-08-01")]
JUN = [("2026-06-01", "2026-07-01")]
MAY = [("2026-05-01", "2026-06-01")]
APR = [("2026-04-01", "2026-05-01")]
MAR = [("2026-03-01", "2026-04-01")]
FEB = [("2026-02-01", "2026-03-01")]
JAN = [("2026-01-01", "2026-02-01")]
DEC25 = [("2025-12-01", "2026-01-01")]
SEP25 = [("2025-09-01", "2025-10-01")]
OCT25 = [("2025-10-01", "2025-11-01")]
Q1, Q2, Q3 = [("2026-01-01", "2026-04-01")], [("2026-04-01", "2026-07-01")], [("2026-07-01", "2026-10-01")]
Q4TD = [("2026-10-01", "2026-11-06")]
Y2025 = [("2025-01-01", "2026-01-01")]
YTD = [("2026-01-01", "2026-11-06")]
MTD = [("2026-11-01", "2026-11-06")]
YDAY = [("2026-11-04", "2026-11-05")]
TODAY = [("2026-11-05", "2026-11-06")]
H1 = [("2026-01-01", "2026-07-01")]
SINCE_MAR = [("2026-03-01", "2026-11-06")]
OCT1_15 = [("2026-10-01", "2026-10-16")]


def c(lang, q, **kw):
    return {"lang": lang, "q": q, **kw}


A_P = {P}         # naming a product may also flag the catalogue
A_PS = {P, PR}

SEALED = [
    # ===================== English =====================
    c("en", "How much revenue did we generate in October?", intents={S}, periods=OCT),
    c("en", "what were last month's sales numbers", intents={S}, periods=OCT),
    c("en", "Give me the sales figure for Q1", intents={S}, periods=Q1),
    c("en", "How much have we sold so far this year?", intents={S}, periods=YTD),
    c("en", "sales yesterday?", intents={S}, periods=YDAY),
    c("en", "Revenue between 1 and 15 October", intents={S}, periods=OCT1_15),
    c("en", "How did sales in September compare to August?", intents={S}, periods=SEP + AUG),
    c("en", "Is revenue up compared with the same month last year?", intents={S}),
    c("en", "what's our total for 2025", intents={S}, periods=Y2025),
    c("en", "how many sales did we make this quarter", intents={S}, periods=Q4TD),
    c("en", "Show monthly revenue since March", intents={S}, periods=SINCE_MAR),
    c("en", "What did we sell in the last 7 days?", intents={S}, days=7),
    c("en", "Which product earned the most in Q3?", intents={S}, periods=Q3, top=True, allowed=A_P),
    c("en", "What are our three weakest sellers?", intents={S}, top=True, allowed=A_P),
    c("en", "How many bottles of Extra Virgin Olive Oil 1L went out last month?", intents={S}, periods=OCT,
      products=["Extra Virgin Olive Oil 1L"], allowed=A_P),
    c("en", "Tahini sales in June", intents={S}, periods=JUN, products=["Tahini 450g"], allowed=A_P),
    c("en", "How much stock is left of Maftoul 500g?", intents={I}, products=["Maftoul 500g"], allowed=A_P),
    c("en", "Anything about to run out?", intents={I}),
    c("en", "When should I reorder Sidr Honey 500g?", intents={I}, products=["Sidr Honey 500g"], allowed=A_P | {FC}),
    c("en", "What's the expected demand for Medjool Dates 1kg next month?", intents={FC}, products=["Medjool Dates 1kg"],
      allowed=A_P),
    c("en", "Forecast sumac for the coming month", intents={FC}, products=["Sumac 200g"], allowed=A_P),
    c("en", "What price do we sell Freekeh 1kg at?", intents={PR}, products=["Freekeh 1kg"], allowed=A_P),
    c("en", "Is our honey overpriced compared to other shops?", intents={C}, allowed={PR, P}),
    c("en", "What was the gross margin last month?", intents={F}, periods=OCT),
    c("en", "Which items have the lowest profit margin?", intents={F}, allowed={P}),
    c("en", "How many products are in our catalogue?", intents={P}),
    c("en", "What are people saying in our reviews?", intents={R}),
    c("en", "Did we get any bad reviews last month?", intents={R}, periods=OCT),
    c("en", "What's our policy on refunds for damaged items?", intents={D}),
    c("en", "Do you deliver to Irbid and how much does it cost?", intents={D}, allowed={PR}),
    c("en", "Who are we and what do we sell?", intents={CO}),
    c("en", "hello there", answerable=False),
    c("en", "thanks, that's helpful", answerable=False),
    # ===================== Arabic MSA =====================
    c("msa", "كم بلغت إيرادات شهر أكتوبر؟", intents={S}, periods=OCT),
    c("msa", "ما إجمالي المبيعات خلال الربع الأول؟", intents={S}, periods=Q1),
    c("msa", "ما حجم المبيعات منذ بداية العام؟", intents={S}, periods=YTD),
    c("msa", "كم كانت المبيعات يوم أمس؟", intents={S}, periods=YDAY),
    c("msa", "قارن بين مبيعات سبتمبر وأغسطس", intents={S}, periods=SEP + AUG),
    c("msa", "ما المبيعات خلال آخر سبعة أيام؟", intents={S}, days=7),
    c("msa", "ما المنتج الأعلى إيراداً في الربع الثالث؟", intents={S}, periods=Q3, top=True, allowed=A_P),
    c("msa", "كم وحدة بيعت من الطحينة في يونيو؟", intents={S}, periods=JUN, products=["Tahini 450g"], allowed=A_P),
    c("msa", "ما الكمية المتبقية من المفتول في المخزون؟", intents={I}, products=["Maftoul 500g"], allowed=A_P),
    c("msa", "ما المنتجات التي يجب إعادة طلبها؟", intents={I}, allowed={P}),
    c("msa", "ما الطلب المتوقع على التمر المجهول في الشهر القادم؟", intents={FC}, products=["Medjool Dates 1kg"], allowed=A_P),
    c("msa", "ما سعر بيع الفريكة؟", intents={PR}, products=["Freekeh 1kg"], allowed=A_P),
    c("msa", "ما هامش الربح الإجمالي في الشهر الماضي؟", intents={F}, periods=OCT),
    c("msa", "كم عدد المنتجات لدينا؟", intents={P}),
    c("msa", "ما تقييمات العملاء لمتجرنا؟", intents={R}),
    c("msa", "ما سياسة استرداد الأموال؟", intents={D}),
    c("msa", "كم تبلغ رسوم التوصيل إلى إربد؟", intents={D}, allowed={PR}),
    c("msa", "من هم منافسونا الرئيسيون؟", intents={C}),
    c("msa", "عرّفني بشركتنا", intents={CO}),
    c("msa", "صباح الخير", answerable=False),
    # ===================== Jordanian =====================
    c("jo", "قديش بعنا الشهر الماضي؟", intents={S}, periods=OCT),
    c("jo", "شو وضع المبيعات هالشهر؟", intents={S}, periods=MTD),
    c("jo", "كم طلعت الغلة بشهر أيلول؟", intents={S}, periods=SEP),
    c("jo", "بدي مبيعات من أول السنة لهلأ", intents={S}, periods=YTD),
    c("jo", "قارنلي مبيعات تشرين الأول مع أيلول", intents={S}, periods=OCT + SEP),
    c("jo", "شو أكتر صنف ماشي عنا هالسنة؟", intents={S}, periods=YTD, top=True, allowed=A_P),
    c("jo", "قديش بعنا زيت زيتون بكر الشهر الماضي؟", intents={S}, periods=OCT,
      products=["Extra Virgin Olive Oil 1L"], allowed=A_P),
    c("jo", "قديش ضايل عنا طحينة؟", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("jo", "شو الأصناف اللي لازم نطلبها؟", intents={I}, allowed={P}),
    c("jo", "قديش متوقع نبيع سماق الشهر الجاي؟", intents={FC}, products=["Sumac 200g"], allowed=A_P),
    c("jo", "قديش سعر الفريكة عنا؟", intents={PR}, products=["Freekeh 1kg"], allowed=A_P),
    c("jo", "قديش ربحنا بشهر أيلول؟", intents={F}, periods=SEP),
    c("jo", "شو بيحكوا الزباين عنا؟", intents={R}),
    c("jo", "إذا الزبون بدو يرجع لبنة شو بصير؟", intents={D}),
    c("jo", "مين المنافسين اللي حوالينا؟", intents={C}),
    c("jo", "يعطيك العافية", answerable=False),
    # ===================== Levantine (Syrian / Lebanese / Palestinian) =====================
    c("lev", "قديه كانت المبيعات بشهر آب؟", intents={S}, periods=AUG),
    c("lev", "شو صار بالمبيعات مبارح؟", intents={S}, periods=YDAY),
    c("lev", "بدي مبيعات الربع التالت", intents={S}, periods=Q3),
    c("lev", "قارن مبيعات حزيران مع تموز", intents={S}, periods=JUN + JUL),
    c("lev", "أيا منتج انباع أكتر شي بتموز؟", intents={S}, periods=JUL, top=True, allowed=A_P),
    c("lev", "كم كيلو زعتر فرط بعنا بأيلول؟", intents={S}, periods=SEP, products=["Loose Za'atar (per kg)"], allowed=A_P),
    c("lev", "في عنا عسل سدر بالمستودع؟", intents={I}, products=["Sidr Honey 500g"], allowed=A_P),
    c("lev", "شو المتوقع نبيع من الفريكة الشهر الجاي؟", intents={FC}, products=["Freekeh 1kg"], allowed=A_P),
    c("lev", "بقديش منبيع المفتول؟", intents={PR}, products=["Maftoul 500g"], allowed=A_P),
    c("lev", "شو هامش الربح عالعسل؟", intents={F}),
    c("lev", "شو رأي الناس بخدمتنا؟", intents={R}),
    c("lev", "شو سياسة الترجيع عندكن؟", intents={D}),
    c("lev", "مرحبا كيفك", answerable=False),
    # ===================== Egyptian =====================
    c("eg", "بعنا بكام الشهر اللي فات؟", intents={S}, periods=OCT),
    c("eg", "المبيعات عاملة إيه السنة دي؟", intents={S}, periods=YTD),
    c("eg", "عايز أعرف مبيعات شهر 9", intents={S}, periods=SEP),
    c("eg", "قارن مبيعات أكتوبر بسبتمبر", intents={S}, periods=OCT + SEP),
    c("eg", "إيه أكتر منتج اتباع في أغسطس؟", intents={S}, periods=AUG, top=True, allowed=A_P),
    c("eg", "بعنا كام علبة طحينة في يونيو؟", intents={S}, periods=JUN, products=["Tahini 450g"], allowed=A_P),
    c("eg", "فاضل عندنا كام كيس مفتول؟", intents={I}, products=["Maftoul 500g"], allowed=A_P),
    c("eg", "إيه المنتجات اللي قربت تخلص؟", intents={I}, allowed={P}),
    c("eg", "متوقع نبيع كام عسل سدر الشهر الجاي؟", intents={FC}, products=["Sidr Honey 500g"], allowed=A_P),
    c("eg", "سعر السماق عندنا بكام؟", intents={PR}, products=["Sumac 200g"], allowed=A_P),
    c("eg", "كسبنا كام الشهر اللي فات؟", intents={F}, periods=OCT),
    c("eg", "الناس رأيها إيه فينا؟", intents={R}),
    c("eg", "التوصيل للزرقا بكام؟", intents={D}, allowed={PR}),
    c("eg", "إزيك عامل إيه", answerable=False),
    # ===================== Gulf =====================
    c("gulf", "شكثر بعنا الشهر الماضي؟", intents={S}, periods=OCT),
    c("gulf", "كم مبيعاتنا اليوم؟", intents={S}, periods=TODAY),
    c("gulf", "ابي مبيعات الربع الأول", intents={S}, periods=Q1),
    c("gulf", "قارن لي مبيعات مايو ويونيو", intents={S}, periods=MAY + JUN),
    c("gulf", "وش أكثر منتج انباع هالسنة؟", intents={S}, periods=YTD, top=True, allowed=A_P),
    c("gulf", "كم كرتون تمر مجهول بعنا في سبتمبر؟", intents={S}, periods=SEP, products=["Medjool Dates 1kg"], allowed=A_P),
    c("gulf", "كم باقي عندنا من الطحينة؟", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("gulf", "وش المنتجات اللي خلصت؟", intents={I}, allowed={P}),
    c("gulf", "كم متوقع نبيع من السماق الشهر الجاي؟", intents={FC}, products=["Sumac 200g"], allowed=A_P),
    c("gulf", "بكم نبيع الفريكة؟", intents={PR}, products=["Freekeh 1kg"], allowed=A_P),
    c("gulf", "كم ربحنا هالسنة؟", intents={F}, periods=YTD),
    c("gulf", "وش يقولون العملاء عنا؟", intents={R}),
    c("gulf", "وش سياسة الاسترجاع؟", intents={D}),
    c("gulf", "هلا والله", answerable=False),
    # ===================== Mixed Arabic-English =====================
    c("mix", "كم الـ revenue تبع الشهر الماضي؟", intents={S}, periods=OCT),
    c("mix", "بدي الـ sales report لشهر September", intents={S}, periods=SEP),
    c("mix", "what's the stock تبع الطحينة؟", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("mix", "الـ forecast للعسل السدر next month", intents={FC}, products=["Sidr Honey 500g"], allowed=A_P),
    c("mix", "شو الـ best seller عندنا هالسنة؟", intents={S}, periods=YTD, top=True, allowed=A_P),
    c("mix", "الـ margin على زيت الزيتون قديش؟", intents={F}),
    c("mix", "compare مبيعات Q2 مع Q3", intents={S}, periods=Q2 + Q3),
    c("mix", "the price تبع المفتول", intents={PR}, products=["Maftoul 500g"], allowed=A_P),
    c("mix", "الـ reviews هالشهر كيف؟", intents={R}, periods=MTD),
    c("mix", "الـ refund policy شو هي؟", intents={D}),
    c("mix", "sales تبع امبارح", intents={S}, periods=YDAY),
    # ===================== Same question, many phrasings (paraphrase robustness) =====================
    c("en", "October takings?", intents={S}, periods=OCT),
    c("en", "how much cash came in during October", intents={S}, periods=OCT),
    c("en", "What was the turnover for the month of October?", intents={S}, periods=OCT),
    c("en", "Tell me October's revenue", intents={S}, periods=OCT),
    c("msa", "أعطني إيرادات أكتوبر", intents={S}, periods=OCT),
    c("jo", "شو دخلنا بتشرين الأول؟", intents={S}, periods=OCT),
    c("eg", "دخلنا كام في أكتوبر؟", intents={S}, periods=OCT),
    c("gulf", "كم دخلنا في شهر أكتوبر؟", intents={S}, periods=OCT),
    c("en", "Are we low on tahini?", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("en", "Do we still have tahini in the warehouse?", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("en", "tahini inventory", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("msa", "هل الطحينة متوفرة لدينا؟", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("eg", "الطحينة لسه موجودة؟", intents={I}, products=["Tahini 450g"], allowed=A_P),
    c("en", "How much do we charge for sumac?", intents={PR}, products=["Sumac 200g"], allowed=A_P),
    c("en", "sumac price", intents={PR}, products=["Sumac 200g"], allowed=A_P),
    c("en", "What's the retail price of our sumac?", intents={PR}, products=["Sumac 200g"], allowed=A_P),
    c("jo", "السماق بقديش؟", intents={PR}, products=["Sumac 200g"], allowed=A_P),
    # ===================== Harder: dates and comparisons =====================
    c("en", "Compare January, February and March sales", intents={S}, periods=JAN + FEB + MAR),
    c("en", "How did April do against March?", intents={S}, periods=APR + MAR),
    c("en", "Sales in December", intents={S}, periods=DEC25),
    c("en", "What were sales in September last year?", intents={S}, periods=SEP25),
    c("en", "October 2025 vs October 2026", intents={S}, periods=OCT25 + OCT),
    c("en", "first half of 2026 revenue", intents={S}, periods=H1),
    c("msa", "مبيعات النصف الأول من هذا العام", intents={S}, periods=H1),
    c("msa", "قارن مبيعات أكتوبر 2025 بأكتوبر 2026", intents={S}, periods=OCT25 + OCT),
    c("jo", "مبيعات كانون الأول", intents={S}, periods=DEC25),
    c("eg", "مبيعات ديسمبر اللي فات", intents={S}, periods=DEC25),
    c("gulf", "مبيعات أبريل مقارنة بمارس", intents={S}, periods=APR + MAR),
]
