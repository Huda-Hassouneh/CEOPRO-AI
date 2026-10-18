"""
Regression tests (live DB, skipped unless AI_TEST_DATABASE_URL is set) for
a services business being unable to sell anything: create_product() used
to insert a zero-stock inventory row for every product, so selling one
"Haircut" or "Consulting hour" failed with "Only 0 unit(s) in stock" and
every service showed as out of stock on the dashboard.
"""
import os
import uuid

import psycopg2
import pytest

from src.ai.dashboard.inventory import get_inventory_status
from src.ai.routers.products import create_product
from src.ai.sales.quick_sale import record_quick_sale

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Salon Co', 'JO', 'JOD');",
            (tenant_id,),
        )
    return tenant_id


def test_a_service_without_stock_can_be_sold_and_is_not_counted_as_out_of_stock(conn):
    tenant_id = _company(conn)
    service = create_product(conn, tenant_id, None, {"en": "Haircut"}, None, {"en": "Services"}, None, 12.5, None, "JOD")
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM inventory WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 0
    sale = record_quick_sale(conn, tenant_id, None, service["product_id"], quantity=3)
    conn.commit()
    assert sale["total_amount"] == 37.5

    status = get_inventory_status(conn, tenant_id)
    assert status["has_data"] is False  # nothing tracked -> no fabricated 0% in-stock KPI


def test_a_product_created_with_stock_is_still_tracked_and_decremented(conn):
    tenant_id = _company(conn)
    product = create_product(conn, tenant_id, None, {"en": "Shampoo 250ml"}, None, None, None, 4.0, 2.1, "JOD", initial_stock_quantity=10)
    conn.commit()
    record_quick_sale(conn, tenant_id, None, product["product_id"], quantity=4)
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute("SELECT stock_quantity FROM inventory WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product["product_id"]))
        assert float(cursor.fetchone()[0]) == 6.0
