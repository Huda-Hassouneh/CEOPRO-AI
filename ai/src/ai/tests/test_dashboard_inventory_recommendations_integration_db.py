"""
Integration tests for dashboard/inventory_recommendations.py against a
real PostgreSQL instance. Same convention as every other live-DB test in
this package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import date, timedelta

import psycopg2
import pytest

from src.ai.dashboard.inventory_recommendations import (
    ACTION_MONITOR, ACTION_REDUCE_ORDER, ACTION_RESTOCK_NOW, get_inventory_recommendations,
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


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _insert_product_with_stock_and_forecast(conn, tenant_id, name, stock_quantity, expected_demand, current_price=10.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
        cursor.execute(
            "INSERT INTO inventory (tenant_id, product_id, stock_quantity) VALUES (%s, %s, %s);",
            (tenant_id, product_id, stock_quantity),
        )
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, forecast_target_date, model_version) "
            "VALUES (%s, %s, %s, %s, %s, 'test-model');",
            (str(uuid.uuid4()), tenant_id, product_id, expected_demand, date.today() + timedelta(days=30)),
        )
    return product_id


def test_returns_zero_counts_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    result = get_inventory_recommendations(conn, tenant_id)
    assert result["recommendations"] == []
    assert result["restock_now_count"] == 0


def test_recommends_restock_now_with_a_real_revenue_impact(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_stock_and_forecast(
        conn, tenant_id, "Acoustic Pro Speaker", stock_quantity=620, expected_demand=1240, current_price=2.0,
    )
    conn.commit()

    result = get_inventory_recommendations(conn, tenant_id)
    assert result["restock_now_count"] == 1
    row = result["recommendations"][0]
    assert row["action"] == ACTION_RESTOCK_NOW
    assert row["suggested_qty"] == 620
    assert row["estimated_revenue_impact"] == pytest.approx(1240.0)  # 620 units * 2.0 JOD
    assert row["priority"] == "High"
    assert "exceeds current stock" in row["reason"]


def test_recommends_reduce_order_with_no_fabricated_revenue_impact(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_stock_and_forecast(conn, tenant_id, "Winter Jacket", stock_quantity=890, expected_demand=450)
    conn.commit()

    result = get_inventory_recommendations(conn, tenant_id)
    assert result["reduce_order_count"] == 1
    row = result["recommendations"][0]
    assert row["action"] == ACTION_REDUCE_ORDER
    assert row["suggested_qty"] == -440
    assert row["estimated_revenue_impact"] is None


def test_recommends_monitor_for_a_small_gap(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_stock_and_forecast(conn, tenant_id, "Steady Widget", stock_quantity=100, expected_demand=105)
    conn.commit()

    result = get_inventory_recommendations(conn, tenant_id)
    assert result["monitor_count"] == 1
    assert result["recommendations"][0]["action"] == ACTION_MONITOR


def test_model_accuracy_pct_is_none_with_no_evidence_record(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_stock_and_forecast(conn, tenant_id, "Widget", stock_quantity=100, expected_demand=200)
    conn.commit()

    result = get_inventory_recommendations(conn, tenant_id)
    assert result["recommendations"][0]["model_accuracy_pct"] is None
