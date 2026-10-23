"""
Integration tests for the new POST /dashboard/products/{id}/forecast
trigger (routers/dashboard.py::dashboard_generate_product_forecast_endpoint)
against a real PostgreSQL instance. Same convention as every other live-DB
test in this package: skipped unless AI_TEST_DATABASE_URL is set.

Regression coverage for the real Demand Prediction bug: a product could
never get its first forecast in any environment, because the only caller
of forecasting/pipeline.py::run_forecast() was a Redis-stream consumer
that nothing ever starts or publishes to. This endpoint is a thin router
wrapper (get_product() existence check, then run_forecast() unmodified) -
these tests exercise exactly that wiring, the same two calls the endpoint
itself makes, directly against a real product row.
"""
from src.ai.tests.sales_fixtures import insert_sale
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.forecasting.pipeline import run_forecast
from src.ai.forecasting.generation import generate_or_reuse_forecast
from src.ai.routers.products import get_product
from src.ai.routers.dashboard import _generate_or_reuse_forecast

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


def _insert_product(conn, tenant_id, name, current_price=10.0) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), current_price),
        )
    return product_id


def test_get_product_returns_none_for_a_nonexistent_product_the_endpoint_404s_on(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert get_product(conn, tenant_id, str(uuid.uuid4())) is None


def test_generate_forecast_for_a_real_product_with_no_sales_history_is_honest_not_fabricated(conn):
    """A product that exists (visible in Products/Demand Prediction) but
    has no invoice history yet - exactly the newly-created-product case
    the reported bug was about. run_forecast() must return a real
    UNKNOWN status with a plain explanation, never a fabricated number."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Anker Power Bank 20,000mAh")
    conn.commit()

    assert get_product(conn, tenant_id, product_id) is not None

    result = run_forecast(conn, tenant_id, product_id)
    assert result["status"] == "UNKNOWN"
    assert "evidence_id" in result

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT explanation_text FROM evidence_records WHERE evidence_id = %s;",
            (result["evidence_id"],),
        )
        (explanation,) = cursor.fetchone()
    assert "no historical transaction data" in explanation.lower()

    # No demand_forecasts row was fabricated for a product with no sales data.
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM demand_forecasts WHERE tenant_id = %s AND product_id = %s;",
            (tenant_id, product_id),
        )
        (forecast_count,) = cursor.fetchone()
    assert forecast_count == 0


def test_generate_forecast_for_a_product_with_real_sales_history_writes_a_real_forecast(conn):
    """A product with enough real historical demand produces a real,
    persisted forecast - proving the trigger actually reaches the real
    pipeline end to end, not just the UNKNOWN short-circuit.

    forecasting/data_access.py::load_daily_demand() reads from
    `transactions` - the table the bulk historical-data upload/extraction
    pipeline (extraction/promotion.py) populates - not from
    invoices/invoice_items (Quick Sale's own write path). Real, but a
    real gap worth knowing: a tenant who has only ever used Quick Sale,
    with no historical transactions file imported, will always see
    UNKNOWN here, however much Quick Sale history accumulates. Populating
    `transactions` directly here matches forecasting's actual real input,
    not Quick Sale's.
    """
    from datetime import datetime, timedelta, timezone

    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget")
    conn.commit()

    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        for day_offset in range(30):
            insert_sale(cursor, tenant_id, product_id, 5, 2.0, now - timedelta(days=30 - day_offset))
    conn.commit()

    result = run_forecast(conn, tenant_id, product_id)
    assert result["status"] == "OK"
    assert result["expected_demand"] is not None
    assert "forecast_id" in result

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM demand_forecasts WHERE tenant_id = %s AND product_id = %s;",
            (tenant_id, product_id),
        )
        (forecast_count,) = cursor.fetchone()
    assert forecast_count == 1


def test_repeated_generation_reuses_current_forecast_without_duplicate_history(conn):
    from datetime import datetime, timedelta, timezone

    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Idempotent demand")
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        for day in range(35):
            insert_sale(cursor, tenant_id, product_id, 3, 2.0, now - timedelta(days=day + 1))
    conn.commit()

    first = _generate_or_reuse_forecast(conn, tenant_id, product_id)
    second = _generate_or_reuse_forecast(conn, tenant_id, product_id)

    assert first["status"] == second["status"] == "OK"
    assert first["forecast_id"] == second["forecast_id"]
    assert second["reused"] is True
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM demand_forecasts WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        assert cursor.fetchone()[0] == 1


def test_repeated_no_history_generation_reuses_unknown_evidence(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "No demand history")
    conn.commit()

    first = _generate_or_reuse_forecast(conn, tenant_id, product_id)
    second = _generate_or_reuse_forecast(conn, tenant_id, product_id)

    assert first["status"] == second["status"] == "UNKNOWN"
    assert first["evidence_id"] == second["evidence_id"]
    assert second["reused"] is True
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM evidence_records WHERE tenant_id = %s AND category = 'UNKNOWN' "
            "AND source_record_ids->>'product_id' = %s;",
            (tenant_id, product_id),
        )
        assert cursor.fetchone()[0] == 1


def test_auto_refresh_and_explicit_generation_share_concurrency_idempotency(conn):
    """The demand-page background refresh and manual API trigger must share one product lock."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Concurrent demand")
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        for day in range(35):
            insert_sale(cursor, tenant_id, product_id, 3, 2.0, now - timedelta(days=day + 1))
    conn.commit()

    def generate():
        worker_conn = psycopg2.connect(DATABASE_URL)
        try:
            return generate_or_reuse_forecast(worker_conn, tenant_id, product_id)
        finally:
            worker_conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _idx: generate(), range(2)))

    assert {result["status"] for result in results} == {"OK"}
    assert len({result["forecast_id"] for result in results}) == 1
    assert sorted(result["reused"] for result in results) == [False, True]
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM demand_forecasts WHERE tenant_id=%s AND product_id=%s", (tenant_id, product_id))
        assert cursor.fetchone()[0] == 1
