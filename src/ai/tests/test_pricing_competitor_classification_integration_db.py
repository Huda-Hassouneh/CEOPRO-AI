"""
Integration test for competitor_classification.py against a real
PostgreSQL instance running the actual Final_schema.sql (+ migrations/).
Same convention as test_pricing_integration_db.py: skipped unless
AI_TEST_DATABASE_URL is set.
"""

import json
import os
import uuid

import psycopg2
import pytest

from src.ai.pricing.competitor_classification import (
    TIER_CANDIDATE, TIER_RELEVANT, TIER_STRATEGIC, classify_competitor, compute_product_match_rate,
)

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn, country_code: str = "JO", operating_countries=None) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency, operating_countries) "
            "VALUES (%s, %s, %s, 'JOD', %s);",
            (tenant_id, f"Test Co {tenant_id[:8]}", country_code, operating_countries or []),
        )
    return tenant_id


def _insert_product(conn, tenant_id: str, name: str) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
    return product_id


def _insert_competitor(conn, tenant_id: str, is_manufacturer: bool = False, country_code: str = None) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors "
            "(global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer, country_code) "
            "VALUES (%s, %s, 'PRIVATE', %s, %s, %s);",
            (competitor_id, f"Competitor {competitor_id[:8]}", tenant_id, is_manufacturer, country_code),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id) VALUES (%s, %s);",
            (tenant_id, competitor_id),
        )
    return competitor_id


def _map_product(conn, tenant_id: str, competitor_id: str, product_id: str):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, is_active) "
            "VALUES (%s, %s, %s, TRUE);",
            (tenant_id, competitor_id, product_id),
        )


def test_match_rate_is_zero_with_no_mapped_products(conn):
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id)
    assert compute_product_match_rate(conn, tenant_id, competitor_id) == 0.0


def test_match_rate_reflects_overlap_ratio(conn):
    tenant_id = _insert_company(conn)
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")  # unmapped - keeps ratio at 50%
    competitor_id = _insert_competitor(conn, tenant_id)
    _map_product(conn, tenant_id, competitor_id, product_a)
    assert compute_product_match_rate(conn, tenant_id, competitor_id) == 0.5


def test_classify_confirms_an_in_region_non_manufacturer_above_threshold(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.product_match_rate == 1.0

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_tracked, is_confirmed_competitor, product_match_rate FROM tenant_competitors "
            "WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        is_tracked, is_confirmed, match_rate = cursor.fetchone()
    assert is_tracked is True
    assert is_confirmed is True
    assert float(match_rate) == 1.0


def test_classify_excludes_a_manufacturer_regardless_of_match_rate(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert "manufacturer" in result.reason

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_tracked FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone()[0] is False


def test_classify_excludes_a_seller_outside_the_operating_region(conn):
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["AE"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="US")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.in_operating_region is False


def test_classify_allows_an_operating_countries_match_beyond_primary(conn):
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["AE"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="AE")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.in_operating_region is True
    assert result.is_confirmed_competitor is True


def test_classify_does_not_exclude_a_competitor_with_unknown_country(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code=None)
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.in_operating_region is True
    assert result.is_confirmed_competitor is True


def test_classify_rejects_below_threshold_overlap(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)  # 1/3 = 33%, below default 50%

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.product_match_rate == pytest.approx(1 / 3)


def test_classify_honors_a_custom_threshold(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)  # 33% overlap

    result = classify_competitor(conn, tenant_id, competitor_id, threshold=0.3)
    assert result.is_confirmed_competitor is True


def test_classify_rejects_invalid_threshold(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _insert_competitor(conn, tenant_id)
    with pytest.raises(ValueError, match="threshold"):
        classify_competitor(conn, tenant_id, competitor_id, threshold=1.5)


def test_tier_is_strategic_when_confirmed(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.tier == TIER_STRATEGIC

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tier FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone()[0] == TIER_STRATEGIC


def test_tier_is_relevant_when_below_threshold_but_otherwise_real(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)  # 1/3 = 33%, below default 50%

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.tier == TIER_RELEVANT

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tier FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone()[0] == TIER_RELEVANT


def test_tier_is_candidate_for_a_manufacturer(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.tier == TIER_CANDIDATE


def test_tier_is_candidate_for_an_out_of_region_seller(conn):
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["AE"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="US")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.tier == TIER_CANDIDATE
