"""
Integration tests for dashboard/forecast_detail.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.forecast_detail import get_product_forecast_detail

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


def _insert_product(conn, tenant_id, name, current_price=10.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def test_returns_none_for_a_product_that_does_not_exist(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert get_product_forecast_detail(conn, tenant_id, str(uuid.uuid4())) is None


def test_current_stock_is_none_with_no_inventory_row(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()

    result = get_product_forecast_detail(conn, tenant_id, product_id)
    assert result["current_stock"] is None
    assert result["latest_forecast"] is None
    assert result["avg_daily_demand"] == 0.0


def test_returns_real_current_stock_and_avg_daily_demand(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO inventory (tenant_id, product_id, stock_quantity) VALUES (%s, %s, 620);",
            (tenant_id, product_id),
        )
    conn.commit()

    now = datetime.now(timezone.utc)
    invoice_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
            "VALUES (%s, %s, 'INV-1', %s, 90.0, 90.0, 'JOD');",
            (invoice_id, tenant_id, now - timedelta(days=1)),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
            "VALUES (%s, %s, %s, 90, 1.0, 90.0);",
            (tenant_id, invoice_id, product_id),
        )
    conn.commit()

    result = get_product_forecast_detail(conn, tenant_id, product_id)
    assert result["current_stock"] == 620
    assert result["avg_daily_demand"] == 1.0  # 90 units / 90 days


def test_returns_the_latest_real_forecast_with_confidence_interval(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()
    target_date = date.today() + timedelta(days=30)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, "
            "confidence_range_lower, confidence_range_upper, forecast_target_date, model_version) "
            "VALUES (%s, %s, %s, 1240, 820, 1560, %s, 'xgboost-v1');",
            (str(uuid.uuid4()), tenant_id, product_id, target_date),
        )
    conn.commit()

    result = get_product_forecast_detail(conn, tenant_id, product_id)
    forecast = result["latest_forecast"]
    assert forecast["predicted_demand"] == 1240
    assert forecast["confidence_range_lower"] == 820
    assert forecast["confidence_range_upper"] == 1560
    assert forecast["forecast_target_date"] == target_date.isoformat()
    assert forecast["model_version"] == "xgboost-v1"
    assert len(result["forecast_history"]) == 1


def test_model_accuracy_pct_reflects_a_real_evidence_record(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()
    forecast_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, forecast_target_date, model_version) "
            "VALUES (%s, %s, %s, 100, %s, 'test-model');",
            (forecast_id, tenant_id, product_id, date.today() + timedelta(days=30)),
        )
        cursor.execute(
            "INSERT INTO evidence_records (tenant_id, category, source_module, source_record_ids, confidence_score, explanation_text) "
            "VALUES (%s, 'PREDICTION', 'ai.forecasting', %s::jsonb, 0.92, 'test explanation');",
            (tenant_id, json.dumps({"forecast_id": forecast_id, "product_id": product_id})),
        )
    conn.commit()

    result = get_product_forecast_detail(conn, tenant_id, product_id)
    assert result["latest_forecast"]["model_accuracy_pct"] == 92
