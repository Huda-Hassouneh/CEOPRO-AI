from src.market_scraper.sector_detection import (
    VERTICAL_INDUSTRY_LABELS, build_industry_search_query, infer_industry_sector,
)


def test_industry_query_uses_the_real_vertical_label_not_the_internal_key():
    query = build_industry_search_query("electronics_hobbyist")
    assert query.startswith("electronics store ")
    assert "electronics_hobbyist" not in query


def test_industry_query_includes_geo_scope_when_given():
    query = build_industry_search_query("food_beverage", geo_scope="Amman")
    assert query.endswith("Amman")


def test_industry_query_falls_back_to_general_retail_for_an_unknown_vertical():
    query = build_industry_search_query("some_future_vertical_nobody_added_yet")
    assert query.startswith(VERTICAL_INDUSTRY_LABELS["general_retail"])


def test_every_vertical_label_is_defined():
    # detect_vertical() can only ever return one of these keys (plus
    # "general_retail") - build_industry_search_query()'s fallback should
    # never actually be needed for a real detect_vertical() result.
    from src.market_scraper.sector_detection import _VERTICAL_KEYWORDS
    for vertical in _VERTICAL_KEYWORDS:
        assert vertical in VERTICAL_INDUSTRY_LABELS


def test_infer_industry_sector_matches_real_keywords():
    assert infer_industry_sector("Downtown Arduino & Sensor Supply") == "electronics_hobbyist"
    assert infer_industry_sector("Amman Coffee & Bakery House") == "food_beverage"


def test_infer_industry_sector_returns_none_when_nothing_matches():
    assert infer_industry_sector("Acme General Trading LLC") is None


def test_infer_industry_sector_handles_empty_text():
    assert infer_industry_sector("") is None
    assert infer_industry_sector(None) is None
