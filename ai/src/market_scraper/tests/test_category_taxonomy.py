from src.market_scraper.category_taxonomy import (
    MIN_COMPETING_SIMILARITY, STRONG_COMPETING_SIMILARITY, best_similarity, categorize, categorize_catalog,
    category_similarity,
)

BURGER = ("food", "snacks", "burger")
PIZZA = ("food", "snacks", "pizza")
DONUTS = ("food", "desserts", "donuts")


def test_burger_restaurant_does_not_compete_with_a_donut_shop():
    sim = category_similarity(BURGER, DONUTS)
    assert sim is not None and sim < MIN_COMPETING_SIMILARITY


def test_burger_and_pizza_share_a_segment_and_compete_strongly():
    assert category_similarity(BURGER, PIZZA) >= STRONG_COMPETING_SIMILARITY


def test_same_leaf_is_a_full_match():
    assert category_similarity(BURGER, BURGER) == 1.0


def test_different_top_level_is_zero():
    assert category_similarity(BURGER, ("electronics", "components", "parts")) == 0.0


def test_unknown_on_either_side_is_none_not_zero():
    assert category_similarity(None, BURGER) is None
    assert category_similarity(BURGER, ()) is None


def test_a_broader_path_is_compatible_but_never_strong():
    sim = category_similarity(BURGER, ("food",))
    assert MIN_COMPETING_SIMILARITY <= sim < STRONG_COMPETING_SIMILARITY


def test_categorize_from_name():
    assert categorize("Smash Burger House").path == BURGER
    assert categorize("Krispy Donuts").path == DONUTS
    assert categorize("Pizza Hut").path == PIZZA


def test_categorize_arabic_name():
    assert categorize("مطعم برجر الشام").path == BURGER
    assert categorize("دونات هاوس").path == DONUTS


def test_categorize_prefers_a_specific_places_type_over_the_name():
    result = categorize("The Corner", ["restaurant", "hamburger_restaurant", "food"])
    assert result.path == BURGER and result.source == "places_type"


def test_generic_places_type_is_only_a_last_resort():
    assert categorize("Joe's", ["restaurant"]).path == ("food",)
    assert categorize("Smash Burger", ["restaurant"]).path == BURGER


def test_ice_cream_phrase_wins_over_a_shorter_word():
    assert categorize("Naples Ice Cream").path == ("food", "desserts", "ice_cream")


def test_unrecognized_business_is_none_never_a_guess():
    assert categorize("Zorblax Holdings") is None
    assert categorize(None, None) is None


def test_electronics_store_type_is_broad_so_it_still_matches_a_components_shop():
    store = categorize("Gadget Hub", ["electronics_store"]).path
    tenant = categorize_catalog(["Arduino Nano", "Resistor Kit"])
    assert best_similarity(tenant, store) >= MIN_COMPETING_SIMILARITY


def test_catalog_categories_for_a_burger_restaurant():
    paths = categorize_catalog(["Cheeseburger", "Double Beef Burger", "Fries", "Cola", "Chicken Burger"])
    assert paths == [BURGER]
    assert best_similarity(paths, DONUTS) < MIN_COMPETING_SIMILARITY
    assert best_similarity(paths, PIZZA) >= STRONG_COMPETING_SIMILARITY


def test_multi_category_tenant_competes_wherever_any_category_matches():
    paths = categorize_catalog(["Burger", "Burger Combo", "Donut", "Glazed Donut"])
    assert set(paths) == {BURGER, DONUTS}
    assert best_similarity(paths, DONUTS) == 1.0


def test_catalog_with_no_signal_is_empty_and_similarity_unknown():
    paths = categorize_catalog(["Item 1", "Item 2"])
    assert paths == []
    assert best_similarity(paths, BURGER) is None


def test_business_type_counts_toward_the_tenant_category():
    assert categorize_catalog(["Item 1"], business_type="Burger restaurant") == [BURGER]


# --- extended coverage + discovery search keywords ---

from src.market_scraper.category_taxonomy import search_keyword_for_path


def test_additional_business_types_are_recognised():
    assert categorize("Glow Hair Salon").path == ("beauty", "salon")
    assert categorize("Iron Gym").path == ("fitness", "gym")
    assert categorize("Al Noor Bookstore").path == ("retail", "books_stationery")
    assert categorize("Quick Fix Garage").path == ("auto", "repair")
    assert categorize("X", ["pet_store"]).path == ("retail", "pets")
    assert categorize("X", ["jewelry_store"]).path == ("retail", "jewelry")


def test_a_salon_and_a_gym_do_not_compete():
    assert category_similarity(categorize("Glow Salon").path, categorize("Iron Gym").path) == 0.0


def test_search_keyword_targets_the_segment_not_the_vertical():
    assert search_keyword_for_path(BURGER) == "burger restaurant"
    assert search_keyword_for_path(DONUTS) == "donut shop"


def test_search_keyword_falls_back_to_a_broader_category():
    assert search_keyword_for_path(("food", "bakery", "something_new")) == "restaurant"
    assert search_keyword_for_path(None) is None
    assert search_keyword_for_path(("unknown",)) is None


def test_every_known_leaf_has_a_search_keyword():
    import src.market_scraper.category_taxonomy as taxonomy
    for name, (path, _, _) in taxonomy._LEAVES.items():
        assert search_keyword_for_path(path), name


def test_a_bakery_and_a_sweets_shop_compete_but_neither_competes_with_a_burger_place():
    bakery, sweets = categorize("Al Reem Bakery").path, categorize("Habibah Sweets").path
    assert category_similarity(bakery, sweets) >= MIN_COMPETING_SIMILARITY
    assert category_similarity(bakery, categorize("Smash Burger House").path) < MIN_COMPETING_SIMILARITY
    assert category_similarity(bakery, categorize("Krispy Donuts").path) >= MIN_COMPETING_SIMILARITY  # baked goods
