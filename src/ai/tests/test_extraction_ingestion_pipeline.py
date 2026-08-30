"""
Unit tests for ingestion_pipeline.py::process_records() - the Universal
Import Engine's orchestrator (spec S12), now with 4 tiers
(TRUSTED_MAPPING/TEMPLATE_COMPLIANT/RECOGNIZED/FALLBACK) and field-level
(not row-level) validation. Renamed from process_file()/source_filename -
this function has zero production callers (confirmed directly before this
rewrite), so the rename carries no back-compat cost; "records" fits a
caller-supplied API/DB batch as well as a file's rows, which "file" didn't.

Dry-run mode only (conn=None) - the DB-touching paths (_insert_staging_row,
_update_staging_row_status, _update_job_counts) are covered separately by
a live-DB integration test.
"""
from unittest.mock import MagicMock, patch

from src.ai.extraction.ingestion_pipeline import process_records

_TEMPLATE_HEADERS = ["product_name", "quantity", "unit_price", "currency", "transaction_date"]


def _template_row(**overrides):
    row = {
        "product_name": "Widget A", "quantity": "5", "unit_price": "19.99",
        "currency": "JOD", "transaction_date": "2026-08-30",
    }
    row.update(overrides)
    return row


def test_template_compliant_headers_are_detected_and_processed():
    rows = [_template_row()]
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows)
    assert summary.template_mode == "TEMPLATE_COMPLIANT"
    assert summary.rows_processed == 1
    assert summary.rows_partial == 0
    assert summary.rows_failed == 0
    assert summary.row_outcomes[0].error is None
    assert summary.row_outcomes[0].field_errors == {}
    assert summary.is_template_compliant is True
    assert summary.data_loss_pct == 0.0


def test_recognized_mode_synonym_headers_are_not_template_compliant():
    """Headers recognized via HEADER_SYNONYMS ("Item"/"Qty"/"Price"-style
    aliases), not the template's own literal column names, get the
    RECOGNIZED tier - best-effort, not the guarantee tier."""
    headers = ["product name", "quantity", "unit price"]
    rows = [{"product name": "Widget A", "quantity": "5", "unit price": "19.99"}]
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=headers, rows=rows)
    assert summary.template_mode == "RECOGNIZED"
    assert summary.rows_processed == 1
    assert summary.is_template_compliant is False


def test_fallback_mode_unrecognized_headers_still_extracts_entities():
    headers = ["notes"]
    rows = [{"notes": "Sold for 45.00 JOD, 10% off"}]
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=headers, rows=rows)
    assert summary.template_mode == "FALLBACK"
    assert summary.rows_processed == 1
    assert summary.row_outcomes[0].fallback_entity_count >= 1
    assert summary.is_template_compliant is False


def test_trusted_mapping_bypasses_header_matching_entirely():
    """A DB/API/POS/ERP caller supplies its own field mapping directly -
    headers that would never pass HEADER_SYNONYMS or the canonical
    template on their own (vendor-specific field names) still get full
    typed parsing and are guarantee-eligible, because the caller already
    knows its own schema with certainty."""
    headers = ["sku", "qty_sold", "unit_cost"]
    rows = [{"sku": "Widget A", "qty_sold": "5", "unit_cost": "19.99"}]
    mapping = {"sku": "product_name", "qty_sold": "quantity", "unit_cost": "unit_price"}
    summary = process_records(
        tenant_id="t1", job_id="j1", source_name="pos-sync", headers=headers, rows=rows,
        trusted_field_mapping=mapping,
    )
    assert summary.template_mode == "TRUSTED_MAPPING"
    assert summary.rows_processed == 1
    assert summary.is_template_compliant is True


def test_one_bad_field_demotes_only_that_field_not_the_whole_row():
    """The core behavior change: a row that parses cleanly except for one
    semantically-invalid field (negative quantity) must still be
    processed, with the bad field dropped and every other field kept -
    not rejected wholesale the way it used to be."""
    rows = [_template_row(quantity="-3")]
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows)
    assert summary.rows_processed == 1
    assert summary.rows_partial == 1
    assert summary.rows_failed == 0
    outcome = summary.row_outcomes[0]
    assert outcome.error is None
    assert "quantity" in outcome.field_errors
    assert "negative" in outcome.field_errors["quantity"]
    assert "quantity" not in outcome.parse_result.typed_fields
    assert outcome.parse_result.typed_fields["product_name"] == "Widget A"
    assert outcome.parse_result.typed_fields["unit_price"] == "19.99"
    assert summary.is_template_compliant is False  # verified, not assumed, from the tier alone
    assert summary.data_loss_pct > 0.0


def test_row_with_zero_usable_fields_is_a_genuine_failure():
    """Only when literally nothing survives (every mapped field either
    blank or failing validation, no fallback entities either) is a row
    excluded from rows_processed - the field-level change narrows this
    case, it doesn't eliminate it."""
    rows = [_template_row(product_name="", quantity="0", unit_price="-5", currency="", transaction_date="")]
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows)
    assert summary.rows_processed == 0
    assert summary.rows_failed == 1
    assert summary.row_outcomes[0].error is not None


def test_mixed_valid_partial_and_failed_rows_are_each_reported_correctly():
    rows = [
        _template_row(product_name="Good Widget"),
        _template_row(product_name="Partial Widget", quantity="0"),
        _template_row(product_name="", quantity="0", unit_price="-5", currency="", transaction_date=""),
    ]
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows)
    assert summary.rows_processed == 2
    assert summary.rows_partial == 1
    assert summary.rows_failed == 1
    assert summary.row_outcomes[0].error is None and summary.row_outcomes[0].field_errors == {}
    assert summary.row_outcomes[1].error is None and summary.row_outcomes[1].field_errors
    assert summary.row_outcomes[2].error is not None


def test_data_loss_pct_reflects_dropped_fields_not_blank_optional_cells():
    """A blank optional cell was never data to lose - it must not count
    against the file's loss percentage the way a genuinely dropped,
    non-blank value does."""
    headers = _TEMPLATE_HEADERS + ["discount_pct"]
    rows = [_template_row(discount_pct="")]  # blank optional field, present in the header row
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=headers, rows=rows)
    assert summary.is_template_compliant is True
    assert summary.data_loss_pct == 0.0


def test_empty_rows_produces_empty_summary_with_no_errors():
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=["a"], rows=[])
    assert summary.rows_processed == 0
    assert summary.rows_failed == 0
    assert summary.row_outcomes == []
    assert summary.is_template_compliant is False  # nothing was ever processed to verify


def test_dry_run_mode_never_touches_conn_redis_or_minio():
    """conn=None/redis_client=None/minio_client=None (all defaults) must
    fully complete without requiring any of the three - this is the
    documented preview/dry-run contract."""
    rows = [_template_row()]
    summary = process_records(tenant_id="t1", job_id="j1", source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows)
    assert summary.minio_object_key is None
    assert all(o.staging_row_id is None for o in summary.row_outcomes)


def test_minio_upload_called_when_client_provided_and_rows_processed():
    rows = [_template_row()]
    fake_minio = MagicMock()
    with patch(
        "src.ai.extraction.ingestion_pipeline.upload_extraction_document", return_value="tenant/job/key.json"
    ) as mock_upload:
        summary = process_records(
            tenant_id="t1", job_id="j1", source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows,
            minio_client=fake_minio,
        )
    mock_upload.assert_called_once()
    assert summary.minio_object_key == "tenant/job/key.json"


def test_minio_upload_includes_partial_rows_not_just_fully_clean_ones():
    """A partial row still has real, useful typed_fields - it belongs in
    the MinIO extraction document, not silently excluded the way a fully
    failed row is."""
    rows = [_template_row(quantity="0")]
    fake_minio = MagicMock()
    with patch(
        "src.ai.extraction.ingestion_pipeline.upload_extraction_document", return_value="tenant/job/key.json"
    ) as mock_upload:
        summary = process_records(
            tenant_id="t1", job_id="j1", source_name="f.csv", headers=_TEMPLATE_HEADERS, rows=rows,
            minio_client=fake_minio,
        )
    mock_upload.assert_called_once()
    assert summary.minio_object_key == "tenant/job/key.json"


def test_minio_upload_skipped_when_the_only_row_failed_outright():
    headers = _TEMPLATE_HEADERS
    rows = [{"product_name": "", "quantity": "0", "unit_price": "-5", "currency": "", "transaction_date": ""}]
    fake_minio = MagicMock()
    with patch("src.ai.extraction.ingestion_pipeline.upload_extraction_document") as mock_upload:
        summary = process_records(
            tenant_id="t1", job_id="j1", source_name="f.csv", headers=headers, rows=rows, minio_client=fake_minio
        )
    mock_upload.assert_not_called()
    assert summary.minio_object_key is None
