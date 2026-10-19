"""Business names across Arabic, English and transliteration - the match bar
(0.82) used for Places candidates - and the cases that must stay apart."""
import pytest

from src.ai.pricing.matching import similarity
from src.market_scraper.name_matching import name_similarity, skeleton

BAR = 0.82


@pytest.mark.parametrize("a, b", [
    ("شاورما أبو علي", "Abu Ali Shawerma"),
    ("مطعم هاشم", "Hashem Restaurant"),
    ("Hashem", "Hashim Restaurant"),
    ("Hummus Abu Shukri", "حمص ابو شكري"),
    ("Kunafa Nabulsieh", "كنافة نابلسية"),
    ("Zaatar w Zeit", "زعتر وزيت"),
    ("Habibah Sweets", "Habiba Sweet"),
    ("Kasr Al Nil", "Qasr El Nil"),
    ("Cafe Bella", "Bella Cafe & Restaurant"),
])
def test_the_same_business_in_another_script_or_spelling_clears_the_bar(a, b):
    assert name_similarity(a, b) >= BAR


@pytest.mark.parametrize("a, b", [
    ("Pizza Hut", "Papa Johns"),
    ("مطعم هاشم", "Abu Ali Shawerma"),
    ("Habibah Sweets", "Al Quds Pharmacy"),
    ("Kunafa Nabulsieh", "حمص ابو شكري"),
    ("Sufra", "Safari"),
])
def test_different_businesses_stay_apart(a, b):
    assert name_similarity(a, b) < BAR


def test_it_never_scores_below_the_plain_ratio_and_handles_blanks():
    for a, b in (("Burger House", "Burger Hut"), ("Al Quds Bakery", "Al Qasr Bakery"), ("x", "xy")):
        assert name_similarity(a, b) >= round(similarity(a, b), 4) - 1e-9
    assert name_similarity("", "x") == 0.0 and name_similarity(None, None) == 0.0


def test_skeleton_ignores_word_order_vowels_and_spelling_variants():
    assert skeleton("Abu Ali Shawerma") == skeleton("شاورما أبو علي") == skeleton("Ali Shawarma")
    assert skeleton("Qasr") == skeleton("Kasr")


def test_very_short_names_are_not_matched_across_scripts_on_purpose():
    # Three consonants fit too many unrelated names ("Sufra" / "Safari"), so cross-script matching
    # needs 4+; such names still match when written the same way.
    assert name_similarity("Sufra", "سفرة") < BAR
    assert name_similarity("Sufra Restaurant", "Sufra") >= BAR
