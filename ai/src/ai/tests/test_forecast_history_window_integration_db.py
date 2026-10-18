"""
The daily demand series used to end at a product's LAST sale, so a seasonal
item last sold months ago (Ramadan-only, summer-only) or a discontinued one
was forecast as if that last sales day were yesterday. Live-DB, skipped
unless AI_TEST_DATABASE_URL is set.
"""
from src.ai.tests.sales_fixtures import insert_sale
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.forecasting import data_access
from src.ai.forecasting.pipeline import run_forecast

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _seasonal_product(conn, last_sale_days_ago=120, days=30, per_day=25):
    tenant_id, product_id = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Season Co', 'JO', 'JOD');", (tenant_id,))
        cursor.execute("INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 2.75, 'JOD');",
                       (product_id, tenant_id, json.dumps({"en": "Qamar al-Din"})))
        start = datetime.now(timezone.utc) - timedelta(days=last_sale_days_ago + days)
        for offset in range(days):
            insert_sale(cursor, tenant_id, product_id, per_day, 2.75, start + timedelta(days=offset))
    conn.commit()
    return tenant_id, product_id


def test_series_runs_to_yesterday_with_zero_sales_days(conn):
    tenant_id, product_id = _seasonal_product(conn)
    daily = data_access.load_daily_demand(conn, tenant_id, product_id)
    assert daily["date"].iloc[-1].date() == date.today() - timedelta(days=1) or daily["date"].iloc[-1].date() == datetime.now(timezone.utc).date() - timedelta(days=1)
    assert daily["quantity"].tail(100).sum() == 0


def test_an_out_of_season_product_is_not_forecast_at_its_peak(conn):
    tenant_id, product_id = _seasonal_product(conn)
    result = run_forecast(conn, tenant_id, product_id)
    assert result["status"] == "OK"
    assert result["expected_demand"] < 25  # was ~25/day x horizon: the peak, as if the season never ended
    assert date.fromisoformat(result["forecast_target_date"]) > date.today()
