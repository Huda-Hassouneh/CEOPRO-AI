"""
Integration test for ingestion_pipeline.py's DB-touching paths
(_insert_staging_row/_update_staging_row_status/_update_job_counts)
against a real PostgreSQL instance. Same convention as
test_integration_db.py: skipped unless AI_TEST_DATABASE_URL is set.
Requires migrations/20260830020000_add_field_level_ingestion_tracking.sql
applied (adds 'PARTIAL' to import_staging_rows' validation_status CHECK
and ingestion_jobs.rows_partial) - without it, the PARTIAL-row tests below
would fail with a CHECK violation, not a code bug.
"""
import os
import uuid

import psycopg2
import pytest

from src.ai.extraction import ingestion_pipeline

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


_UNUSABLE_ROW = {"product_name": "", "quantity": "0", "unit_price": "-5", "currency": "", "transaction_date": ""}


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
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Ingestion QA Co', 'JO', 'JOD');",
            (tenant_id,),
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
    return tenant_id, job_id


def _job_counts(conn, job_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT rows_processed, rows_partial, rows_failed FROM ingestion_jobs WHERE job_id = %s;", (job_id,)
        )
        return cursor.fetchone()


def _staging_row(conn, staging_row_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT validation_status, validation_errors, raw_payload_json "
            "FROM import_staging_rows WHERE staging_row_id = %s;",
            (staging_row_id,),
        )
        return cursor.fetchone()


def test_process_records_writes_staging_rows_and_marks_valid(conn, seeded_tenant_and_job):
    tenant_id, job_id = seeded_tenant_and_job
    rows = [_template_row()]

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn
    )
    conn.commit()

    assert summary.template_mode == "TEMPLATE_COMPLIANT"
    assert summary.rows_processed == 1
    staging_row_id = summary.row_outcomes[0].staging_row_id
    assert staging_row_id is not None

    status, _errors, raw_payload = _staging_row(conn, staging_row_id)
    assert status == "VALID"
    assert raw_payload == rows[0]
    assert _job_counts(conn, job_id) == (1, 0, 0)


def test_process_records_marks_partial_rows_with_field_level_errors_recorded(conn, seeded_tenant_and_job):
    """
    A row with one bad field (negative quantity) and otherwise-clean
    fields must land as PARTIAL, not INVALID - the whole point of the
    field-level refactor. validation_errors is a JSON-encoded
    {field: message} dict (no schema change needed - the column is
    already TEXT, which holds any string including JSON).
    """
    tenant_id, job_id = seeded_tenant_and_job
    rows = [_template_row(quantity="-3")]

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn
    )
    conn.commit()

    assert summary.rows_processed == 1
    assert summary.rows_partial == 1
    staging_row_id = summary.row_outcomes[0].staging_row_id

    status, errors, _raw = _staging_row(conn, staging_row_id)
    assert status == "PARTIAL"
    assert "quantity" in errors
    assert _job_counts(conn, job_id) == (1, 1, 0)


def test_process_records_marks_a_genuinely_unusable_row_invalid(conn, seeded_tenant_and_job):
    tenant_id, job_id = seeded_tenant_and_job
    rows = [_UNUSABLE_ROW]

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn
    )
    conn.commit()

    assert summary.rows_failed == 1
    staging_row_id = summary.row_outcomes[0].staging_row_id

    status, _errors, _raw = _staging_row(conn, staging_row_id)
    assert status == "INVALID"
    assert _job_counts(conn, job_id) == (0, 0, 1)


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
    rows = [_template_row(product_name="Weird\x00Row"), _template_row(product_name="Good Row After It")]

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn
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
    processed, _partial, failed = _job_counts(conn, job_id)
    assert (processed, failed) == (1, 1)


def test_multiple_rows_each_get_their_own_staging_row_and_job_counts_accumulate(conn, seeded_tenant_and_job):
    tenant_id, job_id = seeded_tenant_and_job
    rows = [_template_row(product_name="Good 1"), _UNUSABLE_ROW, _template_row(product_name="Good 2")]

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn
    )
    conn.commit()

    staging_ids = [o.staging_row_id for o in summary.row_outcomes]
    assert len(set(staging_ids)) == 3  # 3 distinct staging rows, not reused/collided

    processed, _partial, failed = _job_counts(conn, job_id)
    assert (processed, failed) == (2, 1)


def test_trusted_field_mapping_writes_staging_rows_the_same_way(conn, seeded_tenant_and_job):
    """A POS/ERP-style caller with its own field names, using
    trusted_field_mapping instead of any header-matching tier, still gets
    the full staging-row/job-count write path."""
    tenant_id, job_id = seeded_tenant_and_job
    headers = ["sku", "qty_sold", "unit_cost"]
    rows = [{"sku": "Widget A", "qty_sold": "5", "unit_cost": "19.99"}]
    mapping = {"sku": "product_name", "qty_sold": "quantity", "unit_cost": "unit_price"}

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="pos-sync", headers=headers, rows=rows,
        trusted_field_mapping=mapping, conn=conn,
    )
    conn.commit()

    assert summary.template_mode == "TRUSTED_MAPPING"
    assert summary.rows_processed == 1
    staging_row_id = summary.row_outcomes[0].staging_row_id
    status, _errors, _raw = _staging_row(conn, staging_row_id)
    assert status == "VALID"


def test_commit_every_flushes_progress_in_batches_visible_to_other_connections(conn, seeded_tenant_and_job):
    """
    Regression test for PENDING_ACTIONS.md #43 / src/ai/extraction/SCALING.md's
    fix #1: with commit_every set, progress is durably committed in batches
    rather than held in one uncommitted transaction for the whole file - proven
    here by reading job counts from a SEPARATE connection before this test's
    own `conn` fixture ever calls commit() (its teardown only rolls back).
    5 rows with commit_every=2 means 2 mid-loop flushes (after rows 2 and 4)
    plus one final flush for the last row - all 5 must already be visible.
    """
    tenant_id, job_id = seeded_tenant_and_job
    rows = [_template_row() for _ in range(5)]

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows,
        conn=conn, commit_every=2,
    )
    assert summary.rows_processed == 5

    other = psycopg2.connect(DATABASE_URL)
    other.autocommit = True
    try:
        with other.cursor() as cursor:
            cursor.execute(
                "SELECT rows_processed, rows_partial, rows_failed FROM ingestion_jobs WHERE job_id = %s;",
                (job_id,),
            )
            assert cursor.fetchone() == (5, 0, 0)
    finally:
        other.close()


def test_without_commit_every_progress_stays_uncommitted_until_the_caller_commits(conn, seeded_tenant_and_job):
    """
    The default (commit_every=None) must be unchanged: process_records()
    never commits on its own, so the original all-or-nothing contract some
    callers rely on for rollback-based cleanup (this file's own `conn`
    fixture included) still holds.
    """
    tenant_id, job_id = seeded_tenant_and_job
    rows = [_template_row() for _ in range(3)]

    summary = ingestion_pipeline.process_records(
        tenant_id=tenant_id, job_id=job_id, source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows, conn=conn,
    )
    assert summary.rows_processed == 3

    other = psycopg2.connect(DATABASE_URL)
    other.autocommit = True
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT rows_processed FROM ingestion_jobs WHERE job_id = %s;", (job_id,))
            assert cursor.fetchone() == (0,)  # nothing committed yet - still the pre-run value
    finally:
        other.close()
