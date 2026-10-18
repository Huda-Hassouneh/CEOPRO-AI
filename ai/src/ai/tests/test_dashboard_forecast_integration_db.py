"""
Integration tests for dashboard/forecast.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.forecast import get_forecast_summary

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


def _insert_product(conn, tenant_id, name="Widget") -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
    return product_id


def _insert_forecast(conn, tenant_id, product_id, expected_demand, target_date, created_at):
    forecast_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, "
            "forecast_target_date, model_version, created_at) VALUES (%s, %s, %s, %s, %s, 'test-model', %s);",
            (forecast_id, tenant_id, product_id, expected_demand, target_date, created_at),
        )
    return forecast_id


def test_returns_honest_zeros_for_a_tenant_with_no_forecasts(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = get_forecast_summary(conn, tenant_id)

    assert result == {"total_predicted_units": 0, "products_forecasted": 0, "forecast_target_date": None}


def test_sums_the_most_recent_forecast_per_product_only(conn):
    tenant_id = _insert_company(conn)
    product_a = _insert_product(conn, tenant_id, "Widget A")
    product_b = _insert_product(conn, tenant_id, "Widget B")
    conn.commit()
    now = datetime.now(timezone.utc)
    target = date.today() + timedelta(days=7)

    # product_a: an older, stale forecast (10) superseded by a newer one (25)
    _insert_forecast(conn, tenant_id, product_a, 10, target, created_at=now - timedelta(days=10))
    _insert_forecast(conn, tenant_id, product_a, 25, target, created_at=now)
    # product_b: a single forecast (15)
    _insert_forecast(conn, tenant_id, product_b, 15, target, created_at=now)
    conn.commit()

    result = get_forecast_summary(conn, tenant_id)

    assert result["total_predicted_units"] == 40  # 25 (latest for A) + 15 (B), not 10+25+15
    assert result["products_forecasted"] == 2
    assert result["forecast_target_date"] == target.isoformat()


def test_a_product_with_no_forecast_does_not_contribute_a_fabricated_zero(conn):
    tenant_id = _insert_company(conn)
    product_with_forecast = _insert_product(conn, tenant_id, "Forecasted Widget")
    _insert_product(conn, tenant_id, "Unforecasted Widget")  # never forecasted
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_forecast(conn, tenant_id, product_with_forecast, 8, date.today() + timedelta(days=7), created_at=now)
    conn.commit()

    result = get_forecast_summary(conn, tenant_id)

    assert result["total_predicted_units"] == 8
    assert result["products_forecasted"] == 1  # the unforecasted product isn't counted at all
