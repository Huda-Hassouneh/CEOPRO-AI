"""
Unit tests for row_parsing.py::validate_typed_fields() - spec S12's
"Validate values" step. Before this existed, a cell that parsed cleanly
(a real number, a real date shape) was treated as fully valid regardless
of whether the value made semantic sense (a negative price, a zero
quantity, a year outside any plausible invoice range).
"""
from datetime import date

from src.ai.extraction.row_parsing import RowParseResult, validate_typed_fields


def _result(**typed_fields) -> RowParseResult:
    r = RowParseResult(tenant_id="t1")
    r.typed_fields = typed_fields
    return r


def test_valid_row_has_no_errors():
    r = _result(product_name="Widget", quantity="5", unit_price="19.99", transaction_date="2026-08-28")
    assert validate_typed_fields(r) == []


def test_negative_unit_price_is_rejected():
    r = _result(unit_price="-5.00")
    errors = validate_typed_fields(r)
    assert len(errors) == 1
    assert "unit_price" in errors[0]
    assert "negative" in errors[0]


def test_negative_amount_raw_is_rejected():
    errors = validate_typed_fields(_result(amount_raw="-10"))
    assert any("amount_raw" in e for e in errors)


def test_negative_discount_pct_is_rejected():
    errors = validate_typed_fields(_result(discount_pct="-5"))
    assert any("discount_pct" in e for e in errors)


def test_negative_quantity_is_rejected():
    errors = validate_typed_fields(_result(quantity="-3"))
    assert any("negative" in e and "quantity" in e for e in errors)


def test_zero_quantity_is_rejected():
    errors = validate_typed_fields(_result(quantity="0"))
    assert any("zero quantity" in e for e in errors)


def test_zero_unit_price_is_allowed():
    """A free item (price 0) is a legitimate business case, unlike a
    negative price or a zero-quantity 'sale'."""
    assert validate_typed_fields(_result(unit_price="0")) == []


def test_positive_values_pass():
    r = _result(amount_raw="100", unit_price="19.99", discount_pct="10", quantity="5")
    assert validate_typed_fields(r) == []


def test_date_far_in_the_past_is_rejected():
    errors = validate_typed_fields(_result(transaction_date="1900-01-01"))
    assert any("transaction_date" in e for e in errors)


def test_date_far_in_the_future_is_rejected():
    errors = validate_typed_fields(_result(transaction_date="2099-01-01"), today=date(2026, 8, 28))
    assert any("transaction_date" in e for e in errors)


def test_date_this_year_and_slightly_forward_dated_is_allowed():
    errors = validate_typed_fields(_result(transaction_date="2027-01-01"), today=date(2026, 8, 28))
    assert errors == []


def test_malformed_date_is_rejected():
    errors = validate_typed_fields(_result(transaction_date="not-a-date"))
    assert any("transaction_date" in e for e in errors)


def test_valid_email_passes():
    assert validate_typed_fields(_result(email="owner@example.com")) == []


def test_invalid_email_is_rejected():
    errors = validate_typed_fields(_result(email="not-an-email"))
    assert any("email" in e for e in errors)


def test_multiple_validation_errors_all_reported_together():
    r = _result(quantity="-1", unit_price="-5", email="bad")
    errors = validate_typed_fields(r)
    assert len(errors) == 3


def test_missing_optional_fields_produce_no_errors():
    """A row that only has product_name (a text field, no validation
    rule applies) must not spuriously fail."""
    assert validate_typed_fields(_result(product_name="Widget")) == []
