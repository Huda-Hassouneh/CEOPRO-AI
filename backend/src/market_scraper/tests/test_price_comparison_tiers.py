"""
Price comparison tiers (market_scraper/price_comparison/): the two worked examples from the
product brief, plus the cases that must NOT produce a comparison. Pure - no database.
"""
import pytest

from src.market_scraper.price_comparison import attributes, tiers
from src.market_scraper.price_comparison.tiers import ADDED_VALUE, EQUIVALENT, EXACT, SIMILAR


def classify(own, own_price, item, item_price):
    return tiers.classify(attributes.parse_offer(own), attributes.parse_offer(item), own_price, item_price)


# --- Example 1: the competitor sells only a cheese burger for 3 JOD -----------------------------

def test_same_burger_is_an_exact_match():
    result = classify("Cheese burger", 3.5, "Cheese burger", 3)
    assert result.tier == EXACT
    assert result.comparable_price == 3
    assert result.price_delta_pct == pytest.approx(16.7)


def test_small_beef_burger_is_similar_and_smaller():
    result = classify("Small beef burger", 2.5, "Cheese burger", 3)
    assert result.tier == SIMILAR
    assert result.direction == tiers.OWN_LEANER
    assert {r["code"] for r in result.reasons} >= {"variant_differs", "size_differs"}


def test_extra_cheese_burger_is_added_value_with_a_premium():
    result = classify("Extra cheese burger", 4, "Cheese burger", 3)
    assert result.tier == ADDED_VALUE
    assert result.direction == tiers.OWN_RICHER
    assert result.premium == {"premium_pct": 33.3, "status": tiers.PREMIUM_WITHIN, "band_pct": tiers.PREMIUM_BAND_PCT}


# --- Example 2: the competitor offers 30 minute classes for 5 JOD ------------------------------

def test_one_hour_class_is_equivalent_to_two_half_hour_classes():
    result = classify("1 hour class", 10, "30 min class", 5)
    assert result.tier == EQUIVALENT
    assert result.scale_factor == 2
    assert result.comparable_price == 10
    assert result.price_delta_pct == 0
    assert result.direction == tiers.SAME


def test_35_minute_class_is_similar_and_priced_pro_rata():
    for own in ("35 min class", "35 class"):  # a bare number takes the other side's unit
        result = classify(own, 6, "30 min class", 5)
        assert result.tier == SIMILAR, own
        assert result.comparable_price == pytest.approx(5.8333, abs=1e-3)
        assert result.direction == tiers.OWN_RICHER


def test_class_with_conversation_feature_is_added_value():
    result = classify("30 min class with conversation", 7, "30 min class", 5)
    assert result.tier == ADDED_VALUE
    assert result.premium["premium_pct"] == 40.0
    assert any(r["code"] == "own_has_extras" and "conversation" in r["extras"] for r in result.reasons)


def test_added_value_that_is_scaled_keeps_the_scale():
    result = classify("1 hour class with conversation", 14, "30 min class", 5)
    assert result.tier == ADDED_VALUE
    assert result.comparable_price == 10
    assert result.premium["premium_pct"] == 40.0


# --- Premium reading ---------------------------------------------------------------------------

@pytest.mark.parametrize("own_price,status", [(3.0, tiers.PREMIUM_UNDERPRICED), (3.05, tiers.PREMIUM_UNDERPRICED),
                                              (4.5, tiers.PREMIUM_WITHIN), (6.0, tiers.PREMIUM_ABOVE)])
def test_premium_status(own_price, status):
    assert classify("Burger meal", own_price, "Burger", 3).premium["status"] == status


# --- What must not relate ----------------------------------------------------------------------

@pytest.mark.parametrize("own,item", [
    ("Cheese burger", "Cheesecake"),        # shares a word, not a kind
    ("Cheese burger", "Garden salad"),
    ("Haircut", "Hair dye"),
])
def test_unrelated_items_have_no_comparison(own, item):
    assert classify(own, 3, item, 3) is None


def test_comparable_price_far_from_ours_is_dropped():
    assert classify("Cheese burger", 3, "Cheese burger", 40) is None  # 13x: a catering tray, not a burger


def test_competitor_with_extras_is_similar_and_ours_is_leaner():
    result = classify("Cheese burger", 3, "Cheese burger with fries", 4)
    assert result.tier == SIMILAR
    assert result.direction == tiers.OWN_LEANER


def test_both_sides_with_different_extras_is_similar():
    assert classify("Burger with fries", 4, "Burger with salad", 4).tier == SIMILAR


def test_far_apart_quantities_scale_only_while_the_comparable_price_stays_plausible():
    # 10 hours = 20 x 30 min: a clean multiple, kept while it is within 0.2x-5x of our own price...
    assert classify("10 hour class", 50, "30 min class", 5).tier == EQUIVALENT
    # ...and dropped when scaling makes the competitor's price absurd next to ours.
    assert classify("10 hour class", 50, "30 min class", 50) is None


def test_quantity_in_another_dimension_does_not_scale():
    result = classify("Coffee 250 ml", 2, "Coffee 2 pcs", 2)
    assert result is None or result.scale_factor == 1


def test_quantity_stated_on_one_side_only_stays_exact_like_the_existing_matcher():
    result = classify("Cola", 1, "Cola 330 ml", 1)
    assert result.tier == EXACT
    assert {"code": "quantity_not_stated_on_one_side"} in result.reasons


# --- Arabic -----------------------------------------------------------------------------------

def test_arabic_hour_class_scales_against_arabic_half_hour_class():
    result = classify("ساعة محادثة", 10, "محادثة 30 دقيقة", 5)
    assert result.tier == EQUIVALENT
    assert result.comparable_price == 10


def test_arabic_extra_marker_is_added_value():
    result = classify("برجر جبنة اضافية", 4, "برجر جبنة", 3)
    assert result.tier == ADDED_VALUE


def test_arabic_indic_digits_are_read():
    assert attributes.parse_offer("صف ٣٠ دقيقة").quantity.amount == 30


# --- Parsing ----------------------------------------------------------------------------------

def test_parse_quantity_units():
    assert attributes.parse_offer("Class 1.5 hours").quantity.amount == 90
    assert attributes.parse_offer("Rice 2 kg").quantity.amount == 2000
    assert attributes.parse_offer("Hour class").quantity.amount == 60  # a bare "hour" is one hour
    assert attributes.parse_offer("Cheese burger").quantity is None


def test_plus_means_with():
    offer = attributes.parse_offer("Burger + fries")
    assert offer.core == ["burger"] and offer.withs == ["fry"]


# --- Compound spellings -----------------------------------------------------------------------

@pytest.mark.parametrize("own,item", [("Cheeseburger", "Cheese burger"), ("Cheese burger", "Cheeseburger"),
                                      ("Seafood pizza", "Sea food pizza"), ("Extra cheeseburger", "Cheese burger")])
def test_a_space_or_no_space_does_not_decide_the_match(own, item):
    result = classify(own, 3.5, item, 3)
    assert result is not None
    assert result.tier in (EXACT, ADDED_VALUE)
    if "Extra" not in own:
        assert result.tier == EXACT and result.reasons == []


def test_compound_spelling_does_not_hide_a_real_difference():
    assert classify("Cheeseburger", 3, "Cheesecake", 3) is None


# --- Extra words the rules cannot place --------------------------------------------------------

def test_conversation_class_vs_class_is_flagged_not_guessed():
    result = classify("Conversation class 30 min", 7, "30 min class", 5)
    assert result.tier == SIMILAR and result.direction == tiers.SAME
    assert result.ambiguous == {"side": "own", "words": ["conversation"]}
    assert any(r["code"] == "specificity_unclear" for r in result.reasons)


def test_a_verdict_of_addition_makes_it_added_value_with_a_premium():
    result = classify("Conversation class 30 min", 7, "30 min class", 5)
    settled = tiers.apply_verdict(result, "addition", 7)
    assert settled.tier == ADDED_VALUE and settled.direction == tiers.OWN_RICHER
    assert settled.premium["premium_pct"] == 40.0 and settled.method == "AI_ASSISTED" and settled.ambiguous is None
    assert any(r["code"] == "ai_judged" and r["verdict"] == "addition" for r in settled.reasons)


def test_a_verdict_of_variant_keeps_it_similar_and_like_for_like():
    result = classify("Chicken burger", 3.5, "Burger", 3)
    settled = tiers.apply_verdict(result, "variant", 3.5)
    assert settled.tier == SIMILAR and settled.direction == tiers.SAME and settled.ambiguous is None


def test_when_the_competitor_is_the_more_specific_one_an_addition_leaves_ours_leaner():
    result = classify("Burger", 3, "Burger with cheese", 4)  # a "with" is already an extra: not ambiguous
    assert result.ambiguous is None and result.direction == tiers.OWN_LEANER
    result = classify("Class 30 min", 5, "Conversation class 30 min", 7)
    assert result.ambiguous == {"side": "competitor", "words": ["conversation"]}
    assert tiers.apply_verdict(result, "addition", 5).direction == tiers.OWN_LEANER


def test_an_unknown_verdict_changes_nothing():
    result = classify("Conversation class 30 min", 7, "30 min class", 5)
    assert tiers.apply_verdict(result, "maybe", 7) is result


# --- The owner's word --------------------------------------------------------------------------

def test_owner_addition_forces_added_value_on_any_pair_and_variant_forces_similar():
    swap = classify("Chicken burger", 3.5, "Beef burger", 3)
    forced = tiers.force_verdict(swap, "addition", 3.5)
    assert forced.tier == ADDED_VALUE and forced.method == "OWNER" and forced.premium["premium_pct"] == pytest.approx(16.7)
    added = classify("Extra cheese burger", 4, "Cheese burger", 3)
    back = tiers.force_verdict(added, "variant", 4)
    assert back.tier == SIMILAR and back.direction == tiers.SAME and back.premium is None and back.method == "OWNER"


def test_owner_verdict_on_an_ambiguous_pair_settles_it_as_owner_decision():
    pair = classify("Conversation class 30 min", 7, "30 min class", 5)
    settled = tiers.force_verdict(pair, "addition", 7)
    assert settled.tier == ADDED_VALUE and settled.method == "OWNER" and settled.ambiguous is None
    codes = [r["code"] for r in settled.reasons]
    assert "owner_decision" in codes and "ai_judged" not in codes  # an owner's word is never labelled as the AI's
