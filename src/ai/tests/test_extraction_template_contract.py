"""
Unit tests for template_contract.py::match_canonical_template() - the
TEMPLATE_COMPLIANT tier's own decision point, distinct from
template_detection.py's fuzzy RECOGNIZED-tier matcher (see both modules'
docstrings for why they're deliberately separate).
"""
from src.ai.extraction.template_contract import (
    REQUIRED_TEMPLATE_FIELDS, TEMPLATE_HEADER_ROW, match_canonical_template,
)


def test_exact_canonical_headers_match():
    mapping = match_canonical_template(TEMPLATE_HEADER_ROW)
    assert mapping is not None
    assert set(mapping.values()) == set(TEMPLATE_HEADER_ROW)


def test_case_and_whitespace_variation_still_matches():
    headers = ["  Product_Name ", "QUANTITY", "Unit_Price", "Currency", "Transaction_Date"]
    mapping = match_canonical_template(headers)
    assert mapping is not None
    assert mapping["  Product_Name "] == "product_name"


def test_extra_unrecognized_columns_do_not_disqualify_compliance():
    headers = ["product_name", "quantity", "unit_price", "currency", "transaction_date", "warehouse_notes"]
    mapping = match_canonical_template(headers)
    assert mapping is not None
    assert "warehouse_notes" not in mapping  # carried as unmapped, not disqualifying


def test_column_order_does_not_matter():
    headers = list(reversed(TEMPLATE_HEADER_ROW))
    assert match_canonical_template(headers) is not None


def test_missing_a_required_field_is_not_compliant():
    headers = [h for h in TEMPLATE_HEADER_ROW if h != "unit_price"]
    assert match_canonical_template(headers) is None


def test_synonym_alone_does_not_count_as_canonical_compliance():
    """"Item"/"Qty"/"Price" are real HEADER_SYNONYMS entries (RECOGNIZED
    tier) but were never given the chance to literally match the
    template's own header text - not TEMPLATE_COMPLIANT."""
    headers = ["item", "qty", "price", "currency", "date"]
    assert match_canonical_template(headers) is None


def test_only_required_fields_present_is_still_compliant():
    headers = list(REQUIRED_TEMPLATE_FIELDS)
    assert match_canonical_template(headers) is not None


def test_completely_unrelated_headers_do_not_match():
    assert match_canonical_template(["a", "b", "c"]) is None
