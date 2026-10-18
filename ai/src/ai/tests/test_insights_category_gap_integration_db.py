"""
Integration tests for insights/category_gap.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.insights.category_gap import MIN_COMPETITOR_MENTIONS, detect_category_gap_details, detect_category_gap_insights

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn, country_code="JO") -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}", country_code),
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


def _insert_competitor(conn, tenant_id, name, tier="STRATEGIC", is_tracked=True) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, tier) VALUES (%s, %s, %s, %s);",
            (tenant_id, competitor_id, is_tracked, tier),
        )
    return competitor_id


def _insert_market_observation(
    conn, tenant_id, competitor_id, product_id, product_name, category, safety_status="SAFE", observed_at=None,
):
    source_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    observed_at = observed_at or datetime.now(timezone.utc)
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
            VALUES (%s, %s, %s, %s, %s, %s, 'https://competitor.example.com/x', 0.95, 'FUZZY_NAME', %s, %s, %s);
            """,
            (tenant_id, source_id, job_id, mapping_id, product_name, category, safety_status, "b" * 64, observed_at),
        )


def test_returns_nothing_for_a_brand_new_tenant_with_no_competitor_observations(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert detect_category_gap_insights(conn, tenant_id) == []


def test_flags_a_category_two_tracked_competitors_carry_that_the_tenant_lacks(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Widgets")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A", tier="STRATEGIC")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival B", tier="RELEVANT")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C Tablets", "Vitamins")
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D Drops", "Vitamins")
    conn.commit()

    insights = detect_category_gap_insights(conn, tenant_id)

    assert len(insights) == 1
    assert "Vitamins" in insights[0].message
    assert "2 of your tracked competitors" in insights[0].message
    assert insights[0].category == "assortment"


def test_does_not_flag_a_category_the_tenant_already_carries(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Vitamins")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival B")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C", "Vitamins")
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D", "Vitamins")
    conn.commit()

    assert detect_category_gap_insights(conn, tenant_id) == []


def test_requires_at_least_min_competitor_mentions_not_just_one(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Widgets")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C", "Vitamins")
    conn.commit()

    assert MIN_COMPETITOR_MENTIONS == 2  # documents the real threshold this test relies on
    assert detect_category_gap_insights(conn, tenant_id) == []


def test_excludes_an_unconfirmed_candidate_tier_competitor_from_the_count(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Widgets")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A", tier="STRATEGIC")
    competitor_b = _insert_competitor(conn, tenant_id, "Unconfirmed", tier="CANDIDATE")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C", "Vitamins")
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D", "Vitamins")
    conn.commit()

    # Only 1 confirmed (STRATEGIC/RELEVANT) mention - below MIN_COMPETITOR_MENTIONS.
    assert detect_category_gap_insights(conn, tenant_id) == []


def test_excludes_quarantined_observations_from_the_count(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Widgets")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival B")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C", "Vitamins")
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D", "Vitamins", safety_status="QUARANTINED")
    conn.commit()

    assert detect_category_gap_insights(conn, tenant_id) == []


def test_excludes_observations_outside_the_recency_window(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Widgets")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival B")
    conn.commit()
    old_date = datetime.now(timezone.utc) - timedelta(days=400)
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C", "Vitamins", observed_at=old_date)
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D", "Vitamins", observed_at=old_date)
    conn.commit()

    assert detect_category_gap_insights(conn, tenant_id) == []


def test_details_returns_the_same_real_gap_as_structured_fields_not_prose(conn):
    """detect_category_gap_details() - the Market Intelligence dashboard's
    Expansion Opportunities source - reuses the exact same real gap
    detect_category_gap_insights() already found, just as fields instead
    of one composed sentence. Never a second, divergent detection rule."""
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Widget", category_en="Widgets")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival A", tier="STRATEGIC")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival B", tier="RELEVANT")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C Tablets", "Vitamins")
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D Drops", "Vitamins")
    conn.commit()

    details = detect_category_gap_details(conn, tenant_id)

    assert len(details) == 1
    assert details[0]["category"] == "Vitamins"
    assert details[0]["competitor_count"] == 2
    assert details[0]["note"]


def test_details_returns_nothing_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert detect_category_gap_details(conn, tenant_id) == []


def test_uses_the_pharmacy_playbooks_add_priority_note_for_a_pharmacy_catalog(conn):
    tenant_id = _insert_company(conn)
    own_product_id = _insert_product(conn, tenant_id, "Paracetamol Tablets", category_en="OTC Medicine")
    competitor_a = _insert_competitor(conn, tenant_id, "Rival Pharmacy A")
    competitor_b = _insert_competitor(conn, tenant_id, "Rival Pharmacy B")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_a, own_product_id, "Vitamin C Syrup", "Vitamins")
    _insert_market_observation(conn, tenant_id, competitor_b, own_product_id, "Vitamin D Drops", "Vitamins")
    conn.commit()

    insights = detect_category_gap_insights(conn, tenant_id)

    assert len(insights) == 1
    assert "licensing" in insights[0].message.lower()
