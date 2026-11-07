"""
KEEL - question-understanding benchmark (rag/understanding.py), offline.

The assistant answers with exact database figures once it has read the question
right: what is asked (intent), for which dates (period) and about which product.
This benchmark scores that reading alone - no database, model or network - so
it runs in a second and can be used while changing the rules.

Two sets:

- DEV: the wordings the rules are developed against.
- HOLDOUT: written at the same time as DEV but never used for changing the
  rules; its score estimates how well the reading generalises to questions
  nobody tested. Changing rules to fix a HOLDOUT case spends it: replace the
  case with a new wording afterwards.

A case passes when every field it specifies matches:

- ``intents``: all of these are detected; ``not_intents``: none of these are.
- ``periods``: exactly these calendar periods, as (start, end-exclusive) dates.
- ``days``: this rolling window ("the last 30 days").
- ``products``: these catalogue products are named (others may be too).
- ``top``: a product ranking is (or is not) asked for - the `top_product` slot or the advisor's
  ranking words, as production decides it (advisor._RANKING).
- ``answerable``: the message is (or is not) a question to research.

    cd backend && python -m src.ai.rag.eval.understanding_benchmark [--set dev|holdout|all] [--show-failures]
"""
import argparse
from datetime import date

from src.ai.rag import understanding as U

TODAY = date(2026, 11, 5)  # a Thursday

CATALOG = [{"product_id": f"p{i}", "name": en, "name_alt": ar} for i, (en, ar) in enumerate([
    ("Arabic Coffee with Cardamom 250g", "قهوة عربية بالهيل 250 غرام"),
    ("Black Olives Jar 650g", "زيتون أسود 650 غرام"),
    ("Coarse Bulgur 1kg", "برغل خشن 1 كيلو"),
    ("Early Harvest Olive Oil 750ml", "زيت زيتون قطفة أولى 750 مل"),
    ("Extra Virgin Olive Oil 1L", "زيت زيتون بكر ممتاز 1 لتر"),
    ("Extra Virgin Olive Oil 500ml", "زيت زيتون بكر ممتاز 500 مل"),
    ("Freekeh 1kg", "فريكة 1 كيلو"),
    ("Fresh Labneh (per kg)", "لبنة طازجة (كيلو)"),
    ("Green Olives Jar 650g", "زيتون أخضر مرصوص 650 غرام"),
    ("Hibiscus (Karkadeh) 200g", "كركديه 200 غرام"),
    ("Loose Za'atar (per kg)", "زعتر فرط (كيلو)"),
    ("Maftoul 500g", "مفتول 500 غرام"),
    ("Medjool Dates 1kg", "تمر مجهول 1 كيلو"),
    ("Medjool Dates Gift Box 500g", "علبة هدايا تمر مجهول 500 غرام"),
    ("Nabulsi Cheese 500g", "جبنة نابلسية 500 غرام"),
    ("Nabulsi Olive Oil Soap 6-pack", "صابون زيت زيتون نابلسي 6 قطع"),
    ("Olive Oil Tin 4L", "تنكة زيت زيتون 4 لتر"),
    ("Pomegranate Molasses 300ml", "دبس رمان 300 مل"),
    ("Premium Za'atar Blend 250g", "زعتر بلدي ممتاز 250 غرام"),
    ("Qamar al-Din Apricot Paste 400g", "قمر الدين 400 غرام"),
    ("Ramadan Gift Hamper", "سلة رمضان"),
    ("Seven Spices Mix 150g", "بهارات سبعة 150 غرام"),
    ("Sidr Honey 500g", "عسل سدر 500 غرام"),
    ("Sumac 200g", "سماق 200 غرام"),
    ("Tahini 450g", "طحينة 450 غرام"),
    ("Tamarind Drink Concentrate 1L", "شراب تمر هندي 1 لتر"),
    ("Turkish Coffee Medium Roast 500g", "قهوة تركية تحميص وسط 500 غرام"),
    ("Wildflower Honey 1kg", "عسل زهور برية 1 كيلو"),
])]

S, F, P, PR, I, FC = U.SALES, U.FINANCIALS, U.PRODUCTS, U.PRICING, U.INVENTORY, U.FORECAST
C, R, D, CO, T = U.COMPETITORS, U.REVIEWS, U.DOCUMENTS, U.COMPANY, U.TRADE

OCT = [("2026-10-01", "2026-11-01")]
SEP = [("2026-09-01", "2026-10-01")]
AUG = [("2026-08-01", "2026-09-01")]
JUL = [("2026-07-01", "2026-08-01")]
JUN = [("2026-06-01", "2026-07-01")]
MAR = [("2026-03-01", "2026-04-01")]
Q2, Q3 = [("2026-04-01", "2026-07-01")], [("2026-07-01", "2026-10-01")]
Y2025 = [("2025-01-01", "2026-01-01")]
YTD = [("2026-01-01", "2026-11-06")]
MTD = [("2026-11-01", "2026-11-06")]
YESTERDAY = [("2026-11-04", "2026-11-05")]
TODAY_P = [("2026-11-05", "2026-11-06")]
H1 = [("2026-01-01", "2026-07-01")]
SINCE_JUNE = [("2026-06-01", "2026-11-06")]


def case(q, **expect):
    return {"q": q, **expect}


DEV = [
    # --- sales, English ---
    case("What was my revenue last month?", intents={S}, periods=OCT),
    case("how much did we sell in september", intents={S}, periods=SEP),
    case("Sales for August 2026", intents={S}, periods=AUG),
    case("Show me last month's turnover", intents={S}, periods=OCT),
    case("What did we make yesterday?", intents={S}, periods=YESTERDAY),
    case("How are sales today?", intents={S}, periods=TODAY_P),
    case("revenue this month so far", intents={S}, periods=MTD),
    case("total sales this year", intents={S}, periods=YTD),
    case("What were our sales in 2025?", intents={S}, periods=Y2025),
    case("Q3 revenue", intents={S}, periods=Q3),
    case("How did the business do last quarter?", intents={S}, periods=Q3),
    case("Revenue in the first half of the year", intents={S}, periods=H1),
    case("sales since June", intents={S}, periods=SINCE_JUNE),
    case("How much money came in during July?", intents={S}, periods=JUL),
    case("What were takings in October?", intents={S}, periods=OCT),
    case("Sales over the last 30 days", intents={S}, days=30),
    case("compare September and August sales", intents={S}, periods=SEP + AUG),
    case("Was October better than September?", intents={S}, periods=OCT + SEP),
    case("How many orders did we get last month?", intents={S}, periods=OCT),
    case("How many invoices in March?", intents={S}, periods=MAR),
    case("what's our average order value last month", intents={S}, periods=OCT),
    case("Monthly sales this year", intents={S}, periods=YTD),
    case("did sales go up or down last month?", intents={S}, periods=OCT),
    case("What was the busiest month this year?", intents={S}, periods=YTD),
    case("How much did we earn in Q2?", intents={S}, periods=Q2),
    # --- sales, Arabic dialects ---
    case("كم كانت مبيعاتنا الشهر الماضي؟", intents={S}, periods=OCT),
    case("قديش بعنا بشهر تشرين الأول؟", intents={S}, periods=OCT),
    case("كم بعنا امبارح؟", intents={S}, periods=YESTERDAY),
    case("المبيعات النهارده عاملة كام؟", intents={S}, periods=TODAY_P),
    case("شنو مبيعاتنا هالشهر؟", intents={S}, periods=MTD),
    case("إجمالي الإيرادات لهذا العام", intents={S}, periods=YTD),
    case("مبيعات سنة 2025", intents={S}, periods=Y2025),
    case("إيرادات الربع الثالث", intents={S}, periods=Q3),
    case("كم دخلنا في شهر 8؟", intents={S}, periods=AUG),
    case("قارن مبيعات أيلول مع آب", intents={S}, periods=SEP + AUG),
    case("كم طلب جانا الشهر الماضي؟", intents={S}, periods=OCT),
    case("المبيعات من بداية السنة", intents={S}, periods=YTD),
    case("مبيعات آخر 30 يوم", intents={S}, days=30),
    case("كيف كان أداء المبيعات في يوليو؟", intents={S}, periods=JUL),
    case("الغلة الشهر اللي فات قديش؟", intents={S}, periods=OCT),
    # --- products and rankings ---
    case("What's my best selling product?", intents={S}, top=True),
    case("Which product sold the most units last month?", intents={S}, periods=OCT, top=True),
    case("top 5 products by revenue this year", intents={S}, periods=YTD, top=True),
    case("Which items are selling the least?", intents={S}),
    case("How many units of Tahini 450g did we sell in September?", intents={S}, periods=SEP, products=["Tahini 450g"]),
    case("sidr honey sales last month", intents={S}, periods=OCT, products=["Sidr Honey 500g"]),
    case("How is the olive oil tin selling?", intents={S}, products=["Olive Oil Tin 4L"]),
    case("units of maftoul sold in august", intents={S}, periods=AUG, products=["Maftoul 500g"]),
    case("كم كيلو لبنة بعنا الشهر الماضي؟", intents={S}, periods=OCT, products=["Fresh Labneh (per kg)"]),
    case("شو أكثر منتج بيتباع عنا؟", intents={S}, top=True),
    case("ايه أكتر حاجة بتتباع؟", intents={S}, top=True),
    case("المنتج الأقل مبيعاً", intents={S}),
    case("كم علبة تمر مجهول بعنا في أيلول؟", intents={S}, periods=SEP, products=["Medjool Dates 1kg"]),
    case("مبيعات عسل السدر هالسنة", intents={S}, periods=YTD, products=["Sidr Honey 500g"]),
    case("How many products do we have?", intents={P}),
    case("list my products", intents={P}),
    case("كم منتج عندي؟", intents={P}),
    # --- inventory ---
    case("What's the stock of Freekeh 1kg?", intents={I}, products=["Freekeh 1kg"]),
    case("How much tahini do we have left?", intents={I}, products=["Tahini 450g"]),
    case("Which products are low in stock?", intents={I}),
    case("What's out of stock?", intents={I}),
    case("Do we need to reorder sumac?", intents={I}, products=["Sumac 200g"]),
    case("how many medjool dates 1kg in the warehouse", intents={I}, products=["Medjool Dates 1kg"]),
    case("Is Sidr Honey 500g available?", intents={I}, products=["Sidr Honey 500g"]),
    case("كم المخزون من الطحينة؟", intents={I}, products=["Tahini 450g"]),
    case("شو المنتجات اللي قربت تخلص؟", intents={I}),
    case("فيه عندنا زعتر بلدي؟", intents={I}, products=["Premium Za'atar Blend 250g"]),
    case("كام علبة فريكة فاضلة؟", intents={I}, products=["Freekeh 1kg"]),
    case("لازم نطلب سماق جديد؟", intents={I}, products=["Sumac 200g"]),
    # --- forecast ---
    case("What's the demand forecast for tahini?", intents={FC}, products=["Tahini 450g"]),
    case("How many Sidr Honey 500g will we sell next month?", intents={FC}, products=["Sidr Honey 500g"]),
    case("Predict sales of freekeh for the next 30 days", intents={FC}, products=["Freekeh 1kg"]),
    case("expected demand next month", intents={FC}),
    case("Which products will sell the most next month?", intents={FC}),
    case("كم متوقع نبيع طحينة الشهر الجاي؟", intents={FC}, products=["Tahini 450g"]),
    case("توقعات الطلب على التمر", intents={FC}),
    case("هنبيع كام فريكة الشهر الجاي؟", intents={FC}, products=["Freekeh 1kg"]),
    # --- pricing ---
    case("What's the price of Sumac 200g?", intents={PR}, products=["Sumac 200g"]),
    case("how much do we charge for maftoul", intents={PR}, products=["Maftoul 500g"]),
    case("How much is the Ramadan Gift Hamper?", intents={PR}, products=["Ramadan Gift Hamper"]),
    case("Is our tahini price competitive?", intents={PR}, products=["Tahini 450g"]),
    case("قديش سعر الطحينة؟", intents={PR}, products=["Tahini 450g"]),
    case("بكام بنبيع الفريكة؟", intents={PR}, products=["Freekeh 1kg"]),
    case("سعر عسل السدر كم؟", intents={PR}, products=["Sidr Honey 500g"]),
    # --- profit ---
    case("What was my gross profit last month?", intents={F}, periods=OCT),
    case("Which products have the best margin?", intents={F}),
    case("Are we losing money on any product?", intents={F}),
    case("كم ربحنا الشهر الماضي؟", intents={F}, periods=OCT),
    case("شو هامش الربح على زيت الزيتون؟", intents={F}),
    # --- competitors ---
    case("Who are my competitors?", intents={C}),
    case("How do my prices compare with competitors?", intents={C, PR}),
    case("مين المنافسين تبعي؟", intents={C}),
    case("أسعاري مقارنة بالمنافسين", intents={C, PR}),
    # --- reviews ---
    case("What do customers say about us?", intents={R}, not_intents={T}),
    case("How many reviews did we get this year?", intents={R}, periods=YTD),
    case("Are customers happy with our service?", intents={R}, not_intents={T}),
    case("any complaints recently?", intents={R}),
    case("شو رأي الزبائن فينا؟", intents={R}),
    case("الناس بتقول ايه عننا؟", intents={R}),
    case("كم تقييم جانا هالسنة؟", intents={R}, periods=YTD),
    # --- documents and company ---
    case("What is our returns policy?", intents={D}),
    case("How much is delivery to Zarqa?", intents={D}),
    case("Can I get a refund on opened products?", intents={D}),
    case("سياسة الإرجاع عندنا شو هي؟", intents={D}),
    case("كم أجرة التوصيل؟", intents={D}),
    case("Tell me about my company", intents={CO}),
    case("when were we founded?", intents={CO}),
    case("احكيلي عن شركتي", intents={CO}),
    # --- small talk and fragments ---
    case("hi", answerable=False),
    case("thanks!", answerable=False),
    case("مرحبا", answerable=False),
    case("مبيعات أيلول", answerable=True, intents={S}, periods=SEP),
    case("stock?", answerable=True, intents={I}),
]

# Never used to change the rules (see module docstring).
HOLDOUT = [
    case("What did we bring in last month?", intents={S}, periods=OCT),
    case("total revenue for september 2026", intents={S}, periods=SEP),
    case("How were sales in the second quarter?", intents={S}, periods=Q2),
    case("revenue yesterday", intents={S}, periods=YESTERDAY),
    case("sales so far this month", intents={S}, periods=MTD),
    case("year to date sales", intents={S}, periods=YTD),
    case("how much did the shop make in 2025", intents={S}, periods=Y2025),
    case("What were gross sales in July?", intents={S}, periods=JUL),
    case("compare Q2 and Q3", intents={S}, periods=Q2 + Q3),
    case("number of orders in august", intents={S}, periods=AUG),
    case("How did October go?", intents={S}, periods=OCT),
    case("sales trend by month this year", intents={S}, periods=YTD),
    case("revenue since june", intents={S}, periods=SINCE_JUNE),
    case("كم كانت إيراداتنا في أيلول؟", intents={S}, periods=SEP),
    case("مبيعات امبارح", intents={S}, periods=YESTERDAY),
    case("قديش بعنا اليوم؟", intents={S}, periods=TODAY_P),
    case("المبيعات في الربع التاني", intents={S}, periods=Q2),
    case("كم كان الدخل السنة الماضية؟", intents={S}, periods=Y2025),
    case("بدي أعرف مبيعات شهر تموز", intents={S}, periods=JUL),
    case("عايز أعرف المبيعات الشهر اللي فات", intents={S}, periods=OCT),
    case("قارن مبيعات تشرين الأول بأيلول", intents={S}, periods=OCT + SEP),
    case("which product made the most money this year?", intents={S}, periods=YTD, top=True),
    case("best seller in september", intents={S}, periods=SEP, top=True),
    case("how many tahini did we sell last month", intents={S}, periods=OCT, products=["Tahini 450g"]),
    case("Freekeh 1kg sales in Q3", intents={S}, periods=Q3, products=["Freekeh 1kg"]),
    case("how are the green olives selling?", intents={S}, products=["Green Olives Jar 650g"]),
    case("كم بعنا مفتول في آب؟", intents={S}, periods=AUG, products=["Maftoul 500g"]),
    case("مين أكثر منتج بيجيب فلوس؟", intents={S}, top=True),
    case("أكثر شي انباع الشهر الماضي", intents={S}, periods=OCT, top=True),
    case("how much sumac is in stock?", intents={I}, products=["Sumac 200g"]),
    case("are we out of freekeh?", intents={I}, products=["Freekeh 1kg"]),
    case("what should I restock?", intents={I}),
    case("stock levels for olive oil tin 4l", intents={I}, products=["Olive Oil Tin 4L"]),
    case("كم باقي من التمر المجهول؟", intents={I}, products=["Medjool Dates 1kg"]),
    case("المخزون الحالي من عسل السدر", intents={I}, products=["Sidr Honey 500g"]),
    case("في عندنا لبنة؟", intents={I}, products=["Fresh Labneh (per kg)"]),
    case("forecast for medjool dates 1kg", intents={FC}, products=["Medjool Dates 1kg"]),
    case("how much tahini will we need next month?", intents={FC}, products=["Tahini 450g"]),
    case("demand prediction for the coming weeks", intents={FC}),
    case("شو التوقعات للشهر الجاي؟", intents={FC}),
    case("كم متوقع نبيع عسل سدر؟", intents={FC}, products=["Sidr Honey 500g"]),
    case("what does the freekeh cost the customer?", intents={PR}, products=["Freekeh 1kg"]),
    case("price list for our honey", intents={PR}),
    case("what's sumac selling for?", intents={PR}, products=["Sumac 200g"]),
    case("بكم الطحينة؟", intents={PR}, products=["Tahini 450g"]),
    case("سعر الفريكة عندنا", intents={PR}, products=["Freekeh 1kg"]),
    case("profit for Q3", intents={F}, periods=Q3),
    case("which product earns us the most margin?", intents={F}),
    case("كم كان صافي الربح هالسنة؟", intents={F}, periods=YTD),
    case("who else sells tahini near us?", intents={U.PRODUCT_RESEARCH}),
    case("list the competitors we track", intents={C}),
    case("are competitors cheaper than us on tahini?", intents={C}),
    case("what are customers complaining about?", intents={R}),
    case("what's our average rating?", intents={R}),
    case("customer satisfaction this year", intents={R}, periods=YTD),
    case("شو بيقولوا الزبائن عن الخدمة؟", intents={R}),
    case("تقييمات العملاء", intents={R}),
    case("do we offer refunds?", intents={D}),
    case("what's the delivery fee?", intents={D}),
    case("هل في استرجاع للمنتجات؟", intents={D}),
    case("what does our company do?", intents={CO}),
    case("نبذة عن شركتنا", intents={CO}),
    case("good morning", answerable=False),
    case("شكرا جزيلا", answerable=False),
    case("ارباح تموز", answerable=True, intents={F}, periods=JUL),
]


def evaluate(cases):
    results = []
    for c in cases:
        u = U.understand(c["q"], catalog=CATALOG, company_currency="JOD", today=TODAY)
        problems = []
        intents = set(u.intents)
        if "intents" in c and not c["intents"] <= intents:
            problems.append(f"intents {sorted(intents)} lack {sorted(c['intents'] - intents)}")
        if "not_intents" in c and c["not_intents"] & intents:
            problems.append(f"unwanted intents {sorted(c['not_intents'] & intents)}")
        if "periods" in c:
            got = [(p["start"], p["end"]) for p in u.slots.get("periods") or []]
            if sorted(got) != sorted(c["periods"]):
                problems.append(f"periods {got} != {c['periods']}")
        if "days" in c and u.slots.get("period_days") != c["days"]:
            problems.append(f"days {u.slots.get('period_days')} != {c['days']}")
        if "products" in c:
            got = {p["name"] for p in u.slots.get("products") or []}
            if not set(c["products"]) <= got:
                problems.append(f"products {sorted(got)} lack {sorted(set(c['products']) - got)}")
        if "top" in c:
            from src.ai.rag import advisor
            ranking = bool(u.slots.get("top_product")) or bool(advisor._RANKING.search(U._norm(u.effective_question)))
            if ranking != c["top"]:
                problems.append(f"ranking {ranking} != {c['top']}")
        if "answerable" in c and U.is_answerable(c["q"]) != c["answerable"]:
            problems.append(f"answerable {not c['answerable']} != {c['answerable']}")
        results.append({"q": c["q"], "passed": not problems, "problems": problems})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=("dev", "holdout", "all"), default="dev")
    parser.add_argument("--show-failures", action="store_true")
    args = parser.parse_args()
    sets = {"dev": [("dev", DEV)], "holdout": [("holdout", HOLDOUT)],
            "all": [("dev", DEV), ("holdout", HOLDOUT)]}[args.set]
    for name, cases in sets:
        results = evaluate(cases)
        passed = sum(r["passed"] for r in results)
        print(f"{name}: {passed}/{len(results)} ({100 * passed / len(results):.1f}%)")
        if args.show_failures:
            for r in results:
                if not r["passed"]:
                    print(f"  FAIL {r['q']}: {'; '.join(r['problems'])}")


if __name__ == "__main__":
    main()
