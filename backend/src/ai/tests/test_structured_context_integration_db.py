"""
Integration tests for rag/structured_context.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.rag.structured_context import build_structured_facts_block

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


def _insert_product(conn, tenant_id, name, current_price=50.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def _insert_competitor(conn, tenant_id, name, tier="STRATEGIC", website_url=None, is_tracked=True) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, website_url, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, tier) VALUES (%s, %s, %s, %s);",
            (tenant_id, competitor_id, is_tracked, tier),
        )
    return competitor_id


def _insert_competitor_price(conn, tenant_id, product_id, competitor_id, scraped_price):
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
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
            (tenant_id, mapping_id, scraped_price),
        )


def test_returns_empty_string_for_a_brand_new_tenant_with_no_data(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert build_structured_facts_block(conn, tenant_id) == ""


def test_includes_real_competitor_tier_counts(conn):
    tenant_id = _insert_company(conn)
    _insert_competitor(conn, tenant_id, "Rival A", tier="STRATEGIC")
    _insert_competitor(conn, tenant_id, "Rival B", tier="STRATEGIC")
    _insert_competitor(conn, tenant_id, "Rival C", tier="RELEVANT")
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "2 STRATEGIC" in block
    assert "1 RELEVANT" in block


def test_includes_real_competitor_names_not_just_a_count(conn):
    """The real fix: "who are my competitors?" used to get only a bare
    tier count back (no way to name anyone) even though the competitor's
    real name is already persisted the moment discovery registers it -
    this is injected always-on (never dependent on retrieval having
    ranked the right RAG chunk highly enough), same guarantee this
    module already gives exact numbers."""
    tenant_id = _insert_company(conn)
    _insert_competitor(conn, tenant_id, "SparkFun Electronics", tier="STRATEGIC", website_url="https://sparkfun.com")
    _insert_competitor(conn, tenant_id, "PiShop US", tier="RELEVANT")
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "SparkFun Electronics" in block
    assert "https://sparkfun.com" in block
    assert "PiShop US" in block


def test_omits_untracked_competitors_from_the_named_list(conn):
    tenant_id = _insert_company(conn)
    _insert_competitor(conn, tenant_id, "Untracked Rival", tier="CANDIDATE", is_tracked=False)
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Untracked Rival" not in block


def test_includes_real_price_gap(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=60.0)
    competitor_id = _insert_competitor(conn, tenant_id, "Rival Co")
    conn.commit()
    _insert_competitor_price(conn, tenant_id, product_id, competitor_id, scraped_price=45.0)
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Widget" in block
    assert "60.00 JOD" in block
    assert "45.00 JOD" in block


def _insert_forecast(conn, tenant_id, product_id, expected_demand, target_date):
    forecast_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, forecast_target_date, model_version) "
            "VALUES (%s, %s, %s, %s, %s, 'test-model');",
            (forecast_id, tenant_id, product_id, expected_demand, target_date),
        )
    return forecast_id


def test_includes_real_demand_forecast(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()
    target_date = (datetime.now(timezone.utc) + timedelta(days=7)).date()
    _insert_forecast(conn, tenant_id, product_id, expected_demand=42, target_date=target_date)
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Widget" in block
    assert "42 units" in block
    assert target_date.isoformat() in block


def test_includes_a_real_proactive_insight_without_being_asked(conn):
    """
    The real requirement this covers: the chatbot must weave in a
    relevant strategic observation on ANY question, not only when the
    user explicitly asks for "advice" or "recommendations" - so the top
    cross-signal insights must appear in the ALWAYS-injected facts block,
    not only in the separately-retrieved strategic_insights RAG slot.
    """
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine", current_price=100.0)
    competitor_id = _insert_competitor(conn, tenant_id, "Cheaper Co")
    conn.commit()
    _insert_competitor_price(conn, tenant_id, product_id, competitor_id, scraped_price=70.0)
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        for quantity, days_ago, unit_price in ((2, 5, 100.0), (20, 45, 100.0)):
            invoice_id = str(uuid.uuid4())
            issue_date = now - timedelta(days=days_ago)
            total = quantity * unit_price
            cursor.execute(
                "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'JOD');",
                (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", issue_date, total, total),
            )
            cursor.execute(
                "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                (tenant_id, invoice_id, product_id, quantity, unit_price, total),
            )
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)

    assert "Proactive insights" in block
    assert "Espresso Machine" in block


def test_includes_real_business_sentiment_score(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, source_platform, review_text) "
            "VALUES (%s, %s, 'BUSINESS', 'GOOGLE', 'Great service.');",
            (review_id, tenant_id),
        )
    from src.ai.sentiment.evidence import insert_sentiment_result
    insert_sentiment_result(conn, review_id, tenant_id, "POSITIVE", 0.8, 0.1, 0.1, 0.9, "test-model-v1")
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Current overall sentiment score" in block
    assert "0.70" in block  # positive_probability(0.8) - negative_probability(0.1)


def _insert_market_observation(
    conn, tenant_id, competitor_id, product_id, product_name, category=None,
    canonical_url="https://competitor.example.com/product-x", safety_status="SAFE", observed_at=None,
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0.95, 'FUZZY_NAME', %s, %s, %s);
            """,
            (tenant_id, source_id, job_id, mapping_id, product_name, category, canonical_url,
             safety_status, "a" * 64, observed_at),
        )
    return mapping_id


def test_includes_real_competitor_activity_with_a_direct_link(conn):
    """The real fix: market_observations.canonical_url was already
    collected by the scraper/social collectors, but nothing in ai/ ever
    read it - a question like "can you show me proof" or "why did my
    sales drop" had no real link to offer. STRATEGIC/RELEVANT tier only -
    "absolutely sure it's a real competitor"."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_competitor(conn, tenant_id, "Rival Co", tier="STRATEGIC")
    conn.commit()
    _insert_market_observation(
        conn, tenant_id, competitor_id, product_id, "Rival Widget Pro", category="Widgets",
        canonical_url="https://rivalco.example.com/widget-pro",
    )
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Rival Co" in block
    assert "Rival Widget Pro" in block
    assert "https://rivalco.example.com/widget-pro" in block


def test_excludes_competitor_activity_from_an_unconfirmed_candidate_tier(conn):
    """The confidence gate: a CANDIDATE competitor hasn't been confirmed
    as a real, relevant competitor yet - never surfaced as "proof" of
    anything."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_competitor(conn, tenant_id, "Unconfirmed Co", tier="CANDIDATE")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_id, product_id, "Some Product")
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Unconfirmed Co" not in block


def test_excludes_quarantined_competitor_activity(conn):
    """A QUARANTINED observation was held back by the platform's own
    safety review - never surfaced here as real evidence."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_competitor(conn, tenant_id, "Rival Co", tier="STRATEGIC")
    conn.commit()
    _insert_market_observation(conn, tenant_id, competitor_id, product_id, "Flagged Product", safety_status="QUARANTINED")
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Flagged Product" not in block


def test_excludes_competitor_activity_older_than_the_recency_window(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    competitor_id = _insert_competitor(conn, tenant_id, "Rival Co", tier="STRATEGIC")
    conn.commit()
    old_date = datetime.now(timezone.utc) - timedelta(days=90)
    _insert_market_observation(conn, tenant_id, competitor_id, product_id, "Stale Product", observed_at=old_date)
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)
    assert "Stale Product" not in block


def test_includes_last_30_days_sales_and_top_products_like_the_dashboard(conn):
    tenant_id = _insert_company(conn)
    oil = _insert_product(conn, tenant_id, "Olive Oil 1L", current_price=9.5)
    dates = _insert_product(conn, tenant_id, "Medjool Dates 1kg", current_price=8.0)
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        for product_id, quantity, unit_price, days_ago in ((oil, 10, 9.5, 3), (dates, 4, 8.0, 10), (oil, 50, 9.5, 40)):
            invoice_id = str(uuid.uuid4())
            total = quantity * unit_price
            cursor.execute(
                "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'JOD');",
                (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", now - timedelta(days=days_ago), total, total),
            )
            cursor.execute(
                "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                (tenant_id, invoice_id, product_id, quantity, unit_price, total),
            )
    conn.commit()

    block = build_structured_facts_block(conn, tenant_id)

    # 95 + 32 in the last 30 days; the 475 sale 40 days ago is the prior window.
    assert "Revenue 127 JOD from 2 invoices; the 30 days before: 475 JOD." in block
    top = block[block.index("Top products by revenue"):]
    assert top.index("Olive Oil 1L: 95 JOD from 10 units") < top.index("Medjool Dates 1kg: 32 JOD from 4 units")
