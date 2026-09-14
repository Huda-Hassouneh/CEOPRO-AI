"""
Integration tests for sales/quick_sale.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.ai.sales.quick_sale import ProductNotFoundError, record_quick_sale

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


def _insert_product(conn, tenant_id, name, current_price=25.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def test_records_a_real_sale_at_the_products_own_price(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=25.0)
    conn.commit()

    result = record_quick_sale(conn, tenant_id, None, product_id, quantity=3)
    conn.commit()

    assert result["product_name"] == "Widget"
    assert result["unit_price"] == 25.0
    assert result["total_amount"] == 75.0
    assert result["currency"] == "JOD"

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT payment_status, total_amount FROM invoices WHERE invoice_id = %s;",
            (result["invoice_id"],),
        )
        payment_status, total_amount = cursor.fetchone()
        assert payment_status == "PAID"
        assert float(total_amount) == 75.0

        cursor.execute(
            "SELECT quantity, unit_price, total_price FROM invoice_items WHERE invoice_id = %s;",
            (result["invoice_id"],),
        )
        quantity, unit_price, total_price = cursor.fetchone()
        assert quantity == 3
        assert float(unit_price) == 25.0
        assert float(total_price) == 75.0


def test_honors_a_real_overridden_unit_price(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=25.0)
    conn.commit()

    result = record_quick_sale(conn, tenant_id, None, product_id, quantity=2, unit_price=20.0)
    conn.commit()

    assert result["unit_price"] == 20.0
    assert result["total_amount"] == 40.0


def test_raises_for_a_product_that_does_not_exist(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    with pytest.raises(ProductNotFoundError):
        record_quick_sale(conn, tenant_id, None, str(uuid.uuid4()), quantity=1)


def test_raises_for_a_soft_deleted_product(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET deleted_at = NOW() WHERE product_id = %s;", (product_id,))
    conn.commit()

    with pytest.raises(ProductNotFoundError):
        record_quick_sale(conn, tenant_id, None, product_id, quantity=1)


def test_shows_up_in_the_real_dashboard_metrics_revenue(conn):
    """The whole point of writing to invoices/invoice_items: every
    existing real reader of that table (dashboard/metrics.py's Revenue
    card among them) sees a quick sale immediately, with no separate
    wiring needed."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=10.0)
    conn.commit()
    record_quick_sale(conn, tenant_id, None, product_id, quantity=5)
    conn.commit()

    from src.ai.dashboard.metrics import get_dashboard_metrics
    result = get_dashboard_metrics(conn, tenant_id)
    assert result["revenue"]["amount"] == 50.0
    assert result["units_sold"]["units"] == 5
