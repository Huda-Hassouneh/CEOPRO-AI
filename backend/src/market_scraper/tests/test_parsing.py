import pytest

from src.market_scraper.parsing import (
    clean_text,
    parse_price,
    parse_rating,
    parse_stock_quantity,
)


def test_clean_text_collapses_source_whitespace():
    assert clean_text("  In stock\n   (22 available) ") == "In stock (22 available)"
    assert clean_text("  ") is None
    assert clean_text(None) is None


def test_parse_price_returns_amount_and_iso_currency():
    assert parse_price("£51.77") == (51.77, "GBP")
    assert parse_price("د.أ 1,200.50") == (1200.5, "JOD")


def test_parse_price_rejects_unknown_currency():
    with pytest.raises(ValueError, match="unsupported currency"):
        parse_price("51.77 credits")


def test_parse_rating_and_stock_quantity():
    assert parse_rating(["star-rating", "Three"]) == 3
    assert parse_rating(["star-rating"]) is None
    assert parse_stock_quantity("In stock (22 available)") == 22
    assert parse_stock_quantity("Out of stock") is None
