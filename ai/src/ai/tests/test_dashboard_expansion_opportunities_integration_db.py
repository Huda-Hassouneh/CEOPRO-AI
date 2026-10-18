"""
Integration tests for dashboard/expansion_opportunities.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import psycopg2
import pytest

from src.ai.dashboard.expansion_opportunities import get_expansion_opportunities

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


def _insert_product(conn, tenant_id, name, category_en=None) -> str:
    product_id = str(uuid.uuid4())
    category = json.dumps({"en": category_en}) if category_en else None
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, category, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), category),
        )
    return product_id


def _insert_competitor(conn, tenant_id, name, tier="STRATEGIC") -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, tier) VALUES (%s, %s, TRUE, %s);",
            (tenant_id, competitor_id, tier),
        )
    return competitor_id


def _insert_market_observation(conn, tenant_id, competitor_id, product_id, product_name, category):
    source_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) VALUES (%s, %s, 'Test Source', 'WEB_SCRAPE');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO ingestion_jobs (job_id, tenant_id, source_id) VALUES (%s, %s, %s);",
            (job_id, tenant_id, source_id),
        )
        cursor.execute(
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, source_id) "
            "VALUES (%s, %s, %s, %s, %s);",
            (mapping_id, tenant_id, competitor_id, product_id, source_id),
        )
        cursor.execute(
            """
            INSERT INTO market_observations
                (tenant_id, source_id, job_id, mapping_id, product_name, category, canonical_url,
                 match_score, match_method, safety_status, content_hash, observed_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'https://competitor.example.com/x', 0.95, 'FUZZY_NAME', 'SAFE', %s, %s);
            """,
            (tenant_id, source_id, job_id, mapping_id, product_name, category, "c" * 64, datetime.now(timezone.utc)),
        )


def test_returns_empty_list_for_a_brand_new_tenant_with_no_market_observations(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert get_expansion_opportunities(conn, tenant_id) == []


def test_returns_a_real_category_gap_as_a_structured_card_not_prose(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Widgets")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A", tier="STRATEGIC")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival B", tier="RELEVANT")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C Tablets", "Vitamins")
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D Drops", "Vitamins")
    conn.commit()

    opportunities = get_expansion_opportunities(conn, tenant_id)

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity["category"] == "Vitamins"
    assert opportunity["competitor_count"] == 2
    assert 0 <= opportunity["opportunity_score"] <= 100
    assert opportunity["note"]
