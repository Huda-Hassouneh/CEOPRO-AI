"""
price_comparison/engine.py: which competitor item represents each tier, and that a competitor's rows are replaced
whole - with a fake cursor, no database. The SQL itself is covered by
ai/tests/test_price_comparison_integration_db.py.
"""
from unittest.mock import MagicMock

from src.market_scraper.price_comparison import engine, tiers

BURGER = {"product_id": "p-burger", "name": "Cheese burger", "name_alt": None, "price": 3.5, "currency": "JOD"}
ITEMS = [
    {"name": "Cheese burger", "price": 3.0, "currency": "JOD", "source_url": "https://c.example/menu"},
    {"name": "Beef burger", "price": 3.2, "currency": "JOD"},
    {"name": "Cheese burger with fries", "price": 4.0, "currency": "JOD"},
    {"name": "Garden salad", "price": 2.0, "currency": "JOD"},
    {"name": "Cheese burger", "price": 4.0, "currency": "USD"},  # another currency is never compared
]


def by_tier(entries):
    return {e["tier"]: e for e in entries}


def test_each_tier_gets_the_closest_item_and_unrelated_items_are_left_out():
    found = by_tier(engine.compare(BURGER, ITEMS))
    assert found[tiers.EXACT]["item"]["price"] == 3.0
    assert found[tiers.SIMILAR]["item"]["name"] in {"Beef burger", "Cheese burger with fries"}
    assert all(e["item"]["name"] != "Garden salad" for e in found.values())
    assert all(e["item"]["currency"] == "JOD" for e in found.values())


def test_one_long_menu_does_not_flood_the_ladder():
    menu = [{"name": f"Beef burger {n}", "price": 3.0 + n / 10, "currency": "JOD"} for n in range(20)]
    assert len(engine.compare(BURGER, menu)) <= len(tiers.TIERS)


def test_the_products_other_language_name_is_also_tried():
    product = {**BURGER, "name": "Kunafa", "name_alt": "كنافة"}
    found = engine.compare(product, [{"name": "كنافة نابلسية", "price": 3.0, "currency": "JOD"}])
    assert found and found[0]["tier"] in (tiers.EXACT, tiers.SIMILAR)


def test_a_product_without_a_price_is_skipped():
    assert engine.compare({**BURGER, "price": None}, ITEMS) == []


def _conn():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_refresh_replaces_the_competitors_rows_inside_a_savepoint():
    conn, cursor = _conn()
    result = engine.refresh_for_competitor(conn, "t1", "c1", [BURGER], ITEMS)
    statements = [call.args[0].strip().split()[0] + " " + call.args[0].strip().split()[1]
                  for call in cursor.execute.call_args_list]
    statements = statements[statements.index("SAVEPOINT price_comparison_write;"):]  # the overrides read comes first
    assert statements[0] == "SAVEPOINT price_comparison_write;"
    assert statements[1] == "DELETE FROM"
    assert statements[-1] == "RELEASE SAVEPOINT"
    assert statements.count("INSERT INTO") == result["rows"] >= 2
    assert result["by_tier"][tiers.EXACT] == 1


class _UndefinedTable(Exception):
    pgcode = "42P01"


def test_a_missing_table_is_skipped_without_poisoning_the_transaction():
    conn, cursor = _conn()
    cursor.execute.side_effect = lambda sql, *a: (_ for _ in ()).throw(_UndefinedTable()) if sql.lstrip().startswith("DELETE") else None
    result = engine.refresh_for_competitor(conn, "t1", "c1", [BURGER], ITEMS)
    assert result["skipped"] == "no_table" and result["rows"] == 0
    assert any("ROLLBACK TO SAVEPOINT" in call.args[0] for call in cursor.execute.call_args_list)


def test_any_other_database_error_is_raised_after_rolling_back_the_savepoint():
    import pytest
    conn, cursor = _conn()
    cursor.execute.side_effect = lambda sql, *a: (_ for _ in ()).throw(RuntimeError("boom")) if sql.lstrip().startswith("DELETE") else None
    with pytest.raises(RuntimeError):
        engine.refresh_for_competitor(conn, "t1", "c1", [BURGER], ITEMS)
    assert any("ROLLBACK TO SAVEPOINT" in call.args[0] for call in cursor.execute.call_args_list)


def test_the_judge_settles_only_ambiguous_pairs_and_the_row_records_the_method():
    product = {"product_id": "p", "name": "Conversation class 30 min", "name_alt": None, "price": 7.0, "currency": "JOD"}
    items = [{"name": "30 min class", "price": 5.0, "currency": "JOD"}]
    asked = []

    def judge(own, item, side, words):
        asked.append((own, item, side, words))
        return "addition"

    found = by_tier(engine.compare(product, items, judge))
    assert tiers.ADDED_VALUE in found and found[tiers.ADDED_VALUE]["comparison"].method == "AI_ASSISTED"
    assert asked == [("Conversation class 30 min", "30 min class", "own", ["conversation"])]
    # Not asked about a plain exact match.
    asked.clear()
    engine.compare({**product, "name": "30 min class"}, items, judge)
    assert asked == []


def test_without_a_judge_or_without_budget_the_pair_stays_unsettled():
    product = {"product_id": "p", "name": "Conversation class 30 min", "name_alt": None, "price": 7.0, "currency": "JOD"}
    items = [{"name": "30 min class", "price": 5.0, "currency": "JOD"}]
    assert engine.compare(product, items)[0]["comparison"].ambiguous is not None
    called = []
    out = engine.compare(product, items, lambda *a: called.append(a) or "addition", budget=[0])
    assert out[0]["comparison"].ambiguous is not None and called == []


def test_owner_decisions_are_applied_by_item_name_and_not_comparable_drops_the_item():
    product = {"product_id": "p", "name": "Cheese burger", "name_alt": None, "price": 3.5, "currency": "JOD"}
    items = [{"name": "Cheese Burger", "price": 3.0, "currency": "JOD"}, {"name": "Beef burger", "price": 3.2, "currency": "JOD"}]
    key = engine.name_key("Beef burger")
    found = by_tier(engine.compare(product, items, overrides={("p", key): "NOT_COMPARABLE"}))
    assert tiers.SIMILAR not in found and tiers.EXACT in found
    found = by_tier(engine.compare(product, items, overrides={("p", key): "ADDITION"}))
    assert found[tiers.ADDED_VALUE]["comparison"].method == "OWNER"
    # A decision about another product does not apply.
    assert tiers.SIMILAR in by_tier(engine.compare(product, items, overrides={("other", key): "NOT_COMPARABLE"}))


def test_an_owner_decision_wins_over_the_judge():
    product = {"product_id": "p", "name": "Conversation class 30 min", "name_alt": None, "price": 7.0, "currency": "JOD"}
    items = [{"name": "30 min class", "price": 5.0, "currency": "JOD"}]
    asked = []
    found = by_tier(engine.compare(product, items, lambda *a: asked.append(a) or "addition",
                                   overrides={("p", engine.name_key("30 min class")): "VARIANT"}))
    assert asked == [] and found[tiers.SIMILAR]["comparison"].method == "OWNER"


def test_an_earlier_ai_verdict_is_reused_without_asking_again_and_only_for_the_same_words():
    product = {"product_id": "p", "name": "Conversation class 30 min", "name_alt": None, "price": 7.0, "currency": "JOD"}
    items = [{"name": "30 min class", "price": 5.0, "currency": "JOD"}]
    key = ("p", engine.name_key("30 min class"))
    asked = []
    found = by_tier(engine.compare(product, items, lambda *a: asked.append(a), verdicts={key: ("own", ("conversation",), "addition")}))
    assert asked == [] and found[tiers.ADDED_VALUE]["comparison"].method == "AI_ASSISTED"
    # Other words (the product was renamed) or the other side: the old answer does not apply.
    stale = by_tier(engine.compare(product, items, verdicts={key: ("own", ("speaking",), "addition")}))
    assert tiers.ADDED_VALUE not in stale and stale[tiers.SIMILAR]["comparison"].ambiguous is not None


def test_prior_verdicts_are_read_from_the_rows_about_to_be_replaced():
    conn, cursor = _conn()
    cursor.fetchall.return_value = [("p", "30 min class", [{"code": "ai_judged", "verdict": "variant", "side": "own", "words": ["conversation"]}, {"code": "x"}])]
    assert engine.load_prior_verdicts(conn, "t1", "c1") == {("p", engine.name_key("30 min class")): ("own", ("conversation",), "variant")}


def test_unsettled_pairs_are_counted_and_an_item_is_parsed_once_for_many_products():
    engine._parse.cache_clear()
    extras = ["Conversation", "Speaking", "Business", "Writing", "Exam"]
    products = [{"product_id": f"p{n}", "name": f"{word} class", "name_alt": None, "price": 7.0, "currency": "JOD"} for n, word in enumerate(extras)]
    conn, _ = _conn()
    result = engine.refresh_for_competitor(conn, "t1", "c1", products, [{"name": "Class", "price": 5.0, "currency": "JOD"}])
    assert result["unsettled"] == 5
    info = engine._parse.cache_info()
    assert info.hits >= 4  # the one competitor item was parsed once, then served from the cache


def test_the_speed_shortcuts_never_change_a_result():
    """same_word's length bound and engine._may_relate only skip work: on a synthetic menu the ladder is identical
    with and without them (the fast path was 15x quicker on 500 products x 300 items)."""
    import random
    from difflib import SequenceMatcher
    from src.market_scraper.price_comparison import attributes

    rng = random.Random(7)
    letters = "abcdeghiklmnoprstuvz"
    words = ["".join(rng.choice(letters) for _ in range(rng.randint(2, 11))) for _ in range(300)]
    for a in words:
        for b in rng.sample(words, 20):
            slow = a == b or (len(a) >= 5 and len(b) >= 5 and abs(len(a) - len(b)) <= 2 and SequenceMatcher(None, a, b).ratio() >= 0.8)
            assert attributes.same_word(a, b) == slow, (a, b)

    nouns = ["burger", "pizza", "class", "salad", "shawarma", "برجر"]
    mods = ["cheese", "cheeseburger", "beef", "extra", "double", "30 min", "1 hour", "with fries", "kabsa", "gabsa", "seafood", "sea food", "جبنة"]
    name = lambda: " ".join(rng.sample(mods, rng.randint(0, 3)) + [rng.choice(nouns)])  # noqa: E731
    products = [{"product_id": str(i), "name": name(), "name_alt": None, "price": 5.0, "currency": "JOD"} for i in range(40)]
    items = [{"name": name(), "price": 5.0, "currency": "JOD"} for _ in range(40)]
    key = lambda found: [[(e["tier"], e["item"]["name"], e["comparison"].comparable_price) for e in entries] for entries in found]  # noqa: E731
    fast = key([engine.compare(p, items) for p in products])
    original = engine._may_relate
    engine._may_relate = lambda a, b: True
    try:
        slow_found = key([engine.compare(p, items) for p in products])
    finally:
        engine._may_relate = original
    assert fast == slow_found
