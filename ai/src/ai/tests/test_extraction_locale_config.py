"""
Unit tests for locale_config.py's pure resolve_locale() logic. Zero test
coverage before this file (same post-merge QA pass as
test_extraction_template_detection.py/test_extraction_row_parsing.py).
get_tenant_locale() (the DB-touching wrapper) was spot-checked directly
against a live database during that same pass and found correct - not
covered here since it needs a real connection, matching this test suite's
existing convention of gating DB-touching tests behind AI_TEST_DATABASE_URL
in the *_integration_db.py files rather than mixing them into plain unit
test files.
"""
from src.ai.extraction.locale_config import resolve_locale


def test_month_first_country_resolves_month_first():
    locale = resolve_locale("US")
    assert locale.date_day_first is False


def test_day_first_country_resolves_day_first():
    locale = resolve_locale("JO")
    assert locale.date_day_first is True


def test_comma_decimal_style_country():
    locale = resolve_locale("MA")
    assert locale.decimal_style == "comma"


def test_period_decimal_style_country():
    locale = resolve_locale("JO")
    assert locale.decimal_style == "period"


def test_unknown_country_falls_back_to_default_decimal_style():
    locale = resolve_locale("ZZ")
    assert locale.decimal_style == "period"  # DEFAULT_DECIMAL_STYLE


def test_country_code_is_normalized_to_uppercase():
    locale = resolve_locale("jo")
    assert locale.country_code == "JO"
    assert locale.decimal_style == "period"


def test_blank_country_code_does_not_crash():
    locale = resolve_locale("")
    assert locale.country_code == ""
    assert locale.decimal_style == "period"  # default, not a crash


def test_defaults_for_currencies_and_language():
    locale = resolve_locale("JO")
    assert locale.supported_currencies == []
    assert locale.preferred_language == "en"
