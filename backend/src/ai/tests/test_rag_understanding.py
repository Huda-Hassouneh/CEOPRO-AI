"""What a question asks for and what it is about (rag/understanding.py), in
English and Arabic, and how a follow-up keeps the conversation's context."""
from datetime import date

import pytest

from src.ai.rag import understanding as u

CATALOG = [{"product_id": "p1", "name": "Extra Virgin Olive Oil 1L", "name_alt": "زيت زيتون بكر ممتاز 1 لتر"},
           {"product_id": "p2", "name": "Medjool Dates 1kg", "name_alt": None}]


@pytest.mark.parametrize("question,expected", [
    ("How were my sales last month?", {u.SALES}),
    ("كيف كانت مبيعاتي الشهر الماضي؟", {u.SALES}),
    ("What's my profit margin?", {u.FINANCIALS}),
    ("Why do customers prefer my competitor's olive oil?", {u.CUSTOMER_PREFERENCE, u.COMPETITORS}),
    ("ليش الزبائن بيفضلوا زيت الزيتون عندي؟", {u.CUSTOMER_PREFERENCE}),
    ("Who else sells Medjool dates in Amman?", {u.PRODUCT_RESEARCH}),
    ("What licence do I need to open a pharmacy in Riyadh?", {u.REGULATION}),
    ("What is the customs duty to import olive oil into Jordan?", {u.TRADE}),
    ("هل استيراد زيت الزيتون من تركيا أرخص من شرائه محلياً؟", {u.TRADE, u.LANDED_COST}),
    ("Is it cheaper to import from Turkey than to buy locally?", {u.TRADE, u.LANDED_COST}),
    ("Should I open a new branch in Irbid?", {u.MARKET_RESEARCH, u.ADVICE}),
])
def test_intents_in_english_and_everyday_arabic(question, expected):
    assert expected <= set(u.detect_intents(question))


@pytest.mark.parametrize("message", ["hi", "Thanks!", "مرحبا", "شعلومك؟", "صباح الخير", "", "  ", "ok", "why"])
def test_greetings_and_fragments_are_not_research_questions(message):
    assert u.is_answerable(message) is False


def test_real_questions_are_answerable():
    assert u.is_answerable("what should a pharmacy stock this season?")
    assert u.is_answerable("من هو اقوى منافس بمجال المطاعم؟")


def test_trade_route_quantity_money_rates_and_terms():
    slots = u.extract_slots("Would importing olive oil from Turkey into Jordan be cheaper than buying it from a local "
                            "distributor at 4.5 JOD per bottle? Supplier quotes 95 TRY per bottle for 1000 bottles FOB, "
                            "freight 300 JOD, duty 20%, VAT 16%, exchange rate 0.0215, HS code 1509.10",
                            company_currency="JOD")
    assert slots["origin_country"] == "TR" and slots["destination_country"] == "JO"
    assert slots["quantity"] == {"value": "1000", "unit": "bottles"}
    amounts = {(a["amount"], a["currency"]) for a in slots["amounts"]}
    assert {("4.5", "JOD"), ("95", "TRY"), ("300", "JOD")} <= amounts
    assert [p["value"] for p in slots["percentages"]] == ["20", "16"]
    assert slots["fx_rate"] == "0.0215"
    assert slots["incoterm"] == "FOB"
    assert slots["hs_code"] == "150910"


def test_arabic_amounts_quantities_and_route():
    slots = u.extract_slots("المورد بيطلب ٩٥ ليرة للقنينة، 1000 قنينة من تركيا إلى الأردن، والموزع المحلي ب 4.5 دينار",
                            company_currency="JOD")
    assert slots["origin_country"] == "TR" and slots["destination_country"] == "JO"
    assert slots["quantity"]["value"] == "1000"
    assert {("95", "TRY"), ("4.5", "JOD")} <= {(a["amount"], a["currency"]) for a in slots["amounts"]}


def test_a_generic_dinar_or_riyal_follows_the_company_currency():
    assert u.extract_slots("costs 5 dinars", company_currency="KWD")["amounts"][0]["currency"] == "KWD"
    assert u.extract_slots("بسعر 12 ريال", company_currency="QAR")["amounts"][0]["currency"] == "QAR"


def test_periods_products_and_links():
    assert u.extract_slots("sales in the last 90 days")["period_days"] == 90
    assert u.extract_slots("آخر 2 أسابيع")["period_days"] == 14
    # "Last quarter" is the previous calendar quarter, not the trailing 90 days.
    assert u.extract_slots("last quarter", today=date(2026, 10, 29))["periods"] == [
        {"start": "2026-07-01", "end": "2026-10-01", "label": "Q3 2026", "kind": "quarter"}]
    slots = u.extract_slots("why is extra virgin olive oil 1l selling less? see https://example.com/page.", catalog=CATALOG)
    assert slots["products"] == [{"product_id": "p1", "name": "Extra Virgin Olive Oil 1L"}]
    assert slots["urls"] == ["https://example.com/page"]
    assert u.extract_slots("كم بعنا من زيت زيتون بكر ممتاز 1 لتر", catalog=CATALOG)["products"][0]["product_id"] == "p1"


def test_a_follow_up_keeps_the_context_and_changes_only_what_it_states():
    first = u.understand("Would importing 1000 bottles of olive oil from Turkey into Jordan be cheaper? duty 20%")
    follow = u.understand("and for 3000 bottles?", previous=first.state())
    assert follow.follow_up
    assert follow.slots["quantity"]["value"] == "3000"
    assert follow.slots["origin_country"] == "TR" and follow.slots["percentages"][0]["value"] == "20"
    assert u.LANDED_COST in follow.intents
    assert "Turkey" in follow.effective_question


def test_a_follow_up_naming_another_country_replaces_the_route():
    first = u.understand("customs duty to import olive oil from Turkey into Jordan")
    follow = u.understand("what about from Italy?", previous=first.state())
    assert follow.slots["origin_country"] == "IT" and "destination_country" not in follow.slots


def test_a_new_question_does_not_inherit_the_previous_context():
    first = u.understand("How were my sales in the last 90 days?")
    second = u.understand("ليش الزبائن بيفضلوا زيت الزيتون عندي؟", previous=first.state())
    assert not second.follow_up and "period_days" not in second.slots


def test_a_period_follow_up_carries_the_sales_intent():
    first = u.understand("How were my sales in the last 30 days?")
    follow = u.understand("and what about the last quarter?", previous=first.state(), today=date(2026, 10, 29))
    assert follow.follow_up and u.SALES in follow.intents
    # The new period replaces the earlier rolling window rather than standing next to it.
    assert [p["label"] for p in follow.slots["periods"]] == ["Q3 2026"] and "period_days" not in follow.slots


# --- routing: public research versus the company's own records -------------------

@pytest.mark.parametrize("question", [
    "Would importing my top product be cheaper than buying it locally?",
    "Total landed cost per kg for Syrian cucumbers to Amman via Jaber",
    "How can I check the customs duties for importing goods into Jordan from any country?",
    "What is the average water price?",
    "ما هو متوسط سعر المياه؟",
    "التكلفة الواصلة للخيار السوري إلى عمان عبر معبر جابر",
])
def test_questions_about_public_facts_are_sent_to_research(question):
    assert u.understand(question).needs_research


@pytest.mark.parametrize("question", [
    "How were my sales last month?", "What's my average daily revenue?", "What are the top selling products?",
    "What price should I charge for olive oil?", "ما هو هامش ربحي؟",
])
def test_questions_about_the_business_itself_stay_private(question):
    understood = u.understand(question)
    assert not understood.needs_research and not understood.public_scope


def test_landed_cost_alone_is_a_trade_question_with_its_route():
    understood = u.understand("Total landed cost per kg for Syrian cucumbers to Amman via Jaber")
    assert {u.TRADE, u.LANDED_COST} <= set(understood.intents)
    assert understood.slots["origin_country"] == "SY" and understood.slots["destination_country"] == "JO"
    assert understood.slots["route"] == "jaber"


def test_an_adjective_of_origin_is_never_read_as_the_destination():
    arabic = u.understand("التكلفة الواصلة للخيار السوري إلى عمان عبر معبر جابر")
    assert arabic.slots["origin_country"] == "SY" and arabic.slots.get("destination_country") != "SY"
    assert arabic.slots["route"] == "معبر جابر"
    assert u.understand("ship Turkish towels to Saudi Arabia").slots == {
        "countries": ["TR", "SA"], "origin_country": "TR", "destination_country": "SA"}


def test_my_top_product_is_flagged_for_the_advisor_to_resolve():
    assert u.understand("Would importing my top product be cheaper than buying it locally?").slots["top_product"]


TWO_PRODUCTS = [{"product_id": "p1", "name": "Olive Oil 1L"}, {"product_id": "p2", "name": "Za'atar"}]


def test_a_pronoun_question_keeps_the_product_just_discussed():
    first = u.understand("How is Olive Oil 1L selling?", catalog=TWO_PRODUCTS)
    follow = u.understand("what is its price?", previous=first.state(), catalog=TWO_PRODUCTS)
    assert follow.follow_up
    assert [p["product_id"] for p in follow.slots["products"]] == ["p1"]
    assert u.PRICING in follow.intents


def test_a_pronoun_question_naming_another_product_is_not_a_follow_up():
    first = u.understand("How is Olive Oil 1L selling?", catalog=TWO_PRODUCTS)
    other = u.understand("what is its price compared to Za'atar?", previous=first.state(), catalog=TWO_PRODUCTS)
    assert [p["product_id"] for p in other.slots["products"]] == ["p2"]
    assert not other.follow_up


def test_a_pronoun_without_a_product_before_it_is_not_a_follow_up():
    first = u.understand("How are sales this month?", catalog=TWO_PRODUCTS)
    assert not u.understand("what is its price?", previous=first.state(), catalog=TWO_PRODUCTS).follow_up


# --- Wordings found by the extended and held-out assistant regression sets (2026-11-05) ---

@pytest.mark.parametrize("question,expected", [
    ("How much Premium Za'atar Blend 250g do we have left?", {u.INVENTORY}),
    ("Are we running low on Freekeh 1kg?", {u.INVENTORY}),
    ("كم باقي عندنا عسل سدر؟", {u.INVENTORY}),
    ("ما هي الكمية المتوفرة من الطحينة؟", {u.INVENTORY}),
    ("How many units of Sumac 200g are available?", {u.INVENTORY}),
    ("Projected sales of Sumac 200g in the coming month", {u.FORECAST}),
    ("Can customers return labneh?", {u.DOCUMENTS}),
    ("هل يمكن استرجاع اللبنة؟", {u.DOCUMENTS}),
])
def test_everyday_wordings_of_stock_forecast_and_policy_questions(question, expected):
    assert expected <= set(u.detect_intents(question))


@pytest.mark.parametrize("question", ["بكم نبيع السماق؟", "what do we sell tahini for?",
                                      "what do we charge Sidr Honey 500g for?"])
def test_asking_what_we_sell_something_for_is_a_price_question(question):
    intents = u.detect_intents(question)
    assert u.PRICING in intents and u.SALES not in intents


@pytest.mark.parametrize("question", ["كم بعنا من السماق؟", "How much sumac did we sell for 2 JOD?", "بعنا بكام الشهر اللي فات؟"])
def test_sales_questions_that_mention_selling_stay_sales(question):
    intents = u.understand(question).intents
    assert u.SALES in intents and u.PRICING not in intents


def test_what_we_sell_asks_about_the_company_not_a_price():
    # Changed 2026-11-05: "what do we sell?" was read as a sales question; it asks about the range we offer.
    intents = u.understand("what do we sell?").intents
    assert u.COMPANY in intents and u.PRICING not in intents and u.SALES not in intents


@pytest.mark.parametrize("question, expected", [
    ("What price do we sell Freekeh 1kg at?", {u.PRICING}), ("ما سعر بيع الفريكة؟", {u.PRICING}),
    ("إذا الزبون بدو يرجع لبنة شو بصير؟", {u.DOCUMENTS}),
    ("Is our honey overpriced compared to other shops?", {u.COMPETITORS}),
    ("Who sells olive oil cheaper than us?", {u.COMPETITORS, u.PRICING}),  # a price comparison: pricing is fair too
    ("شو رأي الزباين بالتوصيل؟", {u.REVIEWS}),
])
def test_the_intent_is_read_without_extra_needs_from_words_used_in_another_sense(question, expected):
    assert set(u.understand(question).intents) - {u.PRODUCTS} == expected


@pytest.mark.parametrize("message", ["مبيعات تموز", "stock?", "sales"])
def test_a_short_message_naming_a_business_need_is_a_question(message):
    assert u.is_answerable(message)


@pytest.mark.parametrize("question, expected", [
    # debts and payments are read from the invoices (sales records), never as stock left
    ("مين الناس اللي لسا ما دفعوا؟", {u.SALES}),
    ("قديش ضايل إلنا عند الزباين؟", {u.SALES}),
    ("قديش مجموع الديون؟", {u.SALES}),
    ("الـ outstanding invoices عنا كم؟", {u.SALES}),
    # orders ("طلبيات") are orders received, not future demand ("الطلب")
    ("عدد الطلبيات تبع مبارح", {u.SALES}),
    ("لازم نعمل طلبية من المورد؟", {u.INVENTORY}),
    # Jordanian stock words
    ("فش طحينة؟", {u.INVENTORY}),
    ("اي اشي قرب يفضى؟", {u.INVENTORY}),
    ("قديش بعنا زعتر وكم ضل؟", {u.SALES, u.INVENTORY}),
    # net profit and expenses
    ("قديش دخلنا الصافي؟", {u.FINANCIALS}),
    ("شو المصروف الشهري تبعنا؟", {u.FINANCIALS}),
    # "تبعنا" (our) is not "بعنا" (we sold); "أسابيع" (weeks) is not "بيع"
    ("التقييم تبعنا نزل؟", {u.REVIEWS}),
    ("شو التوقعات للأسابيع الجاية؟", {u.FORECAST}),
    # the terms of selling are a policy question
    ("شو سياسة البيع بالتقسيط؟", {u.DOCUMENTS}),
    ("بنبيع بالجملة؟ شو الشروط؟", {u.DOCUMENTS}),
    ("في حدا زعلان منا؟", {u.REVIEWS}),
])
def test_jordanian_everyday_wordings(question, expected):
    assert set(u.detect_intents(question)) == expected


def test_a_trailing_vocative_keeps_thanks_small_talk():
    assert u.is_answerable("تسلم يا رب") is False
    assert u.detect_intents("يعطيك العافية يا غالي") == []   # "dear", not "expensive"


@pytest.mark.parametrize("message", ["إزيك عامل إيه", "كيفك، شو الأخبار"])
def test_greetings_strung_together_are_small_talk(message):
    assert u.is_answerable(message) is False
