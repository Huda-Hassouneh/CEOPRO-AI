"""
Offline tests for promotion.py's pure eligibility logic
(_extract_eligible_rows) - no DB needed, since it only reads
IngestionSummary/IngestionRowOutcome objects already in memory. DB-touching
paths (product dedup/creation, bulk transaction insert, staging-row
flagging, the batch-failure row-by-row fallback) are covered by
test_extraction_promotion_integration_db.py against a real Postgres,
matching this session's established "verify live, don't just claim"
convention.
"""
from src.ai.extraction.ingestion_pipeline import IngestionRowOutcome, IngestionSummary
from src.ai.extraction.promotion import _extract_eligible_rows
from src.ai.extraction.row_parsing import RowParseResult


def _outcome(row_index, staging_row_id, typed_fields):
    result = RowParseResult(tenant_id="t1", typed_fields=dict(typed_fields))
    return IngestionRowOutcome(row_index=row_index, staging_row_id=staging_row_id, mode="TEMPLATE_COMPLIANT", parse_result=result)


_COMPLETE_FIELDS = {
    "product_name": "Widget A", "quantity": "5", "unit_price": "19.99",
    "currency": "JOD", "transaction_date": "2026-08-30",
}


def _summary(*outcomes):
    s = IngestionSummary(tenant_id="t1", job_id="j1", source_name="f.csv", template_mode="TEMPLATE_COMPLIANT", header_coverage_ratio=1.0)
    s.row_outcomes = list(outcomes)
    return s


def test_row_with_all_required_fields_is_eligible():
    summary = _summary(_outcome(0, 101, _COMPLETE_FIELDS))
    eligible, skipped = _extract_eligible_rows(summary)

    assert skipped == 0
    assert len(eligible) == 1
    assert eligible[0].staging_row_id == 101
    assert eligible[0].product_name_normalized == "widget a"
    assert eligible[0].quantity == 5


def test_row_missing_a_required_field_is_skipped_not_promoted():
    fields = dict(_COMPLETE_FIELDS)
    del fields["unit_price"]  # e.g. dropped by validate_typed_fields() for being negative
    summary = _summary(_outcome(0, 101, fields))

    eligible, skipped = _extract_eligible_rows(summary)

    assert eligible == []
    assert skipped == 1


def test_row_missing_only_an_optional_field_is_still_eligible():
    """A PARTIAL row (e.g. bad email) with all 5 required fields intact
    must still promote - eligibility is about the required set only."""
    fields = dict(_COMPLETE_FIELDS)
    fields["email"] = None  # never set to begin with, same as a dropped optional field
    summary = _summary(_outcome(0, 101, fields))

    eligible, skipped = _extract_eligible_rows(summary)

    assert len(eligible) == 1
    assert skipped == 0


def test_fallback_mode_row_with_no_parse_result_is_skipped():
    outcome = IngestionRowOutcome(row_index=0, staging_row_id=101, mode="FALLBACK", parse_result=None)
    summary = _summary(outcome)

    eligible, skipped = _extract_eligible_rows(summary)

    assert eligible == []
    assert skipped == 0  # not "incomplete", just never had structured fields to begin with


def test_row_that_failed_staging_insert_entirely_is_skipped():
    outcome = IngestionRowOutcome(row_index=0, staging_row_id=None, mode="TEMPLATE_COMPLIANT", error="staging insert failed")
    summary = _summary(outcome)

    eligible, skipped = _extract_eligible_rows(summary)

    assert eligible == []
    assert skipped == 0


def test_blank_product_name_is_skipped():
    fields = dict(_COMPLETE_FIELDS)
    fields["product_name"] = "   "
    summary = _summary(_outcome(0, 101, fields))

    eligible, skipped = _extract_eligible_rows(summary)

    assert eligible == []
    assert skipped == 1


def test_row_missing_currency_is_skipped_when_no_default_currency_given():
    fields = dict(_COMPLETE_FIELDS)
    del fields["currency"]  # e.g. Electronics_For_Test.xlsx: no currency column in the source file at all
    summary = _summary(_outcome(0, 101, fields))

    eligible, skipped = _extract_eligible_rows(summary)

    assert eligible == []
    assert skipped == 1


def test_row_missing_currency_falls_back_to_default_currency():
    fields = dict(_COMPLETE_FIELDS)
    del fields["currency"]
    summary = _summary(_outcome(0, 101, fields))

    eligible, skipped = _extract_eligible_rows(summary, default_currency="JOD")

    assert skipped == 0
    assert len(eligible) == 1
    assert eligible[0].currency == "JOD"


def test_row_with_its_own_currency_ignores_the_default():
    fields = dict(_COMPLETE_FIELDS, currency="USD")
    summary = _summary(_outcome(0, 101, fields))

    eligible, _ = _extract_eligible_rows(summary, default_currency="JOD")

    assert eligible[0].currency == "USD"


def test_product_name_normalization_matches_case_and_whitespace_insensitively():
    a = dict(_COMPLETE_FIELDS, product_name="  Widget A  ")
    b = dict(_COMPLETE_FIELDS, product_name="WIDGET a")
    summary = _summary(_outcome(0, 101, a), _outcome(1, 102, b))

    eligible, _ = _extract_eligible_rows(summary)

    assert eligible[0].product_name_normalized == eligible[1].product_name_normalized == "widget a"
