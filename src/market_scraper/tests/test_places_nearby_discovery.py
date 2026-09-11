from unittest.mock import patch

from src.market_scraper.discovery import CandidateSource
from src.market_scraper.places_nearby_discovery import (
    MAX_NEARBY_SEARCH_RADIUS_KM, discover_nearby_places,
)


def _nearby_payload(*results):
    return {"status": "OK" if results else "ZERO_RESULTS", "results": list(results)}


def test_returns_empty_list_when_api_key_is_missing():
    assert discover_nearby_places(31.95, 35.91, "electronics store", radius_km=25, api_key=None) == []


def test_returns_empty_list_on_zero_results():
    with patch("src.market_scraper.places_nearby_discovery._get", return_value=_nearby_payload()):
        assert discover_nearby_places(31.95, 35.91, "electronics store", radius_km=25, api_key="k") == []


def test_returns_empty_list_on_request_failure():
    with patch("src.market_scraper.places_nearby_discovery._get", return_value=None):
        assert discover_nearby_places(31.95, 35.91, "electronics store", radius_km=25, api_key="k") == []


def test_returns_empty_list_on_api_error_status():
    payload = {"status": "REQUEST_DENIED", "results": []}
    with patch("src.market_scraper.places_nearby_discovery._get", return_value=payload):
        assert discover_nearby_places(31.95, 35.91, "electronics store", radius_km=25, api_key="k") == []


def test_skips_a_result_with_no_real_website():
    nearby = _nearby_payload({"place_id": "p1", "name": "No Website Shop"})
    with patch("src.market_scraper.places_nearby_discovery._get") as mock_get:
        mock_get.side_effect = [nearby, {"result": {}}]  # Details returns no "website" field
        candidates = discover_nearby_places(31.95, 35.91, "electronics store", radius_km=25, api_key="k")
    assert candidates == []


def test_returns_a_real_candidate_with_its_own_coordinates():
    nearby = _nearby_payload({"place_id": "p1", "name": "Downtown Electronics", "geometry": {"location": {"lat": 31.94, "lng": 35.93}}})
    details = {"result": {
        "website": "https://downtown-electronics.example",
        "geometry": {"location": {"lat": 31.9454, "lng": 35.9284}},
        "formatted_address": "Amman, Jordan",
    }}
    with patch("src.market_scraper.places_nearby_discovery._get") as mock_get:
        mock_get.side_effect = [nearby, details]
        candidates = discover_nearby_places(31.95, 35.91, "electronics store", radius_km=25, api_key="k")

    assert candidates == [
        CandidateSource(
            "electronics store", "https://downtown-electronics.example", "Downtown Electronics",
            latitude=31.9454, longitude=35.9284, city="Amman, Jordan",
        )
    ]


def test_radius_is_clamped_to_the_real_google_api_cap():
    captured_params = {}

    def fake_get(url, params):
        captured_params.update(params)
        return _nearby_payload()

    with patch("src.market_scraper.places_nearby_discovery._get", side_effect=fake_get):
        discover_nearby_places(31.95, 35.91, "electronics store", radius_km=150, api_key="k")

    assert captured_params["radius"] == MAX_NEARBY_SEARCH_RADIUS_KM * 1000


def test_radius_under_the_cap_is_used_as_is():
    captured_params = {}

    def fake_get(url, params):
        captured_params.update(params)
        return _nearby_payload()

    with patch("src.market_scraper.places_nearby_discovery._get", side_effect=fake_get):
        discover_nearby_places(31.95, 35.91, "electronics store", radius_km=10, api_key="k")

    assert captured_params["radius"] == 10_000
