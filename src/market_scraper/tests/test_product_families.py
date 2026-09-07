from src.market_scraper.product_families import family_key, recommended_collector_config


def test_products_differing_only_by_a_numeric_value_share_a_family():
    assert family_key("1k Ohm Resistor") == family_key("2k Ohm Resistor")


def test_products_differing_only_by_size_word_share_a_family():
    assert family_key("T-Shirt Small") == family_key("T-Shirt Large")


def test_token_order_does_not_matter():
    assert family_key("Red Trail Shoe") == family_key("Trail Shoe Red")


def test_genuinely_different_products_get_different_keys():
    assert family_key("Arduino Uno R3") != family_key("Raspberry Pi 4")


def test_all_numeric_tokens_falls_back_to_the_full_token_set_not_an_empty_key():
    assert family_key("100") != ""
    assert family_key("100") == family_key("100")


def test_empty_or_missing_name_does_not_crash():
    assert family_key("") == ""
    assert family_key(None) == ""


def test_arabic_products_differing_only_by_a_numeric_value_share_a_family():
    """
    Real, previously-live bug: an ASCII-only [a-zA-Z0-9]+ token pattern
    found zero tokens in any pure-Arabic product name, so EVERY
    Arabic-named product collapsed into the same single empty-key
    family, regardless of whether they were actually related products -
    exactly the wrong behavior for a platform whose own
    products.product_name is natively bilingual en/ar.
    """
    a = family_key("مقاومة 1 كيلو أوم")
    b = family_key("مقاومة 2 كيلو أوم")
    assert a == b
    assert a != ""  # not the empty-key collapse the bug produced


def test_arabic_products_that_are_genuinely_different_get_different_keys():
    resistor = family_key("مقاومة 1 كيلو أوم")
    dress = family_key("فستان أحمر")
    assert resistor != dress
    assert resistor != "" and dress != ""


def test_mixed_arabic_and_english_tokens_are_all_kept():
    key = family_key("Arduino Uno قطعة إلكترونية")
    assert "arduino" in key
    assert "قطعة" in key


def test_recommended_config_enables_deep_collection_only_for_strategic_tier():
    assert recommended_collector_config("STRATEGIC") == {"fetch_comments": True}
    assert recommended_collector_config("RELEVANT") == {"fetch_comments": False}
    assert recommended_collector_config("CANDIDATE") == {"fetch_comments": False}
    assert recommended_collector_config(None) == {"fetch_comments": False}
