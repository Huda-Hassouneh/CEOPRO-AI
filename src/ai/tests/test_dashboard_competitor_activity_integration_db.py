"""
Integration tests for dashboard/competitor_activity.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.competitor_activity import get_recent_competitor_price_changes

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


def _insert_product(conn, tenant_id, name) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
    return product_id


def _insert_mapping(conn, tenant_id, product_id, competitor_name="Rival Co") -> str:
    competitor_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, competitor_name, tenant_id),
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
    return mapping_id


def _insert_price(conn, tenant_id, mapping_id, price, observed_at):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, observed_at) "
            "VALUES (%s, %s, %s, 'JOD', %s);",
            (tenant_id, mapping_id, price, observed_at),
        )


def test_returns_empty_list_with_no_price_history(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert get_recent_competitor_price_changes(conn, tenant_id) == []


def test_a_single_observation_produces_no_change_yet(conn):
    """Honest absence, not a bug: a real change needs two real data
    points - one observation alone has nothing to compare against."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    _insert_price(conn, tenant_id, mapping_id, 100.0, datetime.now(timezone.utc))
    conn.commit()

    assert get_recent_competitor_price_changes(conn, tenant_id) == []


def test_detects_a_real_price_decrease(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id, competitor_name="Umniah")
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_price(conn, tenant_id, mapping_id, 100.0, now - timedelta(days=2))
    _insert_price(conn, tenant_id, mapping_id, 90.0, now)
    conn.commit()

    changes = get_recent_competitor_price_changes(conn, tenant_id)
    assert len(changes) == 1
    change = changes[0]
    assert change["competitor_name"] == "Umniah"
    assert change["product_name"] == "Widget"
    assert change["latest_price"] == 90.0
    assert change["prior_price"] == 100.0
    assert change["price_change_pct"] == pytest.approx(-10.0)
    assert change["direction"] == "decrease"


def test_detects_a_real_price_increase(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_price(conn, tenant_id, mapping_id, 100.0, now - timedelta(days=2))
    _insert_price(conn, tenant_id, mapping_id, 110.0, now)
    conn.commit()

    changes = get_recent_competitor_price_changes(conn, tenant_id)
    assert len(changes) == 1
    assert changes[0]["price_change_pct"] == pytest.approx(10.0)
    assert changes[0]["direction"] == "increase"
