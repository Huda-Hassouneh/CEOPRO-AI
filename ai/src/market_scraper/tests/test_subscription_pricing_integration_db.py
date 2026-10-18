"""
Integration tests for subscription_pricing.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.market_scraper.cost_ledger import record_scrape_cost
from src.market_scraper.subscription_pricing import (
    calculate_subscription_floor_price,
    calculate_tenant_subscription_floor_price,
    sum_real_variable_cost,
)

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
# calculate_subscription_floor_price() - pure formula
# ---------------------------------------------------------------------------

def test_applies_the_documented_formula():
    # (100 + 50) / (1 - 0.20) = 187.50
    assert calculate_subscription_floor_price(100.0, 50.0, 0.20) == 187.50


def test_zero_variable_cost_and_zero_allocation_gives_zero_floor():
    assert calculate_subscription_floor_price(0.0, 0.0, 0.20) == 0.0


def test_rejects_a_risk_margin_ratio_of_one_or_more():
    with pytest.raises(ValueError):
        calculate_subscription_floor_price(100.0, 50.0, 1.0)


def test_rejects_a_negative_risk_margin_ratio():
    with pytest.raises(ValueError):
        calculate_subscription_floor_price(100.0, 50.0, -0.1)


# ---------------------------------------------------------------------------
# sum_real_variable_cost()
# ---------------------------------------------------------------------------

def test_sums_real_known_costs_for_one_tenant(conn, monkeypatch):
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.02")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()

    record_scrape_cost(conn, tenant_id, mapping_id, "market_source")
    record_scrape_cost(conn, tenant_id, mapping_id, "market_source")
    conn.commit()

    assert sum_real_variable_cost(conn, tenant_id) == pytest.approx(0.04)


def test_returns_a_real_zero_with_no_recorded_cost(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert sum_real_variable_cost(conn, tenant_id) == 0.0


def test_ignores_another_tenants_cost(conn, monkeypatch):
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.05")
    tenant_a = _insert_company(conn)
    tenant_b = _insert_company(conn)
    product_id = _insert_product(conn, tenant_a, "Widget")
    mapping_id = _insert_mapping(conn, tenant_a, product_id)
    conn.commit()

    record_scrape_cost(conn, tenant_a, mapping_id, "market_source")
    conn.commit()

    assert sum_real_variable_cost(conn, tenant_a) == pytest.approx(0.05)
    assert sum_real_variable_cost(conn, tenant_b) == 0.0


def test_excludes_unknown_cost_rows_from_the_sum(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()

    record_scrape_cost(conn, tenant_id, mapping_id, "unconfigured_vendor")
    conn.commit()

    assert sum_real_variable_cost(conn, tenant_id) == 0.0


# ---------------------------------------------------------------------------
# calculate_tenant_subscription_floor_price()
# ---------------------------------------------------------------------------

def test_reports_not_computed_when_server_allocation_is_unconfigured(conn, monkeypatch):
    monkeypatch.delenv("SERVER_ALLOCATION_USD", raising=False)
    tenant_id = _insert_company(conn)
    conn.commit()

    result = calculate_tenant_subscription_floor_price(conn, tenant_id)

    assert result.computed is False
    assert result.floor_price is None
    assert "SERVER_ALLOCATION_USD" in result.reason


def test_computes_a_real_floor_price_from_env_configured_allocation(conn, monkeypatch):
    monkeypatch.setenv("SERVER_ALLOCATION_USD", "50")
    monkeypatch.setenv("SCRAPE_COST_PER_REQUEST_MARKET_SOURCE", "0.02")
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    mapping_id = _insert_mapping(conn, tenant_id, product_id)
    conn.commit()
    record_scrape_cost(conn, tenant_id, mapping_id, "market_source")
    conn.commit()

    result = calculate_tenant_subscription_floor_price(conn, tenant_id, risk_margin_ratio=0.20)

    assert result.computed is True
    assert result.variable_cost == pytest.approx(0.02)
    assert result.server_allocation == 50.0
    # (0.02 + 50) / (1 - 0.20) = 62.525 -> 62.52 (round-half-to-even on the
    # nearest representable float, same as calculate_subscription_floor_price()'s own round())
    assert result.floor_price == pytest.approx(62.52)


def test_explicit_server_allocation_argument_overrides_the_environment(conn, monkeypatch):
    monkeypatch.setenv("SERVER_ALLOCATION_USD", "999")
    tenant_id = _insert_company(conn)
    conn.commit()

    result = calculate_tenant_subscription_floor_price(conn, tenant_id, server_allocation_usd=10.0, risk_margin_ratio=0.20)

    assert result.computed is True
    assert result.server_allocation == 10.0
    # (0 + 10) / (1 - 0.20) = 12.50
    assert result.floor_price == pytest.approx(12.50)
