"""
Integration test for ingestion_pipeline.py's DB-touching paths
(_insert_staging_row/_update_staging_row_status/_update_job_counts)
against a real PostgreSQL instance. Same convention as
test_integration_db.py: skipped unless AI_TEST_DATABASE_URL is set.
These functions had never been run against a real database before this -
the offline unit tests in test_extraction_ingestion_pipeline.py only
exercise dry-run mode (conn=None).
"""
import os
import uuid

import psycopg2
import pytest

from src.ai.extraction import ingestion_pipeline

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def seeded_tenant_and_job(conn):
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Ingestion QA Co', 'JO', 'JOD');",
            (tenant_id,),
        )
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) VALUES (%s, %s, 'Test Source', 'CSV_UPLOAD');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO ingestion_jobs (job_id, tenant_id, source_id) VALUES (%s, %s, %s);",
            (job_id, tenant_id, source_id),
        )
    conn.commit()
    return tenant_id, job_id


def test_process_file_writes_staging_rows_and_marks_valid(conn, seeded_tenant_and_job):
    tenant_id, job_id = seeded_tenant_and_job
    headers = ["product_name", "quantity", "unit_price"]
    rows = [{"product_name": "Widget A", "quantity": "5", "unit_price": "19.99"}]

    summary = ingestion_pipeline.process_file(
        tenant_id=tenant_id, job_id=job_id, source_filename="f.csv", headers=headers, rows=rows, conn=conn
    )
    conn.commit()

    assert summary.rows_processed == 1
    staging_row_id = summary.row_outcomes[0].staging_row_id
    assert staging_row_id is not None

    with conn.cursor() as cursor:
        cursor.execute("SELECT validation_status, raw_payload_json FROM import_staging_rows WHERE staging_row_id = %s;", (staging_row_id,))
        status, raw_payload = cursor.fetchone()
        assert status == "VALID"
        assert raw_payload == rows[0]

        cursor.execute("SELECT rows_processed, rows_failed FROM ingestion_jobs WHERE job_id = %s;", (job_id,))
        processed, failed = cursor.fetchone()
        assert processed == 1
        assert failed == 0


def test_process_file_marks_validation_failures_invalid_with_error_recorded(conn, seeded_tenant_and_job):
    tenant_id, job_id = seeded_tenant_and_job
    headers = ["product_name", "quantity", "unit_price"]
    rows = [{"product_name": "Bad Widget", "quantity": "-3", "unit_price": "19.99"}]

    summary = ingestion_pipeline.process_file(
        tenant_id=tenant_id, job_id=job_id, source_filename="f.csv", headers=headers, rows=rows, conn=conn
    )
    conn.commit()

    assert summary.rows_failed == 1
    staging_row_id = summary.row_outcomes[0].staging_row_id

    with conn.cursor() as cursor:
        cursor.execute("SELECT validation_status, validation_errors FROM import_staging_rows WHERE staging_row_id = %s;", (staging_row_id,))
        status, errors = cursor.fetchone()
        assert status == "INVALID"
        assert "quantity" in errors

        cursor.execute("SELECT rows_processed, rows_failed FROM ingestion_jobs WHERE job_id = %s;", (job_id,))
        processed, failed = cursor.fetchone()
        assert processed == 0
        assert failed == 1


def test_a_row_that_fails_at_the_database_level_does_not_poison_the_rest_of_the_file(conn, seeded_tenant_and_job):
    """
    Regression test for a real bug found via this exact live-DB test:
    a NUL byte in a cell value makes the staging INSERT itself fail
    (psycopg2.errors.UntranslatableCharacter - Postgres genuinely cannot
    store \\x00 in JSONB/text at all, a hard limitation, not something
    fixable while still preserving the raw value untouched). Before the
    savepoint fix, that one failed INSERT left the whole transaction
    aborted, so every later statement on the same connection - including
    later rows' inserts and the final job-count update - failed too with
    psycopg2.errors.InFailedSqlTransaction, even though their content had
    nothing to do with the row that actually failed.
    """
    tenant_id, job_id = seeded_tenant_and_job
    headers = ["product_name", "quantity", "unit_price"]
    rows = [
        {"product_name": "Weird\x00Row", "quantity": "5", "unit_price": "19.99"},  # NUL byte - staging insert itself fails
        {"product_name": "Good Row After It", "quantity": "3", "unit_price": "9.99"},  # must still process fine
    ]

    summary = ingestion_pipeline.process_file(
        tenant_id=tenant_id, job_id=job_id, source_filename="f.csv", headers=headers, rows=rows, conn=conn
    )
    conn.commit()  # must not raise - would if the transaction were still aborted

    # the NUL-byte row: reported as a clean, visible failure, not silently dropped
    assert summary.row_outcomes[0].staging_row_id is None
    assert "staging insert failed" in summary.row_outcomes[0].error

    # the row after it: fully unaffected by the earlier row's DB-level failure
    assert summary.row_outcomes[1].staging_row_id is not None
    assert summary.row_outcomes[1].error is None

    assert summary.rows_processed == 1
    assert summary.rows_failed == 1

    with conn.cursor() as cursor:
        cursor.execute("SELECT rows_processed, rows_failed FROM ingestion_jobs WHERE job_id = %s;", (job_id,))
        processed, failed = cursor.fetchone()
        assert processed == 1
        assert failed == 1


def test_multiple_rows_each_get_their_own_staging_row_and_job_counts_accumulate(conn, seeded_tenant_and_job):
    tenant_id, job_id = seeded_tenant_and_job
    headers = ["product_name", "quantity", "unit_price"]
    rows = [
        {"product_name": "Good 1", "quantity": "5", "unit_price": "9.99"},
        {"product_name": "Bad", "quantity": "0", "unit_price": "9.99"},
        {"product_name": "Good 2", "quantity": "2", "unit_price": "4.99"},
    ]

    summary = ingestion_pipeline.process_file(
        tenant_id=tenant_id, job_id=job_id, source_filename="f.csv", headers=headers, rows=rows, conn=conn
    )
    conn.commit()

    staging_ids = [o.staging_row_id for o in summary.row_outcomes]
    assert len(set(staging_ids)) == 3  # 3 distinct staging rows, not reused/collided

    with conn.cursor() as cursor:
        cursor.execute("SELECT rows_processed, rows_failed FROM ingestion_jobs WHERE job_id = %s;", (job_id,))
        processed, failed = cursor.fetchone()
        assert processed == 2
        assert failed == 1
