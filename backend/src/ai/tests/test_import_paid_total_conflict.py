"""A stated paid line total above quantity x unit price is held for review, never silently replaced."""
from src.ai.extraction.typed_imports import validate_typed_import_row

BASE = dict(product_name="Olive oil", quantity="3", unit_price="24.50", currency="JOD", transaction_date="2026-10-01")


def _row(**extra):
    return validate_typed_import_row("sales", {**BASE, **extra}, source_row_key="row:1")


def test_discounted_and_rounded_totals_are_valid():
    assert _row(amount_raw="66.15")["validation_outcome"] == "valid"   # 10% discount
    assert _row(amount_raw="73.500")["validation_outcome"] == "valid"  # exact
    assert _row(amount_raw="73.5004")["validation_outcome"] == "valid"  # within half a fils


def test_total_above_quantity_times_price_needs_review():
    row = _row(amount_raw="735.00")  # a misread digit
    assert row["validation_outcome"] == "review_required"
    assert row["validation_findings"] == [
        {"field": "amount_raw", "code": "paid_total_exceeds_quantity_times_price_requires_review"}]


def test_no_conflict_check_when_a_figure_is_already_invalid():
    row = _row(amount_raw="735.00", unit_price="-1")
    assert {f["code"] for f in row["validation_findings"]} == {"must_be_nonnegative_number"}
