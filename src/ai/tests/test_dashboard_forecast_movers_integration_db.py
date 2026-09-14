"""
Integration tests for dashboard/forecast_movers.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import date, timedelta

import psycopg2
import pytest

from src.ai.dashboard.forecast_movers import get_forecast_movers

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


def _insert_product_with_stock_and_forecast(conn, tenant_id, name, stock_quantity, expected_demand) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
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
    result = get_forecast_movers(conn, tenant_id)
    assert result["products_forecasted"] == 0
    assert result["top_increasing"] == []
    assert result["top_decreasing"] == []


def test_flags_a_real_predicted_increase(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_stock_and_forecast(conn, tenant_id, "Acoustic Pro Speaker", stock_quantity=620, expected_demand=1240)
    conn.commit()

    result = get_forecast_movers(conn, tenant_id)
    assert result["products_forecasted"] == 1
    assert result["increasing_count"] == 1
    assert len(result["top_increasing"]) == 1
    row = result["top_increasing"][0]
    assert row["product_name"] == "Acoustic Pro Speaker"
    assert row["current_stock"] == 620
    assert row["predicted_demand"] == 1240
    assert row["change_pct"] == pytest.approx(100.0)


def test_flags_a_real_predicted_decrease(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_stock_and_forecast(conn, tenant_id, "Winter Jacket", stock_quantity=890, expected_demand=450)
    conn.commit()

    result = get_forecast_movers(conn, tenant_id)
    assert result["decreasing_count"] == 1
    assert result["top_decreasing"][0]["change_pct"] == pytest.approx(-49.4, abs=0.1)


def test_a_small_gap_counts_as_stable_not_a_mover(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_stock_and_forecast(conn, tenant_id, "Steady Widget", stock_quantity=100, expected_demand=110)
    conn.commit()

    result = get_forecast_movers(conn, tenant_id)
    assert result["stable_count"] == 1
    assert result["top_increasing"] == []
    assert result["top_decreasing"] == []


def test_a_product_with_no_inventory_row_is_excluded(conn):
    tenant_id = _insert_company(conn)
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": "No Inventory Widget"})),
        )
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, forecast_target_date, model_version) "
            "VALUES (%s, %s, %s, 100, %s, 'test-model');",
            (str(uuid.uuid4()), tenant_id, product_id, date.today() + timedelta(days=30)),
        )
    conn.commit()

    result = get_forecast_movers(conn, tenant_id)
    assert result["products_forecasted"] == 0
