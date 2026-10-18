"""Keyless place search (Nominatim, then Photon): parsing the shapes those
services return, keeping only businesses, the one-request-a-second rule,
falling back per query, and skipping or failing honestly."""
import httpx

from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.models import DiscoveryQuery
from src.market_scraper.market_discovery.providers import place_search

NOMINATIM = [
    {"place_id": 1, "osm_type": "node", "osm_id": 4242, "lat": "31.9516", "lon": "35.9239", "category": "shop",
     "type": "pastry", "name": "حلويات حبيبة", "display_name": "Habibah Sweets, King Faisal Street, Amman, Jordan",
     "address": {"shop": "Habibah", "house_number": "12", "road": "King Faisal Street", "suburb": "Al Balad",
                 "city": "Amman", "country_code": "jo"},
     "extratags": {"website": "https://habibah.jo", "phone": "+962 6 463 6000"},
     "namedetails": {"name": "حلويات حبيبة", "name:en": "Habibah Sweets", "name:ar": "حلويات حبيبة"}},
    {"place_id": 2, "osm_type": "way", "osm_id": 77, "lat": "31.95", "lon": "35.92", "category": "highway",
     "type": "residential", "name": "Bakery Street", "display_name": "Bakery Street, Amman"},  # a road, not a business
    {"place_id": 3, "osm_type": "node", "osm_id": 78, "lat": "31.95", "lon": "35.92", "category": "amenity",
     "type": "parking", "name": "Bakery parking"},  # amenity, but not a business
]
PHOTON = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [35.9301, 31.9555]},
     "properties": {"osm_type": "N", "osm_id": 991, "osm_key": "shop", "osm_value": "bakery", "name": "Zalatimo Sweets",
                    "street": "Rainbow Street", "housenumber": "5", "city": "Amman", "countrycode": "JO"}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [35.9, 31.9]},
     "properties": {"osm_type": "R", "osm_id": 5, "osm_key": "place", "osm_value": "city", "name": "Amman"}},
]}


def _query(**overrides):
    bakery = industries.get("bakery")
    values = dict(tenant_id="t", industry_key="bakery", industry_label=bakery.label_en, keywords=["حلويات", "bakery", "sweets shop"],
                  latitude=31.9539, longitude=35.9106, radius_km=5, city="Amman", country_code="JO", language="en",
                  osm_tags=bakery.osm_tags)
    values.update(overrides)
    return DiscoveryQuery(**values)


def test_nominatim_results_become_businesses_with_their_map_page():
    found = place_search.parse_nominatim(NOMINATIM, _query())
    assert [c.name for c in found] == ["Habibah Sweets"]
    habibah = found[0]
    assert habibah.source == "nominatim" and habibah.source_ref == "node/4242"
    assert habibah.source_url == "https://www.openstreetmap.org/node/4242"
    assert habibah.name_ar == "حلويات حبيبة" and habibah.website == "https://habibah.jo"
    assert habibah.address == "12 King Faisal Street, Al Balad" and habibah.industry_key == "bakery"
    assert (habibah.latitude, habibah.longitude) == (31.9516, 35.9239)


def test_photon_results_become_businesses_and_places_are_dropped():
    found = place_search.parse_photon(PHOTON, _query())
    assert [(c.name, c.source_ref, c.industry_key) for c in found] == [("Zalatimo Sweets", "node/991", "bakery")]
    assert found[0].latitude == 31.9555 and found[0].address == "5 Rainbow Street"


def test_each_query_falls_back_to_photon_and_waits_between_queries(monkeypatch):
    calls, waits = [], []

    def nominatim(text, query):
        calls.append(("nominatim", text))
        if text.startswith("bakery"):
            raise httpx.HTTPStatusError("429", request=httpx.Request("GET", "https://n"), response=httpx.Response(429))
        return NOMINATIM

    def photon(text, query):
        calls.append(("photon", text))
        return PHOTON

    monkeypatch.setattr(place_search, "_nominatim", nominatim)
    monkeypatch.setattr(place_search, "_photon", photon)
    result = place_search.search(_query(), sleep=waits.append)
    assert result.status == "ok"
    assert sorted(c.name for c in result.candidates) == ["Habibah Sweets", "Zalatimo Sweets"]
    assert calls == [("nominatim", "حلويات Amman"), ("nominatim", "bakery Amman"), ("photon", "bakery Amman"),
                     ("nominatim", "sweets shop Amman")]
    assert waits == [place_search.NOMINATIM_INTERVAL_SECONDS] * 2 and result.requests == 4


def test_a_city_alone_is_enough_and_nothing_at_all_is_skipped(monkeypatch):
    seen = []
    monkeypatch.setattr(place_search, "_nominatim", lambda text, query: seen.append(place_search._viewbox(query)) or [])
    assert place_search.search(_query(latitude=None, longitude=None), sleep=lambda s: None).status == "ok"
    assert seen and all(v is None for v in seen)  # no pin: searched by city name, unbounded
    assert place_search.search(_query(latitude=None, longitude=None, city=None)).reason == "no_location"


def test_unreachable_services_fail_honestly_and_can_be_turned_off(monkeypatch):
    def down(text, query):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(place_search, "_nominatim", down)
    monkeypatch.setattr(place_search, "_photon", down)
    result = place_search.search(_query(), sleep=lambda s: None)
    assert result.status == "failed" and result.reason == "unreachable" and result.candidates == []
    monkeypatch.setenv("DISCOVERY_DISABLE_PLACE_SEARCH", "true")
    assert place_search.search(_query()).status == "skipped"


def test_the_search_box_stays_within_the_radius():
    west, north, east, south = (float(v) for v in place_search._viewbox(_query(radius_km=5)).split(","))
    assert round(north - south, 2) == round(10 / 111.0, 2) and west < 35.9106 < east
