"""
Integration tests for dashboard/inventory.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.ai.dashboard.inventory import get_inventory_status

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


def _insert_product_with_inventory(conn, tenant_id, name, stock_quantity, reorder_level=10) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
        cursor.execute(
            "INSERT INTO inventory (tenant_id, product_id, stock_quantity, reorder_level) VALUES (%s, %s, %s, %s);",
            (tenant_id, product_id, stock_quantity, reorder_level),
        )
    return product_id


def test_honestly_reports_no_data_for_a_tenant_with_no_inventory_rows(conn):
    """The real fix for the previously-fabricated 78%/24-products-low
    mockup card: a tenant who never had inventory rows written gets an
    explicit has_data=False, never an invented percentage."""
    tenant_id = _insert_company(conn)
    conn.commit()

    result = get_inventory_status(conn, tenant_id)
    assert result == {"has_data": False, "in_stock_pct": None, "low_stock_count": None, "tracked_products": 0}


def test_computes_a_real_in_stock_percentage(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_inventory(conn, tenant_id, "In Stock Widget", stock_quantity=50, reorder_level=10)
    _insert_product_with_inventory(conn, tenant_id, "Out of Stock Widget", stock_quantity=0, reorder_level=10)
    conn.commit()

    result = get_inventory_status(conn, tenant_id)
    assert result["has_data"] is True
    assert result["tracked_products"] == 2
    assert result["in_stock_pct"] == 50.0


def test_flags_a_real_low_stock_product(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_inventory(conn, tenant_id, "Low Stock Widget", stock_quantity=3, reorder_level=10)
    conn.commit()

    result = get_inventory_status(conn, tenant_id)
    assert result["low_stock_count"] == 1
