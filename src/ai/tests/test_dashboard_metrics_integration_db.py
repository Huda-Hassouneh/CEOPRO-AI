"""
Integration tests for dashboard/metrics.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.metrics import get_dashboard_metrics

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


def _insert_product(conn, tenant_id, name="Widget") -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
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


def _insert_tracked_competitor(conn, tenant_id, added_at=None, name=None):
    competitor_id = str(uuid.uuid4())
    name = name or f"Rival Co {competitor_id[:8]}"
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, tenant_id),
        )
        if added_at is not None:
            cursor.execute(
                "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, added_at) "
                "VALUES (%s, %s, TRUE, %s);",
                (tenant_id, competitor_id, added_at),
            )
        else:
            cursor.execute(
                "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);",
                (tenant_id, competitor_id),
            )
    return competitor_id


def test_returns_honest_zeros_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id)

    assert result["revenue"]["amount"] == 0.0
    assert result["revenue"]["change_pct"] is None  # nothing to compare against, never a fabricated 0%
    assert result["units_sold"]["units"] == 0
    assert result["transaction_growth_pct"] is None
    assert result["competitors_tracked"] == {"count": 0, "new_this_window": 0}


def test_revenue_and_units_reflect_real_invoices_in_the_recent_window(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=3, unit_price=10.0, issue_date=now - timedelta(days=5))
    _insert_invoice(conn, tenant_id, product_id, quantity=2, unit_price=10.0, issue_date=now - timedelta(days=10))
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id)

    assert result["revenue"]["amount"] == 50.0
    assert result["revenue"]["currency"] == "JOD"
    assert result["units_sold"]["units"] == 5


def test_change_pct_compares_recent_window_against_prior_window(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    # recent window (last 30 days): 2 invoices, 20.0 revenue
    _insert_invoice(conn, tenant_id, product_id, quantity=2, unit_price=10.0, issue_date=now - timedelta(days=5))
    # prior window (30-60 days ago): 1 invoice, 10.0 revenue
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=10.0, issue_date=now - timedelta(days=40))
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id, window_days=30)

    assert result["revenue"]["amount"] == 20.0
    assert result["revenue"]["change_pct"] == 100.0  # doubled vs. the prior window
    assert result["transaction_growth_pct"] == 0.0  # 1 invoice recent, 1 invoice prior - flat


def test_transaction_growth_reflects_invoice_count_not_amount(conn):
    """A distinct signal from revenue/units - two small invoices vs. one
    big one should move transaction_growth_pct even when revenue is flat."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=5.0, issue_date=now - timedelta(days=2))
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=5.0, issue_date=now - timedelta(days=6))
    _insert_invoice(conn, tenant_id, product_id, quantity=2, unit_price=5.0, issue_date=now - timedelta(days=40))
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id, window_days=30)

    assert result["transaction_growth_pct"] == 100.0  # 2 recent invoices vs. 1 prior


def test_competitors_tracked_counts_only_is_tracked_true(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    _insert_tracked_competitor(conn, tenant_id)
    _insert_tracked_competitor(conn, tenant_id)
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id)

    assert result["competitors_tracked"]["count"] == 2


def test_competitors_tracked_new_this_window_uses_added_at(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_tracked_competitor(conn, tenant_id, added_at=now - timedelta(days=5))
    _insert_tracked_competitor(conn, tenant_id, added_at=now - timedelta(days=60))
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id, window_days=30)

    assert result["competitors_tracked"]["count"] == 2
    assert result["competitors_tracked"]["new_this_window"] == 1


def test_window_days_is_configurable(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=10.0, issue_date=now - timedelta(days=10))
    conn.commit()

    result_7d = get_dashboard_metrics(conn, tenant_id, window_days=7)
    result_30d = get_dashboard_metrics(conn, tenant_id, window_days=30)

    assert result_7d["revenue"]["amount"] == 0.0  # outside a 7-day window
    assert result_30d["revenue"]["amount"] == 10.0  # inside a 30-day window
