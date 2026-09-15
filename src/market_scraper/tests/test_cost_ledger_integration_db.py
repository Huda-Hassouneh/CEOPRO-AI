"""
Integration tests for cost_ledger.py against a real PostgreSQL instance.
Same convention as every other live-DB test in this package: skipped
unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.market_scraper.cost_ledger import evaluate_cost_margin_gate, record_scrape_cost

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


def _insert_product(conn, tenant_id, name, current_price=1.0, cost_price=None) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, cost_price, currency) "
            "VALUES (%s, %s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price, cost_price),
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


# ---------------------------------------------------------------------------
# record_scrape_cost()
# ---------------------------------------------------------------------------

def test_records_a_real_row_with_known_cost_when_configured(conn, monkeypatch):
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.02")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()

    cost_id = record_scrape_cost(conn, tenant_id, mapping_id, "market_source")
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT cost_amount, collector_key FROM scraping_cost_ledger WHERE cost_id = %s;", (cost_id,))
        cost_amount, collector_key = cursor.fetchone()
    assert float(cost_amount) == 0.02
    assert collector_key == "market_source"


def test_records_an_honest_unknown_cost_when_not_configured(conn, monkeypatch):
    monkeypatch.delenv("SCRAPE_COST_PER_REQUEST_UNCONFIGURED_VENDOR", raising=False)
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()

    cost_id = record_scrape_cost(conn, tenant_id, mapping_id, "unconfigured_vendor")
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SELECT cost_amount FROM scraping_cost_ledger WHERE cost_id = %s;", (cost_id,))
        (cost_amount,) = cursor.fetchone()
    assert cost_amount is None  # honestly unknown, never a fabricated 0.00


# ---------------------------------------------------------------------------
# evaluate_cost_margin_gate()
# ---------------------------------------------------------------------------

def test_allows_when_product_does_not_exist(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    decision = evaluate_cost_margin_gate(conn, tenant_id, str(uuid.uuid4()))
    assert decision.allow is True
    assert "no real product record" in decision.reason


def test_allows_when_no_cost_data_recorded_yet(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=1.0)
    conn.commit()
    decision = evaluate_cost_margin_gate(conn, tenant_id, product_id)
    assert decision.allow is True
    assert "no real scraping cost data" in decision.reason
    assert decision.basis_amount == 1.0
    assert decision.basis_kind == "price"


def test_uses_real_margin_when_cost_price_is_set(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=1.0, cost_price=0.60)
    conn.commit()
    decision = evaluate_cost_margin_gate(conn, tenant_id, product_id)
    assert decision.basis_kind == "margin"
    assert decision.basis_amount == pytest.approx(0.40)


def test_falls_back_to_price_when_cost_price_is_unset(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=1.0, cost_price=None)
    conn.commit()
    decision = evaluate_cost_margin_gate(conn, tenant_id, product_id)
    assert decision.basis_kind == "price"
    assert decision.basis_amount == 1.0


def test_allows_a_product_well_under_the_ratio(conn, monkeypatch):
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.01")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=1.0, cost_price=0.50)
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    record_scrape_cost(conn, tenant_id, mapping_id, "market_source")  # 0.01 / 0.50 margin = 2%
    conn.commit()

    decision = evaluate_cost_margin_gate(conn, tenant_id, product_id, max_ratio=0.20)
    assert decision.allow is True
    assert decision.ratio == pytest.approx(0.02)


def test_blocks_a_product_at_or_over_the_ratio(conn, monkeypatch):
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.15")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Cheap Widget", current_price=0.80, cost_price=None)
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    for _ in range(20):  # 20 x 0.15 = 3.00, vs 0.80 price -> 375%
        record_scrape_cost(conn, tenant_id, mapping_id, "market_source")
    conn.commit()

    decision = evaluate_cost_margin_gate(conn, tenant_id, product_id, max_ratio=0.20)
    assert decision.allow is False
    assert decision.ratio > 0.20
    assert "over its cost-to-margin limit" not in decision.reason  # gate-level phrasing lives in enqueue.py
    assert "above the 20% limit" in decision.reason


def test_ignores_scrapes_outside_the_window(conn, monkeypatch):
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "5.00")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=1.0, cost_price=None)
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    cost_id = record_scrape_cost(conn, tenant_id, mapping_id, "market_source")
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE scraping_cost_ledger SET observed_at = %s WHERE cost_id = %s;",
            (datetime.now(timezone.utc) - timedelta(days=45), cost_id),
        )
    conn.commit()

    decision = evaluate_cost_margin_gate(conn, tenant_id, product_id, window_days=30)
    assert decision.allow is True
    assert "no real scraping cost data" in decision.reason


def test_unknown_cost_rows_do_not_count_as_zero_or_as_known(conn):
    """A collector with no configured rate writes NULL-cost rows (see
    record_scrape_cost tests above) - the gate must treat those as no
    information, never as a real $0 spend that would always pass."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=1.0, cost_price=None)
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    record_scrape_cost(conn, tenant_id, mapping_id, "totally_unconfigured_collector")
    conn.commit()

    decision = evaluate_cost_margin_gate(conn, tenant_id, product_id)
    assert decision.allow is True
    assert "no real scraping cost data" in decision.reason
