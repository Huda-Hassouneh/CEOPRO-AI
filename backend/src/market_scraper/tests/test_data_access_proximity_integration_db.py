"""
Integration test for company_geo_profile.py and
data_access.py::list_tenant_competitors_by_proximity() against a real
PostgreSQL instance. Same convention as test_tenant_discovery_
integration_db.py: skipped unless AI_TEST_DATABASE_URL is set.
"""
import os
import uuid

import psycopg2
import pytest

from src.ai.pricing.competitor_classification import classify_competitor
from src.market_scraper.company_geo_profile import (
    SCOPE_LEVEL_CITY, SCOPE_LEVEL_COUNTRY, SCOPE_LEVEL_CUSTOM, SCOPE_LEVEL_GLOBAL, SCOPE_LEVEL_PROVINCE,
    get_tenant_search_scope, set_tenant_search_scope,
)
from src.market_scraper.company_target_markets import set_tenant_target_markets
from src.market_scraper.data_access import list_tenant_competitors_by_proximity
from src.market_scraper.sector_detection import resolve_tenant_geo_scope, resolve_tenant_search_radius

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn, country_code: str = "JO") -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}", country_code),
        )
    return tenant_id


def _insert_product(conn, tenant_id: str, name: str) -> str:
    import json
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
    return product_id


def _insert_competitor_at(conn, tenant_id: str, name: str, lat, lon, country_code="JO") -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors "
            "(global_competitor_id, competitor_name, visibility, added_by_tenant_id, "
            " is_manufacturer, country_code, latitude, longitude) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE, %s, %s, %s);",
            (competitor_id, name, tenant_id, country_code, lat, lon),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id) VALUES (%s, %s);",
            (tenant_id, competitor_id),
        )
    return competitor_id


def test_set_and_get_tenant_search_scope_round_trip(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(
        conn, tenant_id, operating_countries=["jo", "ae"], latitude=31.9539, longitude=35.9106,
        city="Amman", search_scope_level=SCOPE_LEVEL_PROVINCE,
    )
    scope = get_tenant_search_scope(conn, tenant_id)
    assert scope["operating_countries"] == ["JO", "AE"]
    assert scope["latitude"] == pytest.approx(31.9539)
    assert scope["longitude"] == pytest.approx(35.9106)
    assert scope["city"] == "Amman"
    assert scope["search_scope_level"] == SCOPE_LEVEL_PROVINCE
    assert scope["default_search_radius_km"] == 150  # server-resolved preset, never typed by a user


def test_set_tenant_search_scope_is_a_partial_update(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, operating_countries=["jo"], search_scope_level=SCOPE_LEVEL_CITY)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_PROVINCE)  # only the level changes

    scope = get_tenant_search_scope(conn, tenant_id)
    assert scope["operating_countries"] == ["JO"]  # untouched by the second call
    assert scope["search_scope_level"] == SCOPE_LEVEL_PROVINCE
    assert scope["default_search_radius_km"] == 150


def test_set_tenant_search_scope_rejects_a_lone_latitude(conn):
    tenant_id = _insert_company(conn)
    with pytest.raises(ValueError, match="together"):
        set_tenant_search_scope(conn, tenant_id, latitude=31.9539)


def test_city_and_province_resolve_to_server_side_presets(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_CITY)
    assert get_tenant_search_scope(conn, tenant_id)["default_search_radius_km"] == 25

    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_PROVINCE)
    assert get_tenant_search_scope(conn, tenant_id)["default_search_radius_km"] == 150


def test_country_scope_clears_any_stored_radius(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_CITY)
    assert get_tenant_search_scope(conn, tenant_id)["default_search_radius_km"] == 25

    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_COUNTRY)
    scope = get_tenant_search_scope(conn, tenant_id)
    assert scope["search_scope_level"] == SCOPE_LEVEL_COUNTRY
    assert scope["default_search_radius_km"] is None


def test_custom_scope_requires_a_custom_radius(conn):
    tenant_id = _insert_company(conn)
    with pytest.raises(ValueError, match="custom_radius_km is required"):
        set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_CUSTOM)


def test_custom_radius_is_rejected_without_custom_scope(conn):
    tenant_id = _insert_company(conn)
    with pytest.raises(ValueError, match="only accepted together"):
        set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_PROVINCE, custom_radius_km=40)


def test_custom_scope_uses_the_exact_supplied_radius(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_CUSTOM, custom_radius_km=77)
    assert get_tenant_search_scope(conn, tenant_id)["default_search_radius_km"] == 77


def test_global_scope_clears_any_stored_radius(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_CITY)
    assert get_tenant_search_scope(conn, tenant_id)["default_search_radius_km"] == 25

    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_GLOBAL)
    scope = get_tenant_search_scope(conn, tenant_id)
    assert scope["search_scope_level"] == SCOPE_LEVEL_GLOBAL
    assert scope["default_search_radius_km"] is None


def test_resolve_tenant_geo_scope_returns_empty_string_for_global(conn):
    """A tenant who explicitly chose worldwide discovery gets no
    geographic bias in the search query text at all - not even their own
    country, which would silently narrow "global" back down to one place."""
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_GLOBAL)
    assert resolve_tenant_geo_scope(conn, tenant_id) == ""


def test_resolve_tenant_geo_scope_uses_the_city_name_for_city_scope(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, city="Amman", search_scope_level=SCOPE_LEVEL_CITY)
    assert resolve_tenant_geo_scope(conn, tenant_id) == "Amman"


def test_resolve_tenant_geo_scope_falls_back_to_country_name_for_city_scope_without_a_city(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_CITY)
    assert resolve_tenant_geo_scope(conn, tenant_id) == "Jordan"


def test_resolve_tenant_geo_scope_joins_every_operating_country_for_regional_scope(conn):
    """The actual fix for 'regional/selected countries has zero effect on
    discovery' - previously only the tenant's single primary country_code
    was ever used; every operating_countries entry now contributes."""
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(
        conn, tenant_id, operating_countries=["JO", "AE", "SA"], search_scope_level=SCOPE_LEVEL_COUNTRY,
    )
    result = resolve_tenant_geo_scope(conn, tenant_id)
    assert "Jordan" in result
    assert "United Arab Emirates" in result
    assert "Saudi Arabia" in result


def test_resolve_tenant_geo_scope_override_always_wins(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_GLOBAL)
    assert resolve_tenant_geo_scope(conn, tenant_id, override="Amman") == "Amman"


def test_resolve_tenant_geo_scope_adds_declared_target_markets_to_the_bias_text(conn):
    """Discovery integration: an explicitly declared Target Market
    (company_target_markets.py) biases discovery's own search text too,
    additively - operating_countries is untouched, the target market is
    appended alongside it."""
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, operating_countries=["JO"], search_scope_level=SCOPE_LEVEL_COUNTRY)
    set_tenant_target_markets(conn, tenant_id, [{"market_type": "COUNTRY", "country_code": "EG"}])
    result = resolve_tenant_geo_scope(conn, tenant_id)
    assert "Jordan" in result
    assert "Egypt" in result


def test_resolve_tenant_geo_scope_adds_a_declared_region_target_market_as_free_text(conn):
    """A REGION-type target market (free text, never a fixed country list -
    see company_target_markets.py's own docstring) is appended to the
    search-bias text exactly as typed, purely for discovery's own search
    query construction - never resolved against an invented region-to-
    country mapping."""
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, operating_countries=["JO"], search_scope_level=SCOPE_LEVEL_COUNTRY)
    set_tenant_target_markets(conn, tenant_id, [{"market_type": "REGION", "region_name": "Middle East"}])
    result = resolve_tenant_geo_scope(conn, tenant_id)
    assert "Jordan" in result
    assert "Middle East" in result


def test_resolve_tenant_geo_scope_never_adds_anything_when_no_target_market_is_declared(conn):
    """The 'never invent' guarantee, exercised through the real discovery
    entry point: with zero declared target markets, the bias text is
    identical to the pre-existing operating_countries-only behavior."""
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, operating_countries=["JO", "AE"], search_scope_level=SCOPE_LEVEL_COUNTRY)
    assert resolve_tenant_geo_scope(conn, tenant_id) == "Jordan OR United Arab Emirates"


def test_resolve_tenant_geo_scope_still_returns_empty_string_for_global_even_with_a_declared_target_market(conn):
    """GLOBAL scope keeps its own honest 'no geographic bias at all'
    contract - a declared target market doesn't reintroduce one."""
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_GLOBAL)
    set_tenant_target_markets(conn, tenant_id, [{"market_type": "COUNTRY", "country_code": "EG"}])
    assert resolve_tenant_geo_scope(conn, tenant_id) == ""


def test_resolve_tenant_geo_scope_returns_empty_string_when_a_global_target_market_is_declared(conn):
    """A GLOBAL-type target market triggers the same 'no geographic bias'
    contract as search_scope_level=GLOBAL, even when the company's own
    search scope is narrower (COUNTRY) - a declared commercial intent to
    compete everywhere overrides the narrower discovery radius, without
    ever mutating search_scope_level itself."""
    tenant_id = _insert_company(conn, country_code="JO")
    set_tenant_search_scope(conn, tenant_id, operating_countries=["JO"], search_scope_level=SCOPE_LEVEL_COUNTRY)
    set_tenant_target_markets(conn, tenant_id, [{"market_type": "GLOBAL"}])
    assert resolve_tenant_geo_scope(conn, tenant_id) == ""


def test_proximity_listing_sorts_closest_first(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, latitude=31.9539, longitude=35.9106)
    product_a = _insert_product(conn, tenant_id, "Widget A")

    near = _insert_competitor_at(conn, tenant_id, "Near Co", 31.9454, 35.9284)  # ~2km
    far = _insert_competitor_at(conn, tenant_id, "Far Co", 25.2048, 55.2708)  # ~2030km
    for competitor_id in (near, far):
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, is_active) "
                "VALUES (%s, %s, %s, TRUE);",
                (tenant_id, competitor_id, product_a),
            )
        classify_competitor(conn, tenant_id, competitor_id)

    results = list_tenant_competitors_by_proximity(conn, tenant_id)
    assert [r["global_competitor_id"] for r in results] == [near, far]
    assert results[0]["distance_km"] < results[1]["distance_km"]


def test_proximity_listing_radius_filter_excludes_farther_rows(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, latitude=31.9539, longitude=35.9106)
    product_a = _insert_product(conn, tenant_id, "Widget A")

    near = _insert_competitor_at(conn, tenant_id, "Near Co", 31.9454, 35.9284)  # ~2km
    far = _insert_competitor_at(conn, tenant_id, "Far Co", 25.2048, 55.2708)  # ~2030km
    for competitor_id in (near, far):
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, is_active) "
                "VALUES (%s, %s, %s, TRUE);",
                (tenant_id, competitor_id, product_a),
            )
        classify_competitor(conn, tenant_id, competitor_id)

    results = list_tenant_competitors_by_proximity(conn, tenant_id, radius_km=100)
    assert [r["global_competitor_id"] for r in results] == [near]


def test_proximity_listing_puts_unknown_distance_last(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, latitude=31.9539, longitude=35.9106)
    product_a = _insert_product(conn, tenant_id, "Widget A")

    known = _insert_competitor_at(conn, tenant_id, "Known Co", 31.9454, 35.9284)
    unknown = _insert_competitor_at(conn, tenant_id, "Unknown Co", None, None)
    for competitor_id in (known, unknown):
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, is_active) "
                "VALUES (%s, %s, %s, TRUE);",
                (tenant_id, competitor_id, product_a),
            )
        classify_competitor(conn, tenant_id, competitor_id)

    results = list_tenant_competitors_by_proximity(conn, tenant_id)
    assert [r["global_competitor_id"] for r in results] == [known, unknown]
    assert results[1]["distance_km"] is None


# "If the target region data is missing/empty, automatically fall back to
# the closest logically appropriate default scope or radius" - a fresh
# tenant who never called set_tenant_search_scope() at all still has a
# real search_scope_level (the column's own DB default), so
# resolve_tenant_search_radius() should still resolve a real number, not
# silently return None.

def test_radius_falls_back_to_the_province_preset_for_a_never_configured_tenant(conn):
    tenant_id = _insert_company(conn)  # no set_tenant_search_scope() call at all
    assert resolve_tenant_search_radius(conn, tenant_id) == 150  # PROVINCE is the DB default


def test_radius_falls_back_to_the_stored_scope_levels_preset(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_CITY)
    assert resolve_tenant_search_radius(conn, tenant_id) == 25


def test_radius_is_none_for_an_explicit_country_scope_not_a_fallback_failure(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_COUNTRY)
    assert resolve_tenant_search_radius(conn, tenant_id) is None


def test_radius_override_always_wins_regardless_of_stored_scope(conn):
    tenant_id = _insert_company(conn)
    set_tenant_search_scope(conn, tenant_id, search_scope_level=SCOPE_LEVEL_COUNTRY)
    assert resolve_tenant_search_radius(conn, tenant_id, override_km=42) == 42
