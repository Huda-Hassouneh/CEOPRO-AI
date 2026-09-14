"""
Integration tests for dashboard/price_competitiveness.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.price_competitiveness import get_price_competitiveness

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


def _insert_product_with_price(conn, tenant_id, name, current_price, competitor_price, observed_at=None) -> str:
    product_id = str(uuid.uuid4())
    competitor_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    observed_at = observed_at or datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, 'Rival Co', 'PRIVATE', %s, FALSE);",
            (competitor_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);",
            (tenant_id, competitor_id),
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
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, observed_at) "
            "VALUES (%s, %s, %s, 'JOD', %s);",
            (tenant_id, mapping_id, competitor_price, observed_at),
        )
    return product_id


def test_returns_none_score_with_no_competitor_price_data(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    result = get_price_competitiveness(conn, tenant_id)
    assert result == {"score": None, "change": None}


def test_computes_a_real_score_for_a_price_matching_the_market(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_price(conn, tenant_id, "Widget", current_price=100.0, competitor_price=100.0)
    conn.commit()

    result = get_price_competitiveness(conn, tenant_id)
    assert result["score"] == 10.0  # priced exactly at market = the best score


def test_score_drops_the_further_the_price_diverges_from_market(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_price(conn, tenant_id, "Widget", current_price=150.0, competitor_price=100.0)
    conn.commit()

    result = get_price_competitiveness(conn, tenant_id)
    assert result["score"] < 10.0


def test_change_is_none_with_no_prior_period_observation(conn):
    tenant_id = _insert_company(conn)
    _insert_product_with_price(conn, tenant_id, "Widget", current_price=100.0, competitor_price=100.0)
    conn.commit()

    result = get_price_competitiveness(conn, tenant_id)
    assert result["change"] is None
