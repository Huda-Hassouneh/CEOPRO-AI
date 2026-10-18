"""
Integration tests for insights/pipeline.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set. cross_signal.py's own rule
logic is exhaustively covered offline (test_insights_cross_signal.py) -
these tests verify the DATA ASSEMBLY from real tables is correct, which
is the part that can't be tested without a real database.
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.insights import pipeline

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


def _insert_product_review_with_sentiment(conn, tenant_id, product_id, label, pos, neg):
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, product_id, source_platform, review_text) "
            "VALUES (%s, %s, 'PRODUCT', %s, 'GOOGLE', 'Some review text.');",
            (review_id, tenant_id, product_id),
        )
    from src.ai.sentiment.evidence import insert_sentiment_result
    insert_sentiment_result(conn, review_id, tenant_id, label, pos, 0.1, neg, 0.9, "test-model-v1")


def _insert_business_review_with_sentiment(conn, tenant_id, label, pos, neg):
    review_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO reviews (review_id, tenant_id, subject_type, source_platform, review_text) "
            "VALUES (%s, %s, 'BUSINESS', 'GOOGLE', 'Great service overall.');",
            (review_id, tenant_id),
        )
    from src.ai.sentiment.evidence import insert_sentiment_result
    insert_sentiment_result(conn, review_id, tenant_id, label, pos, 0.1, neg, 0.9, "test-model-v1")


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


def _insert_forecast(conn, tenant_id, product_id, expected_demand, target_date, created_at, confidence_score=None):
    forecast_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO demand_forecasts (forecast_id, tenant_id, product_id, expected_demand, "
            "forecast_target_date, model_version, created_at) VALUES (%s, %s, %s, %s, %s, 'test-model', %s);",
            (forecast_id, tenant_id, product_id, expected_demand, target_date, created_at),
        )
        if confidence_score is not None:
            cursor.execute(
                "INSERT INTO evidence_records (tenant_id, forecast_id, category, source_module, "
                "explanation_text, confidence_score) VALUES (%s, %s, 'PREDICTION', 'ai.forecasting', 'test', %s);",
                (tenant_id, forecast_id, confidence_score),
            )
    return forecast_id


def test_load_price_gaps_reflects_real_competitor_prices(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=60.0)
    conn.commit()
    _insert_competitor_price(conn, tenant_id, product_id, scraped_price=50.0)
    conn.commit()

    gaps = pipeline._load_price_gaps(conn, tenant_id)

    assert gaps[product_id] == pytest.approx(20.0)  # 60 vs 50 -> 20% above market


def test_load_product_sentiment_uses_product_level_then_falls_back_to_business(conn):
    tenant_id = _insert_company(conn)
    product_with_reviews = _insert_product(conn, tenant_id, "Reviewed Widget")
    product_without_reviews = _insert_product(conn, tenant_id, "Unreviewed Widget")
    conn.commit()

    _insert_product_review_with_sentiment(conn, tenant_id, product_with_reviews, "NEGATIVE", pos=0.1, neg=0.7)
    _insert_business_review_with_sentiment(conn, tenant_id, "POSITIVE", pos=0.8, neg=0.1)
    conn.commit()

    product_scores, business_score = pipeline._load_product_sentiment(conn, tenant_id)

    assert product_scores[product_with_reviews] == pytest.approx(0.1 - 0.7)
    assert product_without_reviews not in product_scores  # no product-level reviews of its own
    assert business_score == pytest.approx(0.8 - 0.1)


def test_load_sales_trends_computes_recent_vs_prior_correctly(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()

    now = datetime.now(timezone.utc)
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=5, unit_price=10.0, issue_date=now - timedelta(days=5))
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=45))
    conn.commit()

    trends = pipeline._load_sales_trends(conn, tenant_id)

    assert trends[product_id]["recent_units"] == 5.0
    assert trends[product_id]["trend_pct"] == pytest.approx((5.0 - 10.0) / 10.0 * 100)


def test_load_sales_trends_returns_none_trend_when_no_prior_window_data(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Brand New Widget")
    conn.commit()
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=5, unit_price=10.0, issue_date=datetime.now(timezone.utc))
    conn.commit()

    trends = pipeline._load_sales_trends(conn, tenant_id)

    assert trends[product_id]["trend_pct"] is None  # nothing to compare against yet


def test_load_latest_forecasts_returns_only_the_most_recent_per_product(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_forecast(conn, tenant_id, product_id, expected_demand=10, target_date=date.today() + timedelta(days=7), created_at=now - timedelta(days=10))
    _insert_forecast(conn, tenant_id, product_id, expected_demand=42, target_date=date.today() + timedelta(days=7), created_at=now)
    conn.commit()

    forecasts = pipeline._load_latest_forecasts(conn, tenant_id)

    assert forecasts[product_id]["expected_demand"] == 42.0  # the newer of the two rows


def test_load_product_signals_assembles_a_full_cross_signal_picture(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget", current_price=60.0)
    conn.commit()

    _insert_competitor_price(conn, tenant_id, product_id, scraped_price=50.0)
    _insert_product_review_with_sentiment(conn, tenant_id, product_id, "NEGATIVE", pos=0.1, neg=0.6)
    now = datetime.now(timezone.utc)
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=3, unit_price=10.0, issue_date=now - timedelta(days=5))
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=10, unit_price=10.0, issue_date=now - timedelta(days=45))
    conn.commit()

    all_signals = pipeline.load_product_signals(conn, tenant_id)

    assert len(all_signals) == 1
    signals = all_signals[0]
    assert signals.product_name == "Widget"
    assert signals.price_gap_pct == pytest.approx(20.0)
    assert signals.sentiment_score == pytest.approx(0.1 - 0.6)
    assert signals.sales_trend_pct == pytest.approx((3.0 - 10.0) / 10.0 * 100)


def test_generate_insights_for_tenant_surfaces_a_real_cross_signal_pattern(conn):
    """End-to-end: an overpriced product with falling sales must produce
    a real, plain-language insight naming that product."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine", current_price=100.0)
    conn.commit()

    _insert_competitor_price(conn, tenant_id, product_id, scraped_price=70.0)  # 43% above market
    now = datetime.now(timezone.utc)
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=2, unit_price=100.0, issue_date=now - timedelta(days=5))
    _insert_invoice_with_item(conn, tenant_id, product_id, quantity=20, unit_price=100.0, issue_date=now - timedelta(days=45))
    conn.commit()

    insights = pipeline.generate_insights_for_tenant(conn, tenant_id)

    assert len(insights) == 1
    assert "Espresso Machine" in insights[0].message
    assert insights[0].category == "pricing"


def test_generate_insights_for_tenant_returns_empty_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    assert pipeline.generate_insights_for_tenant(conn, tenant_id) == []


def _create_competitor_mapping(conn, tenant_id, product_id, competitor_name="Rival Co") -> str:
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


def _insert_price_observation(conn, tenant_id, mapping_id, price, observed_at):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, observed_at) "
            "VALUES (%s, %s, %s, 'JOD', %s);",
            (tenant_id, mapping_id, price, observed_at),
        )


def _insert_daily_sales(conn, tenant_id, product_id, start_date, days, units_per_day):
    with conn.cursor() as cursor:
        for i in range(days):
            issue_date = start_date + timedelta(days=i)
            invoice_id = str(uuid.uuid4())
            total = units_per_day * 10.0
            cursor.execute(
                "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'JOD');",
                (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", issue_date, total, total),
            )
            cursor.execute(
                "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
                "VALUES (%s, %s, %s, %s, 10.0, %s);",
                (tenant_id, invoice_id, product_id, units_per_day, total),
            )


def test_load_competitor_price_histories_returns_full_ordered_history(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()
    mapping_id = _create_competitor_mapping(conn, tenant_id, product_id, "Rival Co")
    now = datetime.now(timezone.utc)
    _insert_price_observation(conn, tenant_id, mapping_id, 100.0, now - timedelta(days=30))
    _insert_price_observation(conn, tenant_id, mapping_id, 80.0, now - timedelta(days=15))
    conn.commit()

    histories = pipeline._load_competitor_price_histories(conn, tenant_id)

    key = (product_id, "Rival Co")
    assert key in histories
    assert [price for _date, price in histories[key]] == [100.0, 80.0]


def test_load_daily_sales_series_groups_units_by_day(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()
    now = datetime.now(timezone.utc)
    _insert_daily_sales(conn, tenant_id, product_id, now - timedelta(days=10), days=3, units_per_day=5.0)
    conn.commit()

    series = pipeline._load_daily_sales_series(conn, tenant_id)

    assert product_id in series
    assert len(series[product_id]) == 3
    assert all(units == 5.0 for units in series[product_id].values())


def test_generate_causal_insights_for_tenant_detects_a_real_event_timing_pattern(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine")
    conn.commit()
    mapping_id = _create_competitor_mapping(conn, tenant_id, product_id, "Rival Roasters")
    now = datetime.now(timezone.utc)
    event_date = now - timedelta(days=20)

    _insert_price_observation(conn, tenant_id, mapping_id, 100.0, now - timedelta(days=40))
    _insert_price_observation(conn, tenant_id, mapping_id, 70.0, event_date)  # -30% price drop event
    _insert_daily_sales(conn, tenant_id, product_id, event_date - timedelta(days=14), days=14, units_per_day=10.0)
    _insert_daily_sales(conn, tenant_id, product_id, event_date, days=14, units_per_day=4.0)  # -60% after
    conn.commit()

    insights = pipeline.generate_causal_insights_for_tenant(conn, tenant_id)

    assert len(insights) == 1
    assert insights[0].category == "causal_timing"
    assert "Espresso Machine" in insights[0].message
    assert "Rival Roasters" in insights[0].message


def test_generate_insights_for_tenant_merges_causal_and_snapshot_insights(conn):
    """End-to-end: generate_insights_for_tenant() must surface a causal-
    timing finding even when no cross_signal snapshot rule fires for that
    same product (no current price gap or sentiment data at all here -
    only the historical price-drop-then-sales-decline pattern)."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine")
    conn.commit()
    mapping_id = _create_competitor_mapping(conn, tenant_id, product_id, "Rival Roasters")
    now = datetime.now(timezone.utc)
    event_date = now - timedelta(days=20)

    _insert_price_observation(conn, tenant_id, mapping_id, 100.0, now - timedelta(days=40))
    _insert_price_observation(conn, tenant_id, mapping_id, 70.0, event_date)
    _insert_daily_sales(conn, tenant_id, product_id, event_date - timedelta(days=14), days=14, units_per_day=10.0)
    _insert_daily_sales(conn, tenant_id, product_id, event_date, days=14, units_per_day=4.0)
    conn.commit()

    insights = pipeline.generate_insights_for_tenant(conn, tenant_id)

    assert any(insight.category == "causal_timing" for insight in insights)
