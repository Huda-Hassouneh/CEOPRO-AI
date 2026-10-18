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
    assert result["market_sentiment"] is None  # no analyzed reviews yet, never a fabricated score


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
    # history starts before the prior window (outside both windows), so the
    # comparison is over a fully covered prior period
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=10.0, issue_date=now - timedelta(days=61))
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
    _insert_invoice(conn, tenant_id, product_id, quantity=1, unit_price=5.0, issue_date=now - timedelta(days=61))  # covers the prior window
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


def _insert_business_review_with_sentiment(conn, tenant_id, positive_probability, negative_probability, review_date):
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, source_platform, review_text, review_date) "
            "VALUES (%s, %s, 'BUSINESS', 'GOOGLE', 'Great service.', %s);",
            (review_id, tenant_id, review_date),
        )
    from src.ai.sentiment.evidence import insert_sentiment_result
    neutral_probability = 1.0 - positive_probability - negative_probability
    insert_sentiment_result(
        conn, review_id, tenant_id, "POSITIVE", positive_probability, neutral_probability,
        negative_probability, 0.9, "test-model-v1",
    )


def test_market_sentiment_reflects_real_analyzed_reviews_in_the_recent_window(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_business_review_with_sentiment(conn, tenant_id, 0.8, 0.1, review_date=now)
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id)

    assert result["market_sentiment"]["score"] == pytest.approx(85.0)  # (0.8-0.1+1)/2*100
    assert result["market_sentiment"]["change_pts"] is None  # nothing in the prior window to compare against


def test_market_sentiment_change_pts_compares_recent_window_against_prior_window(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_business_review_with_sentiment(conn, tenant_id, 0.5, 0.5, review_date=now - timedelta(days=45))  # score=50
    _insert_business_review_with_sentiment(conn, tenant_id, 0.9, 0.1, review_date=now)  # score=90
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id, window_days=30)

    assert result["market_sentiment"]["score"] == pytest.approx(90.0)
    assert result["market_sentiment"]["change_pts"] == pytest.approx(40.0)


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


# --- First-customer acceptance findings ---------------------------------------

def test_change_pct_is_none_when_history_does_not_cover_the_prior_window(conn):
    """History that starts partway through the prior window used to produce a
    real-looking but meaningless change (live: 'Growth +205.2%' on 90 days)."""
    now = datetime.now(timezone.utc)
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    _insert_invoice(conn, tenant_id, product_id, 1, 10.0, now - timedelta(days=40))  # prior window 30-60d, partly covered
    _insert_invoice(conn, tenant_id, product_id, 5, 10.0, now - timedelta(days=5))

    result = get_dashboard_metrics(conn, tenant_id, window_days=30)

    assert result["revenue"]["amount"] == 50.0
    assert result["history_covers_prior_window"] is False
    assert result["revenue"]["change_pct"] is None
    assert result["units_sold"]["change_pct"] is None
    assert result["transaction_growth_pct"] is None


def test_sales_trend_points_sum_to_the_metric_cards(conn):
    from src.ai.dashboard.metrics import get_sales_trend

    now = datetime.now(timezone.utc)
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    for days_ago, quantity in [(1, 2), (1, 3), (6, 4), (29, 1), (45, 9)]:
        _insert_invoice(conn, tenant_id, product_id, quantity, 2.5, now - timedelta(days=days_ago))

    metrics = get_dashboard_metrics(conn, tenant_id, window_days=30)
    trend = get_sales_trend(conn, tenant_id, window_days=30)

    assert trend["has_data"] is True and trend["currency"] == "JOD"
    assert len(trend["points"]) in (30, 31)
    assert round(sum(p["value"] for p in trend["points"]), 2) == metrics["revenue"]["amount"] == 25.0
    assert sum(p["units"] for p in trend["points"]) == metrics["units_sold"]["units"] == 10
    dates = [p["date"] for p in trend["points"]]
    assert dates == sorted(dates) and dates[-1] == now.date().isoformat()
    assert any(p["value"] == 0 for p in trend["points"])  # days without sales are explicit zeros


def test_sales_trend_is_empty_for_a_brand_new_tenant(conn):
    from src.ai.dashboard.metrics import get_sales_trend

    trend = get_sales_trend(conn, _insert_company(conn), window_days=7)
    assert trend["has_data"] is False
    assert all(p["value"] == 0 and p["units"] == 0 for p in trend["points"])


def test_market_sentiment_includes_reviews_of_the_businesss_own_products_but_not_competitors(conn):
    """Product reviews were excluded, so a business whose customer feedback is
    per-product (most imported review files) showed no sentiment at all."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id)
    competitor_id = _insert_tracked_competitor(conn, tenant_id)
    conn.commit()
    now = datetime.now(timezone.utc)
    from src.ai.sentiment.evidence import insert_sentiment_result
    for subject, column, value, positive, negative in (
        ("PRODUCT", "product_id", product_id, 0.6, 0.2),
        ("COMPETITOR", "competitor_id", competitor_id, 0.0, 1.0),  # must not count
    ):
        review_id = str(uuid.uuid4())
        with conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO reviews (review_id, tenant_id, subject_type, {column}, source_platform, review_text, review_date) "
                "VALUES (%s, %s, %s, %s, 'GOOGLE', 'text', %s);",
                (review_id, tenant_id, subject, value, now),
            )
        insert_sentiment_result(conn, review_id, tenant_id, "POSITIVE", positive, 1 - positive - negative, negative, 0.9, "test-model-v1")
    conn.commit()

    result = get_dashboard_metrics(conn, tenant_id)

    assert result["market_sentiment"]["score"] == pytest.approx(70.0)  # (0.6-0.2+1)/2*100, competitor ignored
