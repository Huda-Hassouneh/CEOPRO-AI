"""
Integration tests for dashboard/competitors.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.ai.dashboard.competitors import get_competitor_directory
from src.ai.pricing.competitor_classification import TIER_CANDIDATE, TIER_RELEVANT, TIER_STRATEGIC

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


def _insert_product(conn, tenant_id, name, current_price=50.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def _insert_tracked_competitor(
    conn, tenant_id, name, tier, match_rate, website_url=None, is_tracked=True,
) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, website_url, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, tier, product_match_rate, is_tracked, is_confirmed_competitor) "
            "VALUES (%s, %s, %s, %s, %s, %s);",
            (tenant_id, competitor_id, tier, match_rate, is_tracked, is_tracked),
        )
    return competitor_id


def _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price, their_price):
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE products SET current_price = %s WHERE product_id = %s;",
            (your_price, product_id),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) VALUES (%s, %s, 'Test Source', 'WEB_SCRAPE');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, source_id) "
            "VALUES (%s, %s, %s, %s, %s);",
            (mapping_id, tenant_id, competitor_id, product_id, source_id),
        )
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency) VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, mapping_id, their_price),
        )


def test_returns_empty_groups_for_a_tenant_with_no_competitors(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert get_competitor_directory(conn, tenant_id) == {"strategic": [], "relevant": []}


def test_strategic_competitor_shows_name_tier_website_and_exact_overlap_pct(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(
        conn, tenant_id, "SparkFun Electronics", TIER_STRATEGIC, match_rate=0.75,
        website_url="https://sparkfun.com",
    )
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)

    assert directory["relevant"] == []
    assert len(directory["strategic"]) == 1
    row = directory["strategic"][0]
    assert row["name"] == "SparkFun Electronics"
    assert row["tier"] == TIER_STRATEGIC
    assert row["website_url"] == "https://sparkfun.com"
    assert row["overlap_pct"] == 75.0
    assert "price_comparisons" not in row


def test_relevant_competitor_shows_name_tier_website_and_price_comparisons(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_tracked_competitor(
        conn, tenant_id, "PiShop US", TIER_RELEVANT, match_rate=0.33,
        website_url="https://pishop.us",
    )
    conn.commit()
    _map_product_with_price(conn, tenant_id, product_id, competitor_id, your_price=60.0, their_price=45.0)
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)

    assert directory["strategic"] == []
    assert len(directory["relevant"]) == 1
    row = directory["relevant"][0]
    assert row["name"] == "PiShop US"
    assert row["tier"] == TIER_RELEVANT
    assert row["website_url"] == "https://pishop.us"
    assert "overlap_pct" not in row
    assert row["price_comparisons"] == [
        {"product_name": "Widget", "your_price": 60.0, "their_price": 45.0, "currency": "JOD"},
    ]


def test_omits_untracked_candidate_tier_competitors_entirely(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(
        conn, tenant_id, "Excluded Manufacturer", TIER_CANDIDATE, match_rate=0.0, is_tracked=False,
    )
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)
    assert directory == {"strategic": [], "relevant": []}


def test_groups_are_sorted_alphabetically_by_name(conn):
    tenant_id = _insert_company(conn)
    _insert_tracked_competitor(conn, tenant_id, "Zebra Corp", TIER_STRATEGIC, match_rate=0.9)
    _insert_tracked_competitor(conn, tenant_id, "Acme Inc", TIER_STRATEGIC, match_rate=0.8)
    conn.commit()

    directory = get_competitor_directory(conn, tenant_id)
    assert [row["name"] for row in directory["strategic"]] == ["Acme Inc", "Zebra Corp"]
