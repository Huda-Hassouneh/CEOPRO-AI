"""
Integration tests for dashboard/competitor_pricing.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.ai.dashboard.competitor_pricing import get_competitor_price_positioning

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _insert_product(conn, tenant_id, name, current_price) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def _insert_competitor_price(conn, tenant_id, product_id, competitor_name, scraped_price):
    competitor_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, competitor_name, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);",
            (tenant_id, competitor_id),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) VALUES (%s, %s, 'Test Source', 'WEB_SCRAPE');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, source_id) "
            "VALUES (%s, %s, %s, %s, %s);",
            (mapping_id, tenant_id, competitor_id, product_id, source_id),
        )
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency) VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, mapping_id, scraped_price),
        )


def test_returns_empty_list_when_no_products_have_a_competitor_mapping(conn):
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Unmapped Widget", current_price=10.0)
    conn.commit()

    assert get_competitor_price_positioning(conn, tenant_id) == []


def test_computes_price_gap_against_the_competitor_average(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine", current_price=120.0)
    conn.commit()
    _insert_competitor_price(conn, tenant_id, product_id, "Rival A", 100.0)
    conn.commit()

    positioning = get_competitor_price_positioning(conn, tenant_id)

    assert len(positioning) == 1
    row = positioning[0]
    assert row["product_id"] == product_id
    assert row["product_name"] == "Espresso Machine"
    assert row["your_price"] == 120.0
    assert row["market_average_price"] == 100.0
    assert row["price_gap_pct"] == pytest.approx(20.0)  # 20% above the market
    assert row["competitors_compared"] == 1


def test_sorted_by_biggest_gap_first_and_respects_limit(conn):
    tenant_id = _insert_company(conn)
    small_gap = _insert_product(conn, tenant_id, "Small Gap Widget", current_price=101.0)
    big_gap = _insert_product(conn, tenant_id, "Big Gap Widget", current_price=200.0)
    conn.commit()
    _insert_competitor_price(conn, tenant_id, small_gap, "Rival A", 100.0)  # +1%
    _insert_competitor_price(conn, tenant_id, big_gap, "Rival B", 100.0)  # +100%
    conn.commit()

    positioning = get_competitor_price_positioning(conn, tenant_id, limit=1)

    assert len(positioning) == 1
    assert positioning[0]["product_id"] == big_gap
