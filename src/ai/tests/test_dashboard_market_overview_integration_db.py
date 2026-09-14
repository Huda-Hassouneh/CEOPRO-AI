"""
Integration tests for dashboard/market_overview.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.market_overview import get_market_overview
from src.ai.sentiment.evidence import insert_sentiment_result

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


def _insert_product(conn, tenant_id, name, category=None) -> str:
    product_id = str(uuid.uuid4())
    category_json = json.dumps({"en": category}) if category else None
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, category, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), category_json),
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
    return competitor_id, mapping_id


def _insert_price(conn, tenant_id, mapping_id, price, observed_at):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, observed_at) "
            "VALUES (%s, %s, %s, 'JOD', %s);",
            (tenant_id, mapping_id, price, observed_at),
        )


def _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_id, positive_probability, negative_probability):
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, competitor_id, source_platform, review_text) "
            "VALUES (%s, %s, 'COMPETITOR', %s, 'GOOGLE', 'A review.');",
            (review_id, tenant_id, competitor_id),
        )
    neutral_probability = 1.0 - positive_probability - negative_probability
    insert_sentiment_result(
        conn, review_id, tenant_id, "POSITIVE", positive_probability, neutral_probability,
        negative_probability, 0.9, "test-model-v1",
    )


def test_returns_honest_empty_state_for_a_tenant_with_no_data(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = get_market_overview(conn, tenant_id)

    assert result["price_trend"]["direction"] is None
    assert result["sentiment"]["label"] is None
    assert result["category_activity"] == {}


def test_price_trend_is_up_when_more_real_increases_than_decreases(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    _, mapping_a = _insert_mapping(conn, tenant_id, product_id, "Rival A")
    _, mapping_b = _insert_mapping(conn, tenant_id, product_id, "Rival B")
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_price(conn, tenant_id, mapping_a, 100.0, now - timedelta(days=2))
    _insert_price(conn, tenant_id, mapping_a, 110.0, now)
    _insert_price(conn, tenant_id, mapping_b, 100.0, now - timedelta(days=2))
    _insert_price(conn, tenant_id, mapping_b, 108.0, now)
    conn.commit()

    result = get_market_overview(conn, tenant_id)
    assert result["price_trend"]["direction"] == "Up"
    assert result["price_trend"]["increases"] == 2
    assert result["price_trend"]["decreases"] == 0


def test_price_trend_is_none_below_the_minimum_real_sample(conn):
    """A single detected change isn't a market direction yet - matches
    this module's own PRICE_TREND_MIN_CHANGES discipline."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    _, mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_price(conn, tenant_id, mapping_id, 100.0, now - timedelta(days=2))
    _insert_price(conn, tenant_id, mapping_id, 110.0, now)
    conn.commit()

    result = get_market_overview(conn, tenant_id)
    assert result["price_trend"]["direction"] is None


def test_sentiment_is_bullish_with_mostly_positive_competitors(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_a, _ = _insert_mapping(conn, tenant_id, product_id, "Rival A")
    competitor_b, _ = _insert_mapping(conn, tenant_id, product_id, "Rival B")
    conn.commit()
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_a, positive_probability=0.9, negative_probability=0.05)
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_b, positive_probability=0.85, negative_probability=0.05)
    conn.commit()

    result = get_market_overview(conn, tenant_id)
    assert result["sentiment"]["label"] == "Bullish"
    assert result["sentiment"]["positive_pct"] == 100.0


def test_sentiment_is_bearish_with_mostly_negative_competitors(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_a, _ = _insert_mapping(conn, tenant_id, product_id, "Rival A")
    conn.commit()
    _insert_competitor_review_with_sentiment(conn, tenant_id, competitor_a, positive_probability=0.05, negative_probability=0.9)
    conn.commit()

    result = get_market_overview(conn, tenant_id)
    assert result["sentiment"]["label"] == "Bearish"
    assert result["sentiment"]["positive_pct"] == 0.0


def test_category_activity_rolls_up_the_real_per_competitor_level(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", category="Electronics")
    competitor_id, mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    for i, price in enumerate([100.0, 95.0, 90.0, 85.0]):
        _insert_price(conn, tenant_id, mapping_id, price, now - timedelta(days=4 - i))
    conn.commit()

    result = get_market_overview(conn, tenant_id)
    assert result["category_activity"] == {"Electronics": "High"}


def test_category_activity_omits_uncategorized_products(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", category=None)
    _, mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    _insert_price(conn, tenant_id, mapping_id, 100.0, datetime.now(timezone.utc))
    conn.commit()

    result = get_market_overview(conn, tenant_id)
    assert result["category_activity"] == {}
