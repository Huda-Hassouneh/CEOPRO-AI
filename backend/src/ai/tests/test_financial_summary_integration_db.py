"""
Integration tests for dashboard/financial_summary.py against a real
PostgreSQL instance. Same convention as every other live-DB test in this
package (see test_dashboard_metrics_integration_db.py): skipped unless
AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.financial_summary import (
    analyze_margin_change,
    analyze_revenue_change,
    get_product_profitability,
    get_profitability_summary,
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


def _insert_company(conn, currency="JOD") -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', %s);",
            (tenant_id, f"Test Co {tenant_id[:8]}", currency),
        )
    return tenant_id


def _insert_product(conn, tenant_id, name="Widget", cost_price=None) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, cost_price, currency) "
            "VALUES (%s, %s, %s, 10.0, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), cost_price),
        )
    return product_id


def _insert_invoice(conn, tenant_id, product_id, quantity, unit_price, issue_date, currency="JOD"):
    invoice_id = str(uuid.uuid4())
    total = quantity * unit_price
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s);",
            (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", issue_date, total, total, currency),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
            "VALUES (%s, %s, %s, %s, %s, %s);",
            (tenant_id, invoice_id, product_id, quantity, unit_price, total),
        )
    return invoice_id


# --- get_profitability_summary ---------------------------------------------

def test_summary_returns_honest_zeros_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = get_profitability_summary(conn, tenant_id)

    assert result["revenue"]["amount"] == 0.0
    assert result["revenue"]["change_pct"] is None
    assert result["gross_profit"]["amount"] is None  # never fabricated as 0
    assert result["cost_data_coverage_pct"] is None


def test_summary_computes_gross_profit_and_margin_from_known_cost_price(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, cost_price=6.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))
    conn.commit()

    result = get_profitability_summary(conn, tenant_id)

    assert result["revenue"]["amount"] == 100.0
    assert result["gross_profit"]["amount"] == 40.0  # (10-6)*10
    assert result["gross_margin_pct"]["recent"] == 40.0
    assert result["cost_data_coverage_pct"] == 100.0


def test_summary_excludes_revenue_from_products_with_no_cost_price(conn):
    """The single most important honesty behavior in this module: a
    product with no cost_price must never be silently treated as zero
    cost (which would inflate the margin) - it must be excluded from the
    margin calculation and flagged via cost_data_coverage_pct."""
    tenant_id = _insert_company(conn)
    priced_product = _insert_product(conn, tenant_id, name="Has cost", cost_price=6.0)
    unpriced_product = _insert_product(conn, tenant_id, name="No cost", cost_price=None)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, priced_product, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))
    _insert_invoice(conn, tenant_id, unpriced_product, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))
    conn.commit()

    result = get_profitability_summary(conn, tenant_id)

    assert result["revenue"]["amount"] == 200.0  # both sales count toward revenue
    assert result["gross_profit"]["amount"] == 40.0  # only the priced product's profit
    assert result["cost_data_coverage_pct"] == 50.0  # only half of revenue has cost data


def test_summary_change_pct_compares_recent_window_against_prior_window(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, cost_price=5.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))  # recent: profit=50
    _insert_invoice(conn, tenant_id, product_id, quantity=5, unit_price=10.0, issue_date=now - timedelta(days=40))  # prior: profit=25
    conn.commit()

    result = get_profitability_summary(conn, tenant_id, window_days=30)

    assert result["gross_profit"]["change_pct"] == 100.0  # doubled


# --- get_product_profitability ----------------------------------------------

def test_product_profitability_ranks_most_and_least_profitable(conn):
    tenant_id = _insert_company(conn)
    winner = _insert_product(conn, tenant_id, name="Star Product", cost_price=2.0)
    loser = _insert_product(conn, tenant_id, name="Loss Leader", cost_price=15.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, winner, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))  # profit = 80
    _insert_invoice(conn, tenant_id, loser, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))  # profit = -50
    conn.commit()

    result = get_product_profitability(conn, tenant_id)

    assert result["most_profitable"][0]["product_name"] == "Star Product"
    assert result["most_profitable"][0]["gross_profit"] == 80.0
    assert result["least_profitable"][0]["product_name"] == "Loss Leader"
    assert result["least_profitable"][0]["gross_profit"] == -50.0


def test_product_profitability_lists_products_with_no_cost_data_separately(conn):
    tenant_id = _insert_company(conn)
    unpriced = _insert_product(conn, tenant_id, name="Mystery Cost", cost_price=None)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, unpriced, quantity=3, unit_price=10.0, issue_date=now - timedelta(days=5))
    conn.commit()

    result = get_product_profitability(conn, tenant_id)

    assert result["most_profitable"] == []
    assert result["least_profitable"] == []
    assert len(result["no_cost_data"]) == 1
    assert result["no_cost_data"][0]["product_name"] == "Mystery Cost"
    assert result["no_cost_data"][0]["revenue"] == 30.0
    assert "gross_profit" not in result["no_cost_data"][0]


# --- analyze_revenue_change (B5/B6 root-cause) -------------------------------

def test_analyze_revenue_change_returns_no_data_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = analyze_revenue_change(conn, tenant_id)

    assert result["has_data"] is False


def test_analyze_revenue_change_decomposes_pure_volume_effect(conn):
    """Same price both windows, more units recently - the whole revenue
    change should attribute to units_effect, price_effect should be ~0."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, cost_price=5.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))  # recent: 100
    _insert_invoice(conn, tenant_id, product_id, quantity=5, unit_price=10.0, issue_date=now - timedelta(days=40))  # prior: 50
    conn.commit()

    result = analyze_revenue_change(conn, tenant_id, window_days=30)

    assert result["has_data"] is True
    assert result["revenue_change"] == 50.0
    assert result["units_sold_change"] == 5
    assert result["drivers"]["units_effect"] == 50.0  # (10-5) * prior_ASP(10)
    assert result["drivers"]["price_effect"] == 0.0


def test_analyze_revenue_change_decomposes_pure_price_effect(conn):
    """Same units both windows, higher price recently - the whole revenue
    change should attribute to price_effect, units_effect should be ~0."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, cost_price=5.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=10, unit_price=15.0, issue_date=now - timedelta(days=5))  # recent: 150
    _insert_invoice(conn, tenant_id, product_id, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=40))  # prior: 100
    conn.commit()

    result = analyze_revenue_change(conn, tenant_id, window_days=30)

    assert result["revenue_change"] == 50.0
    assert result["units_sold_change"] == 0
    assert result["drivers"]["units_effect"] == 0.0
    assert result["drivers"]["price_effect"] == 50.0  # 10 units * (15-10)


def test_analyze_revenue_change_top_movers_ranks_by_absolute_change(conn):
    tenant_id = _insert_company(conn)
    grew = _insert_product(conn, tenant_id, name="Grew A Lot", cost_price=5.0)
    shrank = _insert_product(conn, tenant_id, name="Shrank A Little", cost_price=5.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, grew, quantity=20, unit_price=10.0, issue_date=now - timedelta(days=5))  # recent: 200
    _insert_invoice(conn, tenant_id, grew, quantity=1, unit_price=10.0, issue_date=now - timedelta(days=40))  # prior: 10, delta=190
    _insert_invoice(conn, tenant_id, shrank, quantity=1, unit_price=10.0, issue_date=now - timedelta(days=5))  # recent: 10
    _insert_invoice(conn, tenant_id, shrank, quantity=2, unit_price=10.0, issue_date=now - timedelta(days=40))  # prior: 20, delta=-10
    conn.commit()

    result = analyze_revenue_change(conn, tenant_id, window_days=30)

    assert result["top_movers"][0]["product_name"] == "Grew A Lot"
    assert result["top_movers"][0]["revenue_change"] == 190.0
    assert "correlation/signal, not proof of causation" in result["movers_caveat"]


# --- analyze_margin_change (B5/B6 root-cause) --------------------------------

def test_analyze_margin_change_returns_no_data_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = analyze_margin_change(conn, tenant_id)

    assert result["has_data"] is False


def test_analyze_margin_change_splits_revenue_and_cogs_effects(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, cost_price=6.0)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=5))  # recent: rev=100, cogs=60
    _insert_invoice(conn, tenant_id, product_id, quantity=5, unit_price=10.0, issue_date=now - timedelta(days=40))  # prior: rev=50, cogs=30
    conn.commit()

    result = analyze_margin_change(conn, tenant_id, window_days=30)

    assert result["has_data"] is True
    # revenue_effect = 100-50 = 50; cogs_effect = -(60-30) = -30
    assert result["drivers"]["revenue_effect"] == 50.0
    assert result["drivers"]["cogs_effect"] == -30.0
    # exact: revenue_effect + cogs_effect == delta gross profit (40 -> 25, +15)
    assert round(result["drivers"]["revenue_effect"] + result["drivers"]["cogs_effect"], 2) == 20.0
    assert result["excludes"] == ["fixed_operating_expenses", "marketing_spend", "discounts_and_returns", "taxes"]
