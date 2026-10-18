"""Offline: the newer discovery pipeline ranks only competitors in the
company's own segment (a donut shop is not a burger restaurant's competitor),
and the older Places path skips closed businesses."""
from unittest.mock import patch

from src.market_scraper.category_taxonomy import categorize_catalog
from src.market_scraper.market_discovery import industries, pipeline, relevance
from src.market_scraper.market_discovery.models import Candidate, DiscoveryQuery, ProviderResult
from src.market_scraper.places_nearby_discovery import discover_nearby_places

AMMAN = (31.9539, 35.9106)
BURGER_PATHS = tuple(categorize_catalog(["Cheeseburger", "Double Beef Burger", "Chicken Burger"], "Burger restaurant"))


def _query(paths=BURGER_PATHS):
    ind = industries.get("restaurant")
    return DiscoveryQuery(tenant_id="t", industry_key=ind.key, industry_label=ind.label_en, keywords=list(ind.keywords_en),
                          latitude=AMMAN[0], longitude=AMMAN[1], radius_km=5, city="Amman", country_code="JO",
                          osm_tags=ind.osm_tags, google_types=ind.google_types, own_name="Burger Barn", category_paths=paths)


def _place(name, ref, categories, **kw):
    return Candidate(name=name, source="openstreetmap", source_ref=ref, latitude=31.955, longitude=35.912,
                     industry_key="restaurant", categories=categories, **kw)


def test_the_company_category_is_derived_from_its_products_and_business_type():
    query = pipeline.build_query("t", {"business_type": "Burger restaurant", "product_names": ["Cheeseburger", "Fries"],
                                       "country_code": "JO", "city": "Amman", "latitude": 1.0, "longitude": 2.0})
    assert query.category_paths == (("food", "snacks", "burger"),)


def test_a_donut_shop_is_a_different_category_from_a_burger_restaurant():
    assert relevance.in_different_category("Krispy Donuts", None, ["shop=bakery", "cuisine=donut"], _query())


def test_pizza_and_burger_are_the_same_segment():
    assert not relevance.in_different_category("Napoli Pizza", None, ["amenity=fast_food", "cuisine=pizza"], _query())


def test_arabic_names_are_categorised_too():
    assert relevance.in_different_category("دونات هاوس", None, [], _query())


def test_unknown_category_or_unknown_company_segment_rules_nothing_out():
    assert not relevance.in_different_category("Zorblax", None, ["amenity=restaurant"], _query())
    assert not relevance.in_different_category("Krispy Donuts", None, ["cuisine=donut"], _query(paths=()))


def test_ranking_drops_a_donut_shop_but_keeps_burger_and_pizza_places():
    results = [ProviderResult("openstreetmap", "ok", [
        _place("Smash Burger House", "node/1", ["amenity=fast_food", "cuisine=burger"]),
        _place("Napoli Pizza", "node/2", ["amenity=fast_food", "cuisine=pizza"]),
        _place("Krispy Donuts", "node/3", ["amenity=cafe", "cuisine=donut"]),
        _place("Joe's Place", "node/4", ["amenity=restaurant"]),
    ])]
    names = [r[0].name for r in pipeline.rank(_query(), results)]
    assert "Krispy Donuts" not in names
    assert {"Smash Burger House", "Napoli Pizza", "Joe's Place"} <= set(names)


def test_without_a_company_segment_ranking_is_unchanged():
    results = [ProviderResult("openstreetmap", "ok", [_place("Krispy Donuts", "node/3", ["amenity=cafe", "cuisine=donut"])])]
    assert [r[0].name for r in pipeline.rank(_query(paths=()), results)] == ["Krispy Donuts"]


def test_the_company_specialty_outranks_the_category_rule():
    """A business with the company's own specialty in its name stays (DIRECT)."""
    query = _query()
    from dataclasses import replace
    query = replace(query, specialty_terms=("donut",))
    results = [ProviderResult("openstreetmap", "ok", [_place("Krispy Donuts", "node/3", ["amenity=cafe", "cuisine=donut"])])]
    assert [r[0].name for r in pipeline.rank(query, results)] == ["Krispy Donuts"]


# --- the older Places-nearby path: closed businesses are not competitors ---

def _nearby(*results):
    return {"status": "OK", "results": list(results)}


def test_a_permanently_closed_place_is_skipped_before_any_details_call():
    nearby = _nearby({"place_id": "p1", "name": "Gone Burger", "business_status": "CLOSED_PERMANENTLY"})
    with patch("src.market_scraper.places_nearby_discovery._get", side_effect=[nearby]) as mock_get:
        assert discover_nearby_places(31.95, 35.91, "burger restaurant", radius_km=5, api_key="k") == []
    assert mock_get.call_count == 1  # no Place Details request wasted on it


def test_a_place_closed_according_to_its_details_is_skipped():
    nearby = _nearby({"place_id": "p1", "name": "Gone Burger"})
    details = {"result": {"website": "https://gone.example", "business_status": "CLOSED_PERMANENTLY"}}
    with patch("src.market_scraper.places_nearby_discovery._get", side_effect=[nearby, details]):
        assert discover_nearby_places(31.95, 35.91, "burger restaurant", radius_km=5, api_key="k") == []


def test_an_operating_or_temporarily_closed_place_is_kept():
    nearby = _nearby({"place_id": "p1", "name": "Open Burger", "business_status": "OPERATIONAL"},
                     {"place_id": "p2", "name": "Renovating Burger", "business_status": "CLOSED_TEMPORARILY"})
    details = {"result": {"website": "https://x.example", "business_status": "OPERATIONAL"}}
    with patch("src.market_scraper.places_nearby_discovery._get", side_effect=[nearby, details, details]):
        found = discover_nearby_places(31.95, 35.91, "burger restaurant", radius_km=5, api_key="k")
    assert [c.title for c in found] == ["Open Burger", "Renovating Burger"]
