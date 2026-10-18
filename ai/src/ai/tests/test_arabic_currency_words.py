"""Arabic currency names: a country-qualified name is exact; a bare
"dinar"/"riyal"/"pound"/"dirham" means the company's own currency when it
is in that family, and is never guessed otherwise."""
from src.ai.extraction import regex_patterns
from src.ai.extraction.regex_patterns import extract_money


def _currencies(text, home=None):
    token = regex_patterns.HOME_CURRENCY.set(home)
    try:
        return [e.normalized_value.split()[-1] for e in extract_money(text) if e.normalized_value]
    finally:
        regex_patterns.HOME_CURRENCY.reset(token)


def test_qualified_names_are_exact():
    assert _currencies("السعر 5 دينار كويتي") == ["KWD"]
    assert _currencies("السعر 12 ريال سعودي", home="AED") == ["SAR"]


def test_bare_name_uses_the_company_currency_from_the_same_family():
    assert _currencies("السعر 5 دينار", home="KWD") == ["KWD"]
    assert _currencies("السعر 5 دينار", home="JOD") == ["JOD"]
    assert _currencies("السعر 30 درهم", home="MAD") == ["MAD"]


def test_bare_name_is_not_guessed_for_another_family_or_without_context():
    assert _currencies("السعر 5 دينار", home="SAR") == []
    assert _currencies("السعر 5 دينار") == []
