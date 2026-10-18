"""
Integration tests for rag/business_analysis.py against a real PostgreSQL
instance (skipped unless AI_TEST_DATABASE_URL is set, like every other
live-DB test here). Tenant isolation through the restricted app role is
checked when APP_DB_PASSWORD is also set.
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.rag import business_analysis
from src.ai.tests.test_structured_context_integration_db import (
    _insert_company, _insert_competitor, _insert_competitor_price,
)

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

NOW = datetime.now(timezone.utc)


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    yield connection
    connection.rollback()
    connection.close()


def _product(conn, tenant_id, en, price, ar=None, stock=None, reorder_level=10):
    product_id = str(uuid.uuid4())
    name = {"en": en, **({"ar": ar} if ar else {})}
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps(name), price),
        )
        if stock is not None:
            cursor.execute(
                "INSERT INTO inventory (tenant_id, product_id, stock_quantity, reorder_level, safety_stock) VALUES (%s, %s, %s, %s, 0);",
                (tenant_id, product_id, stock, reorder_level),
            )
    return product_id


def _sale(conn, tenant_id, product_id, quantity, unit_price, days_ago):
    invoice_id = str(uuid.uuid4())
    total = quantity * unit_price
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'JOD');",
            (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", NOW - timedelta(days=days_ago), total, total),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) VALUES (%s, %s, %s, %s, %s, %s);",
            (tenant_id, invoice_id, product_id, quantity, unit_price, total),
        )


def _forecast(conn, tenant_id, product_id, expected_demand):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, forecast_target_date, model_version) "
            "VALUES (%s, %s, %s, %s, %s, 'test-model');",
            (str(uuid.uuid4()), tenant_id, product_id, expected_demand, date.today() + timedelta(days=30)),
        )


def test_declining_and_growing_products_compare_the_last_30_days_with_the_30_before(conn):
    tenant = _insert_company(conn)
    tea = _product(conn, tenant, "Mint Tea", 2.0, ar="شاي بالنعناع")
    soap = _product(conn, tenant, "Olive Soap", 3.0)
    rare = _product(conn, tenant, "Rare Item", 9.0)
    _sale(conn, tenant, tea, 40, 2.0, days_ago=45)
    _sale(conn, tenant, tea, 10, 2.0, days_ago=5)     # 40 -> 10: -75%
    _sale(conn, tenant, soap, 20, 3.0, days_ago=40)
    _sale(conn, tenant, soap, 30, 3.0, days_ago=3)    # 20 -> 30: +50%
    _sale(conn, tenant, rare, 2, 9.0, days_ago=40)    # too few units to call a trend
    conn.commit()

    block = business_analysis.product_trends_block(conn, tenant)
    declining, growing = block.split("Growing")
    assert "Mint Tea: 10 units in the last 30 days vs 40" in declining and "-75%" in declining
    assert "Olive Soap" in growing and "+50%" in growing
    assert "Rare Item" not in block
    assert "your own sales records" in block
    # An Arabic question gets the Arabic product name when there is one.
    assert "شاي بالنعناع" in business_analysis.product_trends_block(conn, tenant, language="ar")


def test_restock_uses_the_forecast_the_reorder_level_and_the_recent_pace(conn):
    tenant = _insert_company(conn)
    oil = _product(conn, tenant, "Olive Oil", 9.0, stock=20, reorder_level=5)
    _forecast(conn, tenant, oil, 80)                   # forecast 80 vs 20 in stock
    salt = _product(conn, tenant, "Sea Salt", 1.0, stock=3, reorder_level=10)   # below its reorder level
    figs = _product(conn, tenant, "Dried Figs", 4.0, stock=6, reorder_level=1)  # no forecast, sells 30/month
    _sale(conn, tenant, figs, 30, 4.0, days_ago=10)
    calm = _product(conn, tenant, "Calm Product", 4.0, stock=500, reorder_level=1)
    _sale(conn, tenant, calm, 3, 4.0, days_ago=10)
    conn.commit()

    block = business_analysis.restock_block(conn, tenant)
    assert "Olive Oil: 20 in stock, about 80 expected" in block and "order about 60 more" in block
    assert "Sea Salt: 3 in stock, at or below its reorder level of 10" in block
    assert "Dried Figs: 6 in stock lasts about 6 days" in block
    assert "Calm Product" not in block


def test_strongest_competitor_is_ranked_by_products_sold_for_less_and_the_rule_is_stated(conn):
    tenant = _insert_company(conn)
    a = _product(conn, tenant, "Product A", 10.0)
    b = _product(conn, tenant, "Product B", 20.0)
    cheap = _insert_competitor(conn, tenant, "Cheap Rival", tier="RELEVANT")
    pricey = _insert_competitor(conn, tenant, "Pricey Rival", tier="STRATEGIC")
    _insert_competitor(conn, tenant, "Unmatched Rival", tier="RELEVANT")
    conn.commit()
    _insert_competitor_price(conn, tenant, a, cheap, 8.0)
    _insert_competitor_price(conn, tenant, b, cheap, 18.0)
    _insert_competitor_price(conn, tenant, a, pricey, 12.0)
    conn.commit()

    block = business_analysis.competitor_comparison_block(conn, tenant)
    assert "Ranked strongest first by: how many of your products they sell for less than you" in block
    assert block.index("1. Cheap Rival") < block.index("2. Pricey Rival")
    assert "Cheap Rival: 2 of your products in common; cheaper than you on 2, more expensive on 0" in block
    # Every price line names the competitor it belongs to (attribution fix).
    assert "Product A: Cheap Rival charges 8 JOD vs your 10 JOD (cheaper than you" in block
    assert "they charge" not in block
    assert "Unmatched Rival: 0 of your products in common; no competitor price recorded yet" in block
    assert "never estimate those" in block


def test_blocks_are_only_built_for_questions_that_ask_for_them(conn):
    tenant = _insert_company(conn)
    _product(conn, tenant, "Thing", 5.0, stock=1, reorder_level=10)
    conn.commit()
    assert business_analysis.build_analysis_blocks(conn, tenant, "hello there") == []
    assert business_analysis.build_analysis_blocks(conn, tenant, "What should a pharmacy stock?") == []
    labels = [label for label, _ in business_analysis.build_analysis_blocks(conn, tenant, "Which products do I need to restock?")]
    assert labels == [business_analysis.LABEL_RADAR]
    assert business_analysis.build_analysis_blocks(conn, tenant, "ما هي المنتجات التي أحتاج إعادة تعبئة مخزونها؟")


@pytest.mark.skipif(not APP_DB_PASSWORD, reason="APP_DB_PASSWORD not set")
def test_a_company_only_ever_sees_its_own_products_and_competitors(conn):
    from src.ai.tests.test_conversation_store_integration_db import _app_conn
    from src.ai.tests.test_rls_integration_db import _ensure_role_key, _insert_user

    mine, theirs = _insert_company(conn), _insert_company(conn)
    my_product = _product(conn, mine, "My Product", 10.0, stock=1)
    their_product = _product(conn, theirs, "Their Secret Product", 10.0, stock=1)
    _sale(conn, mine, my_product, 10, 10.0, days_ago=40)
    _sale(conn, theirs, their_product, 10, 10.0, days_ago=40)
    their_rival = _insert_competitor(conn, theirs, "Their Rival")
    conn.commit()
    _insert_competitor_price(conn, theirs, their_product, their_rival, 5.0)
    with conn.cursor() as cursor:
        role_key = _ensure_role_key(cursor)
        user = _insert_user(cursor, "analysis-isolation")
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (mine, user, role_key))
    conn.commit()

    app = _app_conn(mine, user)
    try:
        text = "\n".join(
            block for _label, block in business_analysis.build_analysis_blocks(
                app, mine, "Which products are declining, what should I restock and who is my strongest competitor?",
            )
        )
    finally:
        app.rollback()
        app.close()
    assert "My Product" in text
    assert "Their Secret Product" not in text and "Their Rival" not in text
