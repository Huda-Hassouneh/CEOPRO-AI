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
    SCOPE_LEVEL_CITY, SCOPE_LEVEL_COUNTRY, SCOPE_LEVEL_CUSTOM, SCOPE_LEVEL_PROVINCE,
    get_tenant_search_scope, set_tenant_search_scope,
)
from src.market_scraper.data_access import list_tenant_competitors_by_proximity

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
