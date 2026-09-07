"""
Integration test for product_families.py::select_family_representatives
against a real PostgreSQL instance (needs real transactions rows).
Skipped unless AI_TEST_DATABASE_URL is set, same convention as every
other *_integration_db.py test in this package.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.market_scraper.product_families import select_family_representatives

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


def _insert_product(conn, tenant_id: str, name: str) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
    return product_id


def _insert_transaction(conn, tenant_id: str, product_id: str, quantity: int):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO transactions "
            "(tenant_id, product_id, quantity_sold, unit_price, total_price, original_currency, transaction_date) "
            "VALUES (%s, %s, %s, 10.0, %s, 'JOD', NOW());",
            (tenant_id, product_id, quantity, 10.0 * quantity),
        )


def test_highest_selling_family_member_is_the_representative(conn):
    tenant_id = _insert_company(conn)
    low = _insert_product(conn, tenant_id, "1k Ohm Resistor")
    high = _insert_product(conn, tenant_id, "2k Ohm Resistor")
    _insert_transaction(conn, tenant_id, low, 5)
    _insert_transaction(conn, tenant_id, high, 500)

    products = [
        {"product_id": low, "product_name": "1k Ohm Resistor"},
        {"product_id": high, "product_name": "2k Ohm Resistor"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 1
    assert representatives[0]["product_id"] == high
    assert {m["product_id"] for m in representatives[0]["family_members"]} == {low, high}


def test_family_with_no_sales_data_falls_back_to_alphabetical(conn):
    tenant_id = _insert_company(conn)
    ten = _insert_product(conn, tenant_id, "Trail Shoe Size 10")
    nine = _insert_product(conn, tenant_id, "Trail Shoe Size 9")

    products = [
        {"product_id": ten, "product_name": "Trail Shoe Size 10"},
        {"product_id": nine, "product_name": "Trail Shoe Size 9"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 1  # same family - only the size number differs
    # No sales data for either - falls back to sorting by product_name as a
    # plain string (deterministic, not volume-based): "...10" < "...9" lexicographically.
    assert representatives[0]["product_id"] == ten


def test_genuinely_different_products_produce_separate_families(conn):
    tenant_id = _insert_company(conn)
    resistor = _insert_product(conn, tenant_id, "1k Ohm Resistor")
    pi = _insert_product(conn, tenant_id, "Raspberry Pi 4")

    products = [
        {"product_id": resistor, "product_name": "1k Ohm Resistor"},
        {"product_id": pi, "product_name": "Raspberry Pi 4"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 2
