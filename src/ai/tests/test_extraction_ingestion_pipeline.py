"""
Unit tests for ingestion_pipeline.py::process_file() - the Universal
Import Engine's orchestrator (spec S12). Zero coverage anywhere in the
repo before this file (test_extraction_pipeline.py tests a different,
same-named-adjacent module - extraction/pipeline.py's NER persistence
pipeline, not this one). Dry-run mode only (conn=None) - the DB-touching
paths (_insert_staging_row, _update_staging_row_status, _update_job_counts)
are covered separately by a live-DB integration test.
"""
from unittest.mock import MagicMock, patch

from src.ai.extraction.ingestion_pipeline import process_file


def test_strict_mode_recognized_headers_all_process_successfully():
    headers = ["product_name", "quantity", "unit_price"]
    rows = [{"product_name": "Widget A", "quantity": "5", "unit_price": "19.99"}]
    summary = process_file(tenant_id="t1", job_id="j1", source_filename="f.csv", headers=headers, rows=rows)
    assert summary.template_mode == "STRICT"
    assert summary.rows_processed == 1
    assert summary.rows_failed == 0
    assert summary.row_outcomes[0].error is None


def test_fallback_mode_unrecognized_headers_still_extracts_entities():
    headers = ["notes"]
    rows = [{"notes": "Sold for 45.00 JOD, 10% off"}]
    summary = process_file(tenant_id="t1", job_id="j1", source_filename="f.csv", headers=headers, rows=rows)
    assert summary.template_mode == "FALLBACK"
    assert summary.rows_processed == 1
    assert summary.row_outcomes[0].fallback_entity_count >= 1


def test_value_validation_failure_routes_row_to_failed_not_processed():
    """Regression test for the validate_typed_fields() wiring - a row
    that parses cleanly but fails semantic validation (negative quantity)
    must be reported as failed, not silently counted as processed."""
    headers = ["product_name", "quantity", "unit_price"]
    rows = [{"product_name": "Bad Widget", "quantity": "-3", "unit_price": "19.99"}]
    summary = process_file(tenant_id="t1", job_id="j1", source_filename="f.csv", headers=headers, rows=rows)
    assert summary.rows_processed == 0
    assert summary.rows_failed == 1
    assert "quantity" in summary.row_outcomes[0].error
    assert "negative" in summary.row_outcomes[0].error


def test_mixed_valid_and_invalid_rows_are_each_reported_correctly():
    headers = ["product_name", "quantity", "unit_price"]
    rows = [
        {"product_name": "Good Widget", "quantity": "5", "unit_price": "19.99"},
        {"product_name": "Bad Widget", "quantity": "0", "unit_price": "19.99"},
        {"product_name": "Another Good One", "quantity": "2", "unit_price": "9.99"},
    ]
    summary = process_file(tenant_id="t1", job_id="j1", source_filename="f.csv", headers=headers, rows=rows)
    assert summary.rows_processed == 2
    assert summary.rows_failed == 1
    assert summary.row_outcomes[1].error is not None
    assert summary.row_outcomes[0].error is None
    assert summary.row_outcomes[2].error is None


def test_empty_rows_produces_empty_summary_with_no_errors():
    summary = process_file(tenant_id="t1", job_id="j1", source_filename="f.csv", headers=["a"], rows=[])
    assert summary.rows_processed == 0
    assert summary.rows_failed == 0
    assert summary.row_outcomes == []


def test_dry_run_mode_never_touches_conn_redis_or_minio():
    """conn=None/redis_client=None/minio_client=None (all defaults) must
    fully complete without requiring any of the three - this is the
    documented preview/dry-run contract."""
    headers = ["product_name", "quantity", "unit_price"]
    rows = [{"product_name": "Widget", "quantity": "5", "unit_price": "9.99"}]
    summary = process_file(tenant_id="t1", job_id="j1", source_filename="f.csv", headers=headers, rows=rows)
    assert summary.minio_object_key is None
    assert all(o.staging_row_id is None for o in summary.row_outcomes)


def test_minio_upload_called_when_client_provided_and_rows_processed():
    headers = ["product_name", "quantity", "unit_price"]
    rows = [{"product_name": "Widget", "quantity": "5", "unit_price": "9.99"}]
    fake_minio = MagicMock()
    with patch(
        "src.ai.extraction.ingestion_pipeline.upload_extraction_document", return_value="tenant/job/key.json"
    ) as mock_upload:
        summary = process_file(
            tenant_id="t1", job_id="j1", source_filename="f.csv", headers=headers, rows=rows, minio_client=fake_minio
        )
    mock_upload.assert_called_once()
    assert summary.minio_object_key == "tenant/job/key.json"


def test_minio_upload_skipped_when_all_rows_failed_validation():
    """No successfully-parsed rows means nothing worth persisting to
    MinIO - the upload call should be skipped entirely, not attempted
    with an empty document. Headers must satisfy STRICT_MODE_REQUIRED_FIELDS
    (product_name/quantity/unit_price) so this actually exercises the
    validation path rather than falling through to FALLBACK mode, which
    has no typed-value validation to fail in the first place."""
    headers = ["product_name", "quantity", "unit_price"]
    rows = [{"product_name": "Bad", "quantity": "0", "unit_price": "9.99"}]
    fake_minio = MagicMock()
    with patch("src.ai.extraction.ingestion_pipeline.upload_extraction_document") as mock_upload:
        summary = process_file(
            tenant_id="t1", job_id="j1", source_filename="f.csv", headers=headers, rows=rows, minio_client=fake_minio
        )
    mock_upload.assert_not_called()
    assert summary.minio_object_key is None
