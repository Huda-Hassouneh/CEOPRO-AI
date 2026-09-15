"""
Integration tests for enqueue.py's new cost-margin gate wiring
(_load_mapped_product_ids / _cost_margin_gate_blocks) against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package: skipped unless AI_TEST_DATABASE_URL is set.

Tests the real gate logic directly against a plain connection rather than
through enqueue_collection() itself, which additionally needs a pooled,
RLS-actor connection (SCRAPER_DATABASE_URL/SCRAPER_ACTOR_USER_ID) and a
real Redis stream - infrastructure this module didn't change and doesn't
need re-verifying here. What's new and tested here is the actual decision
logic: resolving a source_id to its real mapped product(s) and combining
their individual gate decisions.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.market_scraper.cost_ledger import record_scrape_cost
from src.market_scraper.enqueue import _cost_margin_gate_blocks, _load_mapped_product_ids

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


def _insert_product(conn, tenant_id, name, current_price=1.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def _insert_source(conn, tenant_id) -> str:
    source_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) VALUES (%s, %s, 'Test Source', 'WEB_SCRAPE');",
            (source_id, tenant_id),
        )
    return source_id


def _insert_mapping_for_source(conn, tenant_id, product_id, source_id, competitor_name="Rival Co") -> str:
    competitor_id = str(uuid.uuid4())
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
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, source_id) "
            "VALUES (%s, %s, %s, %s, %s);",
            (mapping_id, tenant_id, competitor_id, product_id, source_id),
        )
    return mapping_id


def test_load_mapped_product_ids_finds_the_real_mapping(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    source_id = _insert_source(conn, tenant_id)
    _insert_mapping_for_source(conn, tenant_id, product_id, source_id)
    conn.commit()

    product_ids = _load_mapped_product_ids(conn, tenant_id, source_id)
    assert product_ids == [product_id]


def test_load_mapped_product_ids_empty_for_an_unmapped_source(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_source(conn, tenant_id)
    conn.commit()
    assert _load_mapped_product_ids(conn, tenant_id, source_id) == []


def test_gate_never_blocks_a_source_with_no_mapped_product(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_source(conn, tenant_id)
    conn.commit()

    blocked, reason = _cost_margin_gate_blocks(conn, tenant_id, source_id)
    assert blocked is False
    assert "no mapped product" in reason


def test_gate_allows_when_the_mapped_product_is_under_ratio(conn, monkeypatch):
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.01")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=1.0)
    source_id = _insert_source(conn, tenant_id)
    _insert_mapping_for_source(conn, tenant_id, product_id, source_id)
    conn.commit()

    blocked, reason = _cost_margin_gate_blocks(conn, tenant_id, source_id)
    assert blocked is False


def test_gate_blocks_when_the_only_mapped_product_is_over_ratio(conn, monkeypatch):
    """Priced at $5.00 (above the $1.00 minimum price floor) so this test
    genuinely exercises the ratio-blocking path, not the floor - the floor
    has its own dedicated test below."""
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.15")
    monkeypatch.setenv("COST_GATE_MAX_RATIO", "0.20")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Ratio Widget", current_price=5.00)
    source_id = _insert_source(conn, tenant_id)
    mapping_id = _insert_mapping_for_source(conn, tenant_id, product_id, source_id)
    conn.commit()
    for _ in range(20):
        record_scrape_cost(conn, tenant_id, mapping_id, "market_source")
    conn.commit()

    blocked, reason = _cost_margin_gate_blocks(conn, tenant_id, source_id)
    assert blocked is True
    assert "every mapped product is over its cost-to-margin limit" in reason


def test_gate_allows_a_source_when_any_one_of_several_mapped_products_is_still_ok(conn, monkeypatch):
    """Priced at $5.00 (above the $1.00 minimum price floor) so the
    over-budget product is blocked by the ratio, not the floor - keeping
    this test's original intent (mixed ratio outcomes across a source's
    mapped products) unambiguous."""
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.15")
    monkeypatch.setenv("COST_GATE_MAX_RATIO", "0.20")
    tenant_id = _insert_company(conn)
    source_id = _insert_source(conn, tenant_id)

    over_budget_product = _insert_product(conn, tenant_id, "Ratio Widget", current_price=5.00)
    healthy_product = _insert_product(conn, tenant_id, "Pricier Widget", current_price=50.0)
    over_mapping = _insert_mapping_for_source(conn, tenant_id, over_budget_product, source_id, "Rival A")
    _insert_mapping_for_source(conn, tenant_id, healthy_product, source_id, "Rival B")
    conn.commit()
    for _ in range(20):
        record_scrape_cost(conn, tenant_id, over_mapping, "market_source")
    conn.commit()

    blocked, reason = _cost_margin_gate_blocks(conn, tenant_id, source_id)
    assert blocked is False
    assert "at least one mapped product" in reason


def test_gate_blocks_a_cheap_product_through_the_minimum_price_floor(conn):
    """The floor blocks a sub-$1.00 product immediately, with zero ledger
    rows - this is the enqueue-level counterpart to the floor tests in
    test_cost_ledger_integration_db.py, confirming _cost_margin_gate_blocks()
    surfaces the floor's block reason too, not just the ratio's."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Cheap Widget", current_price=0.80)
    source_id = _insert_source(conn, tenant_id)
    _insert_mapping_for_source(conn, tenant_id, product_id, source_id)
    conn.commit()

    blocked, reason = _cost_margin_gate_blocks(conn, tenant_id, source_id)
    assert blocked is True
    assert "minimum price floor" in reason
