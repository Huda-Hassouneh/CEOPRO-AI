"""
Integration test for extraction/data_access.py against a real PostgreSQL
instance running the actual Final_schema.sql (+ migrations/). Same
convention as the other *_integration_db.py files: skipped unless
AI_TEST_DATABASE_URL is set.
"""

import json
import os
import uuid

import psycopg2
import pytest

from src.ai.extraction import data_access

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def seeded_tenant(conn):
    tenant_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    global_competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, 'Extraction Test Co', 'JO', 'JOD');
            """,
            (tenant_id,),
        )
        cursor.execute(
            """
            INSERT INTO products (product_id, tenant_id, product_name, current_price, currency)
            VALUES (%s, %s, %s, 18.00, 'JOD');
            """,
            (product_id, tenant_id, json.dumps({"en": "Sunscreen SPF 50", "ar": "واقي شمس"})),
        )
        cursor.execute(
            """
            INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id)
            VALUES (%s, 'Rival Pharmacy', 'PRIVATE', %s);
            """,
            (global_competitor_id, tenant_id),
        )
        cursor.execute(
            """
            INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked)
            VALUES (%s, %s, TRUE);
            """,
            (tenant_id, global_competitor_id),
        )
    conn.commit()
    return tenant_id, product_id, global_competitor_id


def test_load_known_product_names(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    names = data_access.load_known_product_names(conn, tenant_id)
    assert sorted(names) == ["Sunscreen SPF 50", "واقي شمس"]


def test_load_known_competitor_names(conn, seeded_tenant):
    tenant_id, _, _ = seeded_tenant
    names = data_access.load_known_competitor_names(conn, tenant_id)
    assert names == ["Rival Pharmacy"]


def test_load_known_product_names_excludes_soft_deleted(conn, seeded_tenant):
    """products.deleted_at must be respected."""
    tenant_id, product_id, _ = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET deleted_at = NOW() WHERE product_id = %s;", (product_id,))
    conn.commit()

    assert data_access.load_known_product_names(conn, tenant_id) == []


def test_load_known_competitor_names_excludes_untracked(conn, seeded_tenant):
    """tenant_competitors.is_tracked must be respected."""
    tenant_id, _, global_competitor_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE tenant_competitors SET is_tracked = FALSE WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, global_competitor_id),
        )
    conn.commit()

    assert data_access.load_known_competitor_names(conn, tenant_id) == []


def test_load_known_competitor_names_excludes_other_tenants_private_competitors(conn, seeded_tenant):
    """A PRIVATE competitor another tenant added, and never tracked by this one, must not leak in."""
    tenant_id, _, _ = seeded_tenant
    other_tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Other Co', 'JO', 'JOD');",
            (other_tenant_id,),
        )
        cursor.execute(
            "INSERT INTO global_competitors (competitor_name, visibility, added_by_tenant_id) "
            "VALUES ('Other Tenant Only Competitor', 'PRIVATE', %s);",
            (other_tenant_id,),
        )
    conn.commit()

    assert data_access.load_known_competitor_names(conn, tenant_id) == ["Rival Pharmacy"]


def test_load_known_names_empty_for_tenant_with_no_products(conn):
    other_tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, 'Empty Catalog Co', 'JO', 'JOD');
            """,
            (other_tenant_id,),
        )
    conn.commit()
    assert data_access.load_known_product_names(conn, other_tenant_id) == []
    assert data_access.load_known_competitor_names(conn, other_tenant_id) == []
