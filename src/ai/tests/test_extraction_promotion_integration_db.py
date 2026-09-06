"""
Integration tests for promotion.py against a real PostgreSQL instance -
same convention as test_extraction_ingestion_pipeline_integration_db.py:
skipped unless AI_TEST_DATABASE_URL is set. Proves the bulk (execute_values)
path and its SAVEPOINT-isolated batch/row fallback actually write correct
rows to products/transactions and correctly flag import_staging_rows -
the offline tests in test_extraction_promotion.py only cover the pure
eligibility-selection logic, not any SQL.
"""
import os
import uuid
from decimal import Decimal

import psycopg2
import pytest

from src.ai.extraction import ingestion_pipeline, promotion

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

_TEMPLATE_HEADERS = ["product_name", "quantity", "unit_price", "currency", "transaction_date"]


def _template_row(**overrides):
    row = {
        "product_name": "Widget A", "quantity": "5", "unit_price": "19.99",
        "currency": "JOD", "transaction_date": "2026-08-30",
    }
    row.update(overrides)
    return row


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def seeded_tenant(conn):
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Promotion QA Co', 'JO', 'JOD');",
            (tenant_id,),
        )
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'x');",
            (user_id, f"{user_id}@example.com"),
        )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');",
            (tenant_id, user_id),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) "
            "VALUES (%s, %s, 'Test Source', 'CSV_UPLOAD');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO ingestion_jobs (job_id, tenant_id, source_id) VALUES (%s, %s, %s);",
            (job_id, tenant_id, source_id),
        )
    conn.commit()
    return tenant_id, user_id, job_id


def _staging_row(conn, staging_row_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT validation_status, committed_table, committed_record_id "
            "FROM import_staging_rows WHERE staging_row_id = %s;",
            (staging_row_id,),
        )
        return cursor.fetchone()


def _product(conn, product_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_name->>'en', current_price, currency, source, created_by_user_id "
            "FROM products WHERE product_id = %s;",
            (product_id,),
        )
        return cursor.fetchone()


def _transaction(conn, transaction_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, quantity_sold, unit_price, total_price, original_currency "
            "FROM transactions WHERE transaction_id = %s;",
            (transaction_id,),
        )
        return cursor.fetchone()


def _run(conn, tenant_id, job_id, user_id, rows):
    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn,
    )
    return summary, promotion.promote_ingested_rows(conn, tenant_id, job_id, summary, user_id=user_id)


def test_complete_row_promotes_to_a_new_product_and_transaction(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    summary, promo = _run(conn, tenant_id, job_id, user_id, [_template_row()])
    conn.commit()

    assert promo.rows_promoted == 1
    assert promo.rows_skipped_incomplete == 0
    assert promo.rows_failed == 0
    assert promo.products_created == 1

    staging_row_id = summary.row_outcomes[0].staging_row_id
    status, committed_table, transaction_id = _staging_row(conn, staging_row_id)
    assert status == "COMMITTED"
    assert committed_table == "transactions"
    assert transaction_id is not None

    product_id, quantity, unit_price, total_price, currency = _transaction(conn, transaction_id)
    assert quantity == 5
    assert unit_price == Decimal("19.99")
    assert total_price == Decimal("99.9500")
    assert currency == "JOD"

    name, price, prod_currency, source, created_by = _product(conn, product_id)
    assert name == "Widget A"
    assert price == Decimal("19.99")
    assert prod_currency == "JOD"
    assert source == "IMPORTED"
    assert str(created_by) == user_id


def test_two_rows_same_product_name_share_one_product(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(quantity="2"), _template_row(quantity="3", product_name="  widget a  ")]
    summary, promo = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert promo.rows_promoted == 2
    assert promo.products_created == 1

    ids = []
    for outcome in summary.row_outcomes:
        _, _, txn_id = _staging_row(conn, outcome.staging_row_id)
        ids.append(txn_id)
    product_ids = {_transaction(conn, tid)[0] for tid in ids}
    assert len(product_ids) == 1


def test_existing_product_price_is_never_overwritten_by_a_later_import(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, source) "
            "VALUES (%s, %s::jsonb, 999.00, 'JOD', 'MANUAL') RETURNING product_id;",
            (tenant_id, '{"en": "Widget A"}'),
        )
        existing_product_id = cursor.fetchone()[0]
    conn.commit()

    summary, promo = _run(conn, tenant_id, job_id, user_id, [_template_row(unit_price="19.99")])
    conn.commit()

    assert promo.products_created == 0
    staging_row_id = summary.row_outcomes[0].staging_row_id
    _, _, transaction_id = _staging_row(conn, staging_row_id)
    product_id, _, _, _, _ = _transaction(conn, transaction_id)
    assert str(product_id) == str(existing_product_id)

    _, price, _, _, _ = _product(conn, existing_product_id)
    assert price == Decimal("999.00")  # untouched, even though the import's unit_price was 19.99


def test_row_missing_a_required_field_is_not_promoted_and_stays_unflagged(conn, seeded_tenant):
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(unit_price="-5")]  # negative price -> dropped by validate_typed_fields()
    summary, promo = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert promo.rows_promoted == 0
    assert promo.rows_skipped_incomplete == 1

    staging_row_id = summary.row_outcomes[0].staging_row_id
    status, committed_table, transaction_id = _staging_row(conn, staging_row_id)
    assert status == "PARTIAL"
    assert committed_table is None
    assert transaction_id is None


def test_multi_batch_promotion_stitches_results_together(conn, seeded_tenant, monkeypatch):
    """Forces _PROMOTION_BATCH_SIZE down to 2 so a 5-row promotion spans
    three batches - proves `known` (the product cache) and the row/staging
    correlation both survive correctly across batch boundaries, not just
    within a single batch."""
    monkeypatch.setattr(promotion, "_PROMOTION_BATCH_SIZE", 2)
    tenant_id, user_id, job_id = seeded_tenant
    rows = [_template_row(product_name=f"Widget {i}", quantity=str(i + 1)) for i in range(5)]

    summary, promo = _run(conn, tenant_id, job_id, user_id, rows)
    conn.commit()

    assert promo.rows_promoted == 5
    assert promo.products_created == 5
    for i, outcome in enumerate(summary.row_outcomes):
        status, committed_table, transaction_id = _staging_row(conn, outcome.staging_row_id)
        assert status == "COMMITTED"
        _, quantity, _, _, _ = _transaction(conn, transaction_id)
        assert quantity == i + 1
