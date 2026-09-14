"""
Integration tests for dashboard/search.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.ai.dashboard.search import search

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


def test_returns_empty_for_a_blank_query(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert search(conn, tenant_id, "") == {"products": [], "competitors": []}


def test_finds_a_real_product_by_name_substring(conn):
    tenant_id = _insert_company(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (str(uuid.uuid4()), tenant_id, json.dumps({"en": "Raspberry Pi 5"})),
        )
    conn.commit()

    result = search(conn, tenant_id, "raspberry")
    assert len(result["products"]) == 1
    assert result["products"][0]["name"] == "Raspberry Pi 5"
    assert result["competitors"] == []


def test_finds_a_real_tracked_competitor_by_name_substring(conn):
    tenant_id = _insert_company(conn)
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, 'SparkFun Electronics', 'https://sparkfun.com', 'PRIVATE', %s, FALSE);",
            (competitor_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);",
            (tenant_id, competitor_id),
        )
    conn.commit()

    result = search(conn, tenant_id, "sparkfun")
    assert len(result["competitors"]) == 1
    assert result["competitors"][0]["name"] == "SparkFun Electronics"
    assert result["competitors"][0]["website_url"] == "https://sparkfun.com"


def test_omits_an_untracked_competitor(conn):
    tenant_id = _insert_company(conn)
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, 'Untracked Rival', 'PRIVATE', %s, FALSE);",
            (competitor_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, FALSE);",
            (tenant_id, competitor_id),
        )
    conn.commit()

    result = search(conn, tenant_id, "untracked")
    assert result["competitors"] == []
