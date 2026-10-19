"""What a question asks for and what it is about (rag/understanding.py), in
English and Arabic, and how a follow-up keeps the conversation's context."""
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
    assert u.extract_slots("last quarter")["period_days"] == 90
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
    follow = u.understand("and what about the last quarter?", previous=first.state())
    assert follow.follow_up and u.SALES in follow.intents and follow.slots["period_days"] == 90
