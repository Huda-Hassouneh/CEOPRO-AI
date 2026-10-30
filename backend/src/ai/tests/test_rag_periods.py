"""
Periods, intents and product names the assistant reads from a question
(rag/periods.py, rag/understanding.py) - the step that decided which records
were queried. Each case here was a real failure: "March 2026" reached the
model as "the last 30 days", "last month" as a rolling window, "customers"
as a customs question, "زيت الزيتون" as no product at all.
"""
from datetime import date

import pytest

from src.ai.rag import periods as P
from src.ai.rag import understanding as u

TODAY = date(2026, 10, 29)


def _labels(question):
    return [p["label"] for p in P.resolve_periods(u._norm(question), TODAY)]


@pytest.mark.parametrize("question, expected", [
    ("How much did we sell in March 2026?", ["March 2026"]),
    ("sales in March?", ["March 2026"]),
    ("sales in December", ["December 2025"]),  # the most recent December that has started
    ("What was my revenue last month?", ["September 2026"]),
    ("revenue this month", ["October 2026 to date"]),
    ("sales this year", ["2026 to date"]),
    ("sales last year", ["2025"]),
    ("What were my sales in 2025?", ["2025"]),
    ("Compare my sales in Q2 2026 with Q2 2025", ["Q2 2026", "Q2 2025"]),
    ("first quarter of 2026", ["Q1 2026"]),
    ("last quarter", ["Q3 2026"]),
    ("this month vs last month", ["October 2026 to date", "September 2026"]),
    ("September vs August", ["September 2026", "August 2026"]),
    ("June vs May", ["June 2026", "May 2026"]),
    ("sales between 1 May and 15 June 2026", ["2026-05-01 to 2026-06-15"]),
    ("sales from 2026-05-01 to 2026-05-31", ["2026-05-01 to 2026-05-31"]),
    ("How were sales yesterday?", ["yesterday (2026-10-28)"]),
    ("كم كانت مبيعاتي في شهر آذار؟", ["March 2026"]),
    ("كم كانت مبيعاتي الشهر الماضي؟", ["September 2026"]),
    ("مبيعات هالشهر", ["October 2026 to date"]),
    ("مبيعات شهر 9", ["September 2026"]),
    ("مبيعات أيلول مقارنة بآب", ["September 2026", "August 2026"]),
    ("مبيعات الربع الأول", ["Q1 2026"]),
    ("مبيعات سنة 2025", ["2025"]),
    ("من 1/5/2026 إلى 15/6/2026", ["2026-05-01 to 2026-06-15"]),
    ("مبيعاتي بين ١ أيار و ١٥ حزيران", ["2026-05-01 to 2026-06-15"]),
])
def test_named_periods_are_exact_calendar_dates(question, expected):
    assert _labels(question) == expected


@pytest.mark.parametrize("question", [
    "what may happen next month",   # "may" the verb, and a future month has no sales
    "الباب مكسور",                   # "باب" is a door, not August
    "sales in the last 3 months",   # a rolling window, kept as period_days
])
def test_words_that_only_look_like_periods_are_not_periods(question):
    assert _labels(question) == []


def test_calendar_month_dates_and_the_period_before():
    march = P.resolve_periods("march 2026", TODAY)[0]
    assert (march["start"], march["end"]) == ("2026-03-01", "2026-04-01")  # end exclusive
    assert P.previous_period(march)["label"] == "February 2026"
    q2 = P.resolve_periods("q2 2025", TODAY)[0]
    assert P.previous_period(q2)["label"] == "Q1 2025"
    month_to_date = P.resolve_periods("this month", TODAY)[0]
    before = P.previous_period(month_to_date)
    assert (before["start"], before["end"]) == ("2026-09-01", "2026-09-30")  # 1-29 Sep vs 1-29 Oct


def test_rolling_windows_keep_their_meaning():
    assert u.extract_slots("sales in the last 90 days", today=TODAY)["period_days"] == 90
    assert u.extract_slots("past 3 months", today=TODAY)["period_days"] == 90
    assert "periods" not in u.extract_slots("sales in the last 90 days", today=TODAY)


@pytest.mark.parametrize("question, intents", [
    ("How much did we sell in March 2026?", {u.SALES}),
    ("how many units did we sell?", {u.SALES}),
    ("What do customers say about us?", {u.REVIEWS}),
    ("Summarise positive and negative customer feedback", {u.REVIEWS}),
    ("Tell me about my company", {u.COMPANY}),
    ("Who are my top 5 customers this year?", {u.SALES}),
    ("Compare March 2024 with February 2024", {u.SALES}),  # a bare period comparison is about sales
])
def test_intents(question, intents):
    found = set(u.understand(question, today=TODAY).intents)
    assert intents <= found
    # "customers" is not "customs": a customer question never becomes a trade/customs one.
    assert u.TRADE not in found and u.LANDED_COST not in found


def test_keywords_match_at_the_start_of_a_word():
    assert u.SALES not in u.detect_intents("what are our wholesale terms?")
    assert u.REGULATION not in u.detect_intents("is the syntax right?")
    assert u.REVIEWS in u.detect_intents("show me the reviews")


CATALOG = [
    {"product_id": "p1", "name": "Extra Virgin Olive Oil 1L", "name_alt": "زيت زيتون بكر ممتاز 1 لتر"},
    {"product_id": "p2", "name": "Olive Oil Tin 4L", "name_alt": "تنكة زيت زيتون 4 لتر"},
    {"product_id": "p3", "name": "Green Olives Jar 650g", "name_alt": "زيتون أخضر 650 غرام"},
    {"product_id": "p4", "name": "Sidr Honey 500g", "name_alt": "عسل سدر 500 غرام"},
    {"product_id": "p5", "name": "Medjool Dates 1kg", "name_alt": "تمر مجهول 1 كيلو"},
]


@pytest.mark.parametrize("question, ids", [
    ("What is the demand forecast for olive oil next month?", ["p1", "p2"]),
    ("كم المخزون عندي من زيت الزيتون؟", ["p1", "p2"]),
    ("how is the honey selling", ["p4"]),
    ("Do we have green olives in stock?", ["p3"]),
    ("sidr honey 500g sales", ["p4"]),          # a full name wins over partial matches
])
def test_partial_product_names_find_the_catalogue_products(question, ids):
    found = u.extract_slots(question, catalog=CATALOG, today=TODAY).get("products") or []
    assert [p["product_id"] for p in found] == ids


def test_a_size_or_packaging_word_alone_names_no_product():
    assert "products" not in u.extract_slots("the 1kg pack", catalog=CATALOG, today=TODAY)


def test_a_follow_up_replaces_the_period_or_adds_to_it_when_comparing():
    first = u.understand("What were my sales in September 2026?", today=TODAY)
    second = u.understand("and in August?", previous=first.state(), today=TODAY)
    assert second.follow_up and u.SALES in second.intents
    assert [p["label"] for p in second.slots["periods"]] == ["August 2026"]
    third = u.understand("which product sold the most then?", previous=second.state(), today=TODAY)
    assert third.follow_up and [p["label"] for p in third.slots["periods"]] == ["August 2026"]
    compared = u.understand("how does that compare with July?", previous=second.state(), today=TODAY)
    assert [p["label"] for p in compared.slots["periods"]] == ["August 2026", "July 2026"]


def test_an_elliptical_follow_up_keeps_the_product():
    first = u.understand("What's the price of Sidr Honey 500g?", catalog=CATALOG, today=TODAY)
    second = u.understand("how many did we sell last month?", previous=first.state(), catalog=CATALOG, today=TODAY)
    assert second.follow_up and u.SALES in second.intents
    assert second.slots["products"][0]["product_id"] == "p4"
    assert second.slots["periods"][0]["label"] == "September 2026"
    third = u.understand("and its stock?", previous=second.state(), catalog=CATALOG, today=TODAY)
    assert u.INVENTORY in third.intents and third.slots["products"][0]["product_id"] == "p4"


@pytest.mark.parametrize("follow_up, expected", [
    ("and the month before?", ["August 2026"]),
    ("and the previous month", ["August 2026"]),          # relative to September, not "last month" from today
    ("والشهر اللي قبله؟", ["August 2026"]),
    ("what about the same period last year?", ["September 2025"]),  # not the whole of 2025
    ("what about last month?", ["September 2026"]),
])
def test_a_follow_up_can_name_a_period_relative_to_the_one_discussed(follow_up, expected):
    first = u.understand("What were my sales in September 2026?", today=TODAY)
    second = u.understand(follow_up, previous=first.state(), today=TODAY)
    assert second.follow_up and u.SALES in second.intents
    assert [p["label"] for p in second.slots["periods"]] == expected
