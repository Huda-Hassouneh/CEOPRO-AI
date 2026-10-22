"""
Demand Prediction end to end on a real database: products with sales and no
forecasts are found, forecasted, and the overview reports real trends, stock
advice and a chart series. Also covers localized_text() name selection.
Skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.forecasting import overview, refresh
from src.ai.forecasting.data_access import load_daily_demand
from src.ai.forecasting.pipeline import run_forecast
from src.ai.tests.sales_fixtures import insert_sale

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _company(cursor):
    tenant_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
        (tenant_id, f"Demand Co {tenant_id[:8]}"),
    )
    return tenant_id


def _product(cursor, tenant_id, names, price=4.0, stock=None, reorder=0):
    product_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, %s, 'JOD');",
        (product_id, tenant_id, json.dumps(names), price),
    )
    if stock is not None:
        cursor.execute(
            "INSERT INTO inventory (tenant_id, product_id, stock_quantity, reorder_level, safety_stock) VALUES (%s, %s, %s, %s, 0);",
            (tenant_id, product_id, stock, reorder),
        )
    return product_id


def _cleanup(cursor, tenant):
    for table in ("invoice_items", "invoices", "demand_forecasts", "evidence_records", "inventory", "products", "companies"):
        cursor.execute(f"DELETE FROM {table} WHERE tenant_id = %s;", (tenant,))


def test_products_with_sales_and_no_forecast_are_forecast_and_reported(conn):
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        tenant = _company(cursor)
        steady = _product(cursor, tenant, {"en": "Olive Oil", "ar": "زيت زيتون"}, stock=20)
        unsold = _product(cursor, tenant, {"en": "New Honey"}, stock=5)
        for day in range(1, 61):
            insert_sale(cursor, tenant, steady, 6, 4.0, now - timedelta(days=day))
    conn.commit()

    assert refresh.products_needing_forecast(conn, tenant) == [steady]
    result = run_forecast(conn, tenant, steady)
    assert result["status"] == "OK"
    assert refresh.products_needing_forecast(conn, tenant) == []

    data = overview.build_overview(conn, tenant)
    rows = {p["product_id"]: p for p in data["products"]}
    olive = rows[steady]
    assert olive["sold_last_30"] == pytest.approx(180, abs=6)
    assert olive["forecast_next_30"] == pytest.approx(180, rel=0.2)
    assert olive["trend"] == "stable"
    # 20 in stock against ~180 forecast units: restock, urgent.
    assert olive["stock_action"] == "restock" and olive["stock_priority"] == "high"
    assert olive["stock_suggested_qty"] >= 140
    assert olive["expected_revenue"] == pytest.approx(olive["forecast_next_30"] * 4.0)
    assert rows[unsold]["forecast_next_30"] is None and rows[unsold]["trend"] == "no_sales"
    assert data["totals"]["forecasted"] == 1 and data["totals"]["restock"] == 1

    history = [p for p in data["series"] if p["actual"] is not None]
    future = [p for p in data["series"] if p["forecast"] is not None]
    assert len(history) == overview.HISTORY_DAYS and len(future) == 30
    assert sum(p["forecast"] for p in future) == pytest.approx(olive["forecast_next_30"], rel=0.05)

    # A new sale after the forecast makes it stale again.
    with conn.cursor() as cursor:
        insert_sale(cursor, tenant, steady, 1, 4.0, now)
    conn.commit()
    assert refresh.products_needing_forecast(conn, tenant) == [steady]

    with conn.cursor() as cursor:
        _cleanup(cursor, tenant)
    conn.commit()


def test_overview_is_scoped_to_one_product_when_asked(conn):
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        tenant = _company(cursor)
        a = _product(cursor, tenant, {"en": "A"}, stock=100)
        b = _product(cursor, tenant, {"en": "B"}, stock=100)
        for day in range(1, 40):
            insert_sale(cursor, tenant, a, 2, 1.0, now - timedelta(days=day))
            insert_sale(cursor, tenant, b, 5, 1.0, now - timedelta(days=day))
    conn.commit()
    data = overview.build_overview(conn, tenant, product_id=a)
    assert data["totals"]["products"] == 1
    assert sum(p["actual"] or 0 for p in data["series"]) == pytest.approx(2 * 39)
    with conn.cursor() as cursor:
        _cleanup(cursor, tenant)
    conn.commit()


def test_cancelled_invoices_are_not_forecast_as_demand_or_reported_as_sales(conn):
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        tenant = _company(cursor)
        product = _product(cursor, tenant, {"en": "Cancelled sale test"})
        insert_sale(cursor, tenant, product, 4, 3.0, now - timedelta(days=2))
        insert_sale(cursor, tenant, product, 100, 3.0, now - timedelta(days=1))
        cursor.execute(
            "UPDATE invoices SET payment_status = 'CANCELLED' WHERE tenant_id = %s "
            "AND invoice_id = (SELECT i.invoice_id FROM invoices i JOIN invoice_items ii "
            "ON ii.tenant_id = i.tenant_id AND ii.invoice_id = i.invoice_id "
            "WHERE ii.tenant_id = %s AND ii.product_id = %s ORDER BY i.issue_date DESC LIMIT 1);",
            (tenant, tenant, product),
        )
    conn.commit()

    history = load_daily_demand(conn, tenant, product)
    assert history["quantity"].sum() == pytest.approx(4)
    assert refresh.products_needing_forecast(conn, tenant) == [product]
    report = overview.build_overview(conn, tenant, product_id=product)
    assert report["products"][0]["sold_last_30"] == pytest.approx(4)

    with conn.cursor() as cursor:
        _cleanup(cursor, tenant)
    conn.commit()


@pytest.mark.parametrize("lang, names, expected", [
    ("en", {"en": "Dates", "ar": "تمر"}, "Dates"),
    ("ar", {"en": "Dates", "ar": "تمر"}, "تمر"),
    ("ar", {"en": "Dates"}, "Dates"),
    ("en", {"ar": "تمر", "fr": "Dattes"}, "Dattes"),   # never Arabic in English when another name exists
    ("en", {"ar": "تمر"}, "تمر"),                       # the only name there is
    ("fr", {"en": "Dates", "fr": "Dattes"}, "Dattes"),
    ("en", {"en": "  ", "ar": "تمر", "fr": "Dattes"}, "Dattes"),
])
def test_localized_text_picks_the_interface_language(conn, lang, names, expected):
    with conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.lang', %s, true);", (lang,))
        cursor.execute("SELECT localized_text(%s::jsonb);", (json.dumps(names),))
        assert cursor.fetchone()[0] == expected
