"""
Integration tests for insights/assortment_reduce.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.insights.assortment_reduce import detect_reduce_candidate_insights

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


def _insert_product(conn, tenant_id, name, current_price=50.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def _insert_inventory(conn, tenant_id, product_id, stock_quantity):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO inventory (tenant_id, product_id, stock_quantity) VALUES (%s, %s, %s);",
            (tenant_id, product_id, stock_quantity),
        )


def _insert_forecast(conn, tenant_id, product_id, expected_demand, target_date):
    forecast_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, "
            "confidence_range_lower, confidence_range_upper, forecast_target_date, model_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'test-model');",
            (forecast_id, tenant_id, product_id, expected_demand, expected_demand - 5, expected_demand + 5, target_date),
        )
    return forecast_id


def test_returns_nothing_for_a_brand_new_tenant_with_no_forecast_or_stock(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert detect_reduce_candidate_insights(conn, tenant_id) == []


def test_flags_a_real_reduce_order_candidate(conn):
    """Reuses dashboard/inventory_recommendations.py's own real rule:
    predicted demand well below current stock (>= ACTION_THRESHOLD_PCT
    below) - here, 10 expected demand vs. 100 in stock is a 90% gap."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Slow Mover")
    conn.commit()
    _insert_inventory(conn, tenant_id, product_id, stock_quantity=100)
    target_date = (datetime.now(timezone.utc) + timedelta(days=30)).date()
    _insert_forecast(conn, tenant_id, product_id, expected_demand=10, target_date=target_date)
    conn.commit()

    insights = detect_reduce_candidate_insights(conn, tenant_id)

    assert len(insights) == 1
    assert "Slow Mover" in insights[0].message
    assert "phase it out" in insights[0].message
    assert insights[0].category == "assortment"
    assert insights[0].product_id == product_id


def test_does_not_flag_a_product_within_normal_demand_range(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Steady Seller")
    conn.commit()
    _insert_inventory(conn, tenant_id, product_id, stock_quantity=100)
    target_date = (datetime.now(timezone.utc) + timedelta(days=30)).date()
    _insert_forecast(conn, tenant_id, product_id, expected_demand=95, target_date=target_date)
    conn.commit()

    assert detect_reduce_candidate_insights(conn, tenant_id) == []


def test_does_not_flag_a_restock_now_candidate(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Hot Seller")
    conn.commit()
    _insert_inventory(conn, tenant_id, product_id, stock_quantity=10)
    target_date = (datetime.now(timezone.utc) + timedelta(days=30)).date()
    _insert_forecast(conn, tenant_id, product_id, expected_demand=100, target_date=target_date)
    conn.commit()

    assert detect_reduce_candidate_insights(conn, tenant_id) == []
