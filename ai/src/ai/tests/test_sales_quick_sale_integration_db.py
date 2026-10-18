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

from src.ai.sales.quick_sale import InsufficientStockError, ProductNotFoundError, record_quick_sale

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


def _insert_inventory(conn, tenant_id, product_id, stock_quantity) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO inventory (tenant_id, product_id, stock_quantity) VALUES (%s, %s, %s);",
            (tenant_id, product_id, stock_quantity),
        )


def test_decrements_real_tracked_stock_by_the_sold_quantity(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=10.0)
    _insert_inventory(conn, tenant_id, product_id, stock_quantity=10)
    conn.commit()

    record_quick_sale(conn, tenant_id, None, product_id, quantity=3)
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT stock_quantity FROM inventory WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        assert cursor.fetchone()[0] == 7


def test_rejects_a_sale_that_exceeds_real_tracked_stock(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=10.0)
    _insert_inventory(conn, tenant_id, product_id, stock_quantity=2)
    conn.commit()

    with pytest.raises(InsufficientStockError):
        record_quick_sale(conn, tenant_id, None, product_id, quantity=5)
    conn.rollback()

    with conn.cursor() as cursor:
        cursor.execute("SELECT stock_quantity FROM inventory WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        assert cursor.fetchone()[0] == 2

        cursor.execute("SELECT COUNT(*) FROM invoices WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 0


def test_allows_a_sale_that_exactly_matches_real_tracked_stock(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=10.0)
    _insert_inventory(conn, tenant_id, product_id, stock_quantity=5)
    conn.commit()

    record_quick_sale(conn, tenant_id, None, product_id, quantity=5)
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT stock_quantity FROM inventory WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        assert cursor.fetchone()[0] == 0


def test_skips_stock_tracking_untouched_when_no_inventory_row_exists(conn):
    """A product with no inventory row (stock never set) has nothing to
    decrement - the sale still records fine, and no orphan inventory row
    gets fabricated by the UPDATE (it simply matches zero rows)."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=10.0)
    conn.commit()

    record_quick_sale(conn, tenant_id, None, product_id, quantity=1)
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM inventory WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        assert cursor.fetchone()[0] == 0


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


def test_records_a_fractional_quantity_exactly(conn):
    """2.5 kg / 1.5 hours are real sales - quantity used to be int-only."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Tomatoes (kg)", current_price=1.235)
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO inventory (tenant_id, product_id, stock_quantity) VALUES (%s, %s, 10.5);", (tenant_id, product_id))
    conn.commit()

    result = record_quick_sale(conn, tenant_id, None, product_id, quantity=2.5)
    conn.commit()

    assert result["quantity"] == 2.5
    assert result["total_amount"] == 3.0875  # 2.5 x 1.235, exact
    with conn.cursor() as cursor:
        cursor.execute("SELECT stock_quantity FROM inventory WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        assert float(cursor.fetchone()[0]) == 8.0
