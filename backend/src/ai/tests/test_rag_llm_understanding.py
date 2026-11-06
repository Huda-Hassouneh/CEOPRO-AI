"""The model as a second reader behind the rules (rag/llm_understanding.py): it fills only what the rules left
empty, its periods become exact dates through periods.py, it can name only catalogue products, and any failure
leaves the rules' reading unchanged."""
import json
from datetime import date

import pytest

from src.ai.rag import llm_client, llm_understanding as L, understanding as U

TODAY = date(2026, 11, 5)
CATALOG = [{"product_id": "p1", "name": "Tahini 450g", "name_alt": "طحينة 450 غرام"},
           {"product_id": "p2", "name": "Sumac 200g", "name_alt": "سماق 200 غرام"}]


def _model_says(monkeypatch, answer):
    calls = []

    def fake(messages, **kwargs):
        calls.append((messages, kwargs))
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)

    monkeypatch.setattr(llm_client, "chat_completion", fake)
    return calls


def test_it_is_off_unless_switched_on():
    assert L.MODE == "off" or L.enabled() == (L.MODE == "gaps")


def test_the_model_reading_is_validated(monkeypatch):
    calls = _model_says(monkeypatch, {"intents": ["sales", "made_up"], "periods": ["Q2 2026", "nonsense"],
                                      "products": ["Tahini 450g", "Invented Product"], "ranking": True, "small_talk": False})
    reading = L.read("كيف كانت مبيعات الطحينة بالربع التاني", CATALOG, TODAY)
    assert reading["intents"] == ["sales"]                         # unknown intents dropped
    assert [(p["start"], p["end"]) for p in reading["periods"]] == [("2026-04-01", "2026-07-01")]  # deterministic dates
    assert reading["products"] == [{"product_id": "p1", "name": "Tahini 450g"}]  # never a name it made up
    assert calls[0][1]["json_mode"] is True and calls[0][1]["temperature"] == 0


@pytest.mark.parametrize("failure", [llm_client.LLMError("down"), "not json", "[1, 2]"])
def test_any_model_failure_leaves_the_rules_alone(monkeypatch, failure):
    _model_says(monkeypatch, failure)
    assert L.read("anything", CATALOG, TODAY) is None
    u = U.understand("What was revenue last month?", catalog=CATALOG, today=TODAY)
    before = (list(u.intents), dict(u.slots))
    assert (lambda x: (x.intents, x.slots))(L.fill_gaps(u, None)) == before


def test_only_what_the_rules_left_empty_is_filled():
    u = U.understand("What was revenue last month?", catalog=CATALOG, today=TODAY)
    rules_periods = u.slots["periods"]
    reading = {"intents": ["forecast"], "periods": [{"start": "2025-01-01", "end": "2026-01-01"}], "period_days": None,
               "products": [{"product_id": "p2", "name": "Sumac 200g"}], "ranking": False, "small_talk": False}
    filled = L.fill_gaps(u, reading)
    assert filled.intents == [U.SALES]                 # the rules found an intent: kept
    assert filled.slots["periods"] == rules_periods    # and a period: kept
    assert filled.slots["products"][0]["name"] == "Sumac 200g"  # no product: the model's
    assert filled.slots["read_by_model"] == ["products"]


def test_an_unknown_wording_gets_the_models_intent_and_period():
    u = U.understand("how did the shop do in the dreary month of 9/2026 lol", catalog=CATALOG, today=TODAY)
    u.intents, u.slots = [], {}
    reading = {"intents": ["sales"], "periods": [{"start": "2026-09-01", "end": "2026-10-01"}], "period_days": None,
               "products": [], "ranking": False, "small_talk": False}
    filled = L.fill_gaps(u, reading)
    assert filled.intents == ["sales"] and filled.slots["periods"][0]["start"] == "2026-09-01"


def test_small_talk_is_the_models_call_only_when_the_rules_found_no_need():
    talk = {"intents": [], "periods": [], "period_days": None, "products": [], "ranking": False, "small_talk": True}
    assert L.answerable(True, rules_found_intent=False, reading=talk) is False   # "thanks, that's helpful"
    assert L.answerable(True, rules_found_intent=True, reading=talk) is True     # the rules saw a business need
    assert L.answerable(False, rules_found_intent=False, reading=None) is False


def test_a_large_catalogue_is_cut_to_the_closest_names():
    big = [{"product_id": str(i), "name": f"Item {i}", "name_alt": None} for i in range(500)] + CATALOG
    shown = L.catalog_candidates("كم بعنا طحينة؟", big)
    assert len(shown) == L.MAX_CATALOG_NAMES and shown[0]["name"] == "Tahini 450g"


@pytest.mark.parametrize("raw, expected", [
    ('{"intents": ["sales"]}', {"intents": ["sales"]}),
    ('Sure:\n```json\n{"intents": ["sales"]}\n```', {"intents": ["sales"]}),   # wrapped in a code fence
    ('{"intents": ["sales"', None),                                           # cut off
    ("[1, 2]", None), ("", None), (None, None),
])
def test_only_a_complete_json_object_is_accepted(raw, expected):
    assert L.parse_json_object(raw) == expected


def test_a_broken_answer_is_asked_again_once(monkeypatch):
    replies = iter(['{"intents": ["sales"', '{"intents": ["sales"], "periods": [], "products": []}'])
    calls = []
    monkeypatch.setattr(llm_client, "chat_completion", lambda messages, **k: calls.append(messages) or next(replies))
    reading = L.read("sales?", CATALOG, TODAY)
    assert reading["intents"] == ["sales"] and len(calls) == 2
    assert calls[1][-1]["content"].startswith("That was not one complete JSON object")


def test_a_lone_generic_product_intent_gives_way_to_the_models():
    u = U.understand("Which item has been flying off the shelves this year?", catalog=CATALOG, today=TODAY)
    u.intents = [U.PRODUCTS]  # what the rules made of "item"
    reading = {"intents": ["sales"], "periods": [], "period_days": None, "products": [], "ranking": True, "small_talk": False}
    assert L.fill_gaps(u, reading).intents == ["sales"]
    u2 = U.understand("What was revenue last month?", catalog=CATALOG, today=TODAY)
    assert L.fill_gaps(u2, {**reading, "intents": ["forecast"]}).intents == [U.SALES]  # a specific reading is kept


def test_wrongly_typed_fields_never_crash(monkeypatch):
    # Seen from a 0.6B model: objects inside "intents", a string for "periods", "yes" for a boolean.
    _model_says(monkeypatch, {"intents": [{"name": "sales"}, "sales", 3], "periods": "Q2 2026",
                              "products": {"name": "Tahini 450g"}, "ranking": "yes", "small_talk": 1})
    reading = L.read("anything", CATALOG, TODAY)
    assert reading["intents"] == ["sales"] and reading["periods"][0]["start"] == "2026-04-01"
    assert reading["products"] == [] and reading["ranking"] is False and reading["small_talk"] is False



def test_the_model_trims_intents_the_rules_added_from_a_word_used_in_another_sense():
    u = U.understand("When should I reorder Sidr Honey?", catalog=CATALOG, today=TODAY)
    u.intents = [U.INVENTORY, U.ADVICE]   # "should" read as a request for advice
    reading = {"intents": ["inventory"], "periods": [], "period_days": None, "products": [], "ranking": False,
               "small_talk": False}
    assert L.fill_gaps(u, reading).intents == [U.INVENTORY]


def test_a_question_that_joins_two_needs_keeps_both():
    u = U.understand("قديش بعنا وقديش كسبنا بشهر 9؟", catalog=CATALOG, today=TODAY)
    assert set(u.intents) == {U.SALES, U.FINANCIALS}
    reading = {"intents": ["sales"], "periods": [], "period_days": None, "products": [], "ranking": False,
               "small_talk": False}
    assert set(L.fill_gaps(u, reading).intents) == {U.SALES, U.FINANCIALS}


def test_delivery_cost_is_the_delivery_policy_not_cost_price():
    u = U.understand("Do you deliver to Irbid and how much does it cost?", catalog=CATALOG, today=TODAY)
    assert u.intents == [U.DOCUMENTS]


@pytest.mark.parametrize("question, ask", [
    ("What was revenue last month?", False),                 # one clear need, its period read: rules alone
    ("قديش ضل عنا طحينة؟", False),
    ("how did the shop go lately lol", True),                # no need the rules know
    ("What price do we sell Tahini 450g at?", False),        # pricing with its product
    ("what's the price?", True),                             # pricing without a product
    ("sales in the spring of last decade", True),           # a time word without a period the rules could read
])
def test_the_model_is_asked_only_when_the_rules_reading_is_uncertain(question, ask):
    u = U.understand(question, catalog=CATALOG, today=TODAY)
    assert L.needs_model(u, question) is ask


@pytest.mark.parametrize("message", ["شكرا جزيلا", "إزيك عامل إيه", "تسلم يا رب"])
def test_a_recognised_greeting_never_asks_the_model(message):
    u = U.understand(message, catalog=CATALOG, today=TODAY)
    assert L.needs_model(u, message) is False and U.is_answerable(message) is False
