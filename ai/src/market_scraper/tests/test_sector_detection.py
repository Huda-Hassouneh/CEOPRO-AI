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


# Found in first-customer testing across business types: Arabic/French
# catalogs produced zero tokens, and beauty, grocery, services and
# manufacturing tenants were all searched as a generic "retail store".

def test_arabic_and_french_catalogs_are_detected():
    from src.market_scraper.sector_detection import detect_vertical
    assert detect_vertical(["زيت زيتون بكر ممتاز", "زعتر بلدي", "عسل سدر", "تمر مجهول"]).vertical == "grocery"
    assert detect_vertical(["Crème hydratante", "Parfum floral", "Savon à l'huile"]).vertical == "beauty_personal_care"


def test_non_retail_business_types_get_their_own_vertical():
    from src.market_scraper.sector_detection import detect_vertical
    assert detect_vertical(["Consulting hour", "Audit session", "Training course"]).vertical == "professional_services"
    assert detect_vertical(["Steel pipe 2in", "Galvanized sheet", "Cement 50kg"]).vertical == "industrial_manufacturing"
    assert detect_vertical(["Brake pads", "Oil filter", "Spark plug"]).vertical == "automotive"


def test_declared_business_type_wins_over_ambiguous_product_names():
    from src.market_scraper.sector_detection import detect_vertical
    # "Signature Package" / "Gold Plan" say nothing; the owner's own label does.
    assert detect_vertical(["Signature Package", "Gold Plan"], business_type="Hair salon").vertical == "beauty_personal_care"
    assert detect_vertical(["Signature Package"], business_type=None).vertical == "general_retail"


def test_a_self_described_manufacturer_keeps_manufacturer_competitors():
    from src.ai.pricing.competitor_classification import _tenant_business_type_signals_manufacturer
    for label in ("Manufacturing", "Industrial supplies", "Food producer", "مصنع ألبسة", "Fabricant de meubles"):
        assert _tenant_business_type_signals_manufacturer(label), label
    assert not _tenant_business_type_signals_manufacturer("Hair salon")
