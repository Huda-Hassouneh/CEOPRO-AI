"""Offline tests for geo_currency's pure country->currency lookup table."""
from src.ai.extraction.geo_currency import resolve_country_currency


def test_known_country_resolves_to_its_official_currency():
    assert resolve_country_currency("JO") == "JOD"
    assert resolve_country_currency("US") == "USD"
    assert resolve_country_currency("DE") == "EUR"


def test_lookup_is_case_and_whitespace_insensitive():
    assert resolve_country_currency(" jo ") == "JOD"


def test_unknown_country_returns_none_not_a_guess():
    assert resolve_country_currency("ZZ") is None


def test_missing_country_returns_none():
    assert resolve_country_currency(None) is None
    assert resolve_country_currency("") is None
