import pytest

from src.market_scraper.geo import distance_km_if_known, haversine_km


def test_haversine_is_zero_for_the_same_point():
    assert haversine_km(31.9539, 35.9106, 31.9539, 35.9106) == pytest.approx(0.0, abs=1e-6)


def test_haversine_matches_a_known_real_distance():
    # Amman, Jordan -> Dubai, UAE - real published great-circle distance is ~2030km.
    d = haversine_km(31.9539, 35.9106, 25.2048, 55.2708)
    assert d == pytest.approx(2030, rel=0.02)


def test_haversine_is_symmetric():
    a_to_b = haversine_km(31.9539, 35.9106, 25.2048, 55.2708)
    b_to_a = haversine_km(25.2048, 55.2708, 31.9539, 35.9106)
    assert a_to_b == pytest.approx(b_to_a)


def test_distance_km_if_known_returns_none_when_any_coordinate_is_missing():
    assert distance_km_if_known(None, 35.9106, 25.2048, 55.2708) is None
    assert distance_km_if_known(31.9539, None, 25.2048, 55.2708) is None
    assert distance_km_if_known(31.9539, 35.9106, None, 55.2708) is None
    assert distance_km_if_known(31.9539, 35.9106, 25.2048, None) is None


def test_distance_km_if_known_computes_when_all_coordinates_present():
    d = distance_km_if_known(31.9539, 35.9106, 25.2048, 55.2708)
    assert d == pytest.approx(2030, rel=0.02)
