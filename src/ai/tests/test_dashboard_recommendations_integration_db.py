"""
Integration tests for dashboard/recommendations.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set. The underlying rule
engine is already exhaustively covered by test_insights_cross_signal.py
and test_insights_pipeline_integration_db.py - these tests only verify
that this presentation-layer module correctly wraps and relabels that
engine's output for the dashboard.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.recommendations import get_top_recommendations

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


def _insert_competitor_price(conn, tenant_id, product_id, scraped_price):
    competitor_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
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
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency) VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, mapping_id, scraped_price),
        )


def _insert_invoice_with_item(conn, tenant_id, product_id, quantity, unit_price, issue_date):
    invoice_id = str(uuid.uuid4())
    total = quantity * unit_price
    with conn.cursor() as cursor:
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


def test_returns_empty_list_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    assert get_top_recommendations(conn, tenant_id) == []


def test_surfaces_a_real_pricing_insight_with_a_plain_priority_label(conn):
    """End-to-end through the shared insights engine: an overpriced
    product with falling sales must come back as a dashboard-shaped
    recommendation - product name in the message, a human category
    label (not the raw "pricing" internal string), and a plain priority
    word instead of the raw confidence float."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine", current_price=100.0)
    conn.commit()
    _insert_competitor_price(conn, tenant_id, product_id, scraped_price=70.0)  # 43% above market
    now = datetime.now(timezone.utc)
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=2, unit_price=100.0, issue_date=now - timedelta(days=5))
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=20, unit_price=100.0, issue_date=now - timedelta(days=45))
    conn.commit()

    recommendations = get_top_recommendations(conn, tenant_id)

    assert len(recommendations) == 1
    rec = recommendations[0]
    assert rec["product_id"] == product_id
    assert rec["category"] == "Pricing"  # relabeled, not the raw "pricing" category
    assert rec["priority"] in ("high", "medium", "low")
    assert "confidence" not in rec  # the raw score is never surfaced
    assert "Espresso Machine" in rec["message"]


def test_limit_caps_the_number_of_recommendations_returned(conn):
    tenant_id = _insert_company(conn)
    now = datetime.now(timezone.utc)
    for i in range(4):
        product_id = _insert_product(conn, tenant_id, f"Overpriced Widget {i}", current_price=100.0)
        conn.commit()
        _insert_competitor_price(conn, tenant_id, product_id, scraped_price=60.0)
        _insert_invoice_with_item(conn, tenant_id, product_id, quantity=1, unit_price=100.0, issue_date=now - timedelta(days=5))
        _insert_invoice_with_item(conn, tenant_id, product_id, quantity=20, unit_price=100.0, issue_date=now - timedelta(days=45))
        conn.commit()

    recommendations = get_top_recommendations(conn, tenant_id, limit=2)

    assert len(recommendations) == 2
