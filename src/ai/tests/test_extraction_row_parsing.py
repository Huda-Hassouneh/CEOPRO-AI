"""
Unit tests for row_parsing.py. Zero test coverage before this file (found
during a post-merge QA pass, same pass that found template_detection.py's
snake_case bug). A real bug was caught immediately: _parse_typed_cell()'s
"percent" branch passed the raw cell value straight to
normalize_number_string() without stripping a '%' - a discount_pct cell
written the natural way ("10%", not "10") failed to parse and silently
fell through to unmapped/fallback extraction, even though the column had
already been correctly identified as discount_pct by template_detection.py.
extract_percent() (regex_patterns.py)'s regex-based path already avoided
this - its capture group excludes the '%' - so this was specifically a
STRICT-mode typed-parsing inconsistency, not a numerals.py bug.
"""
from src.ai.extraction.row_parsing import parse_mapped_row


def test_percent_cell_with_percent_sign_parses_correctly():
    """Regression test for the discount_pct '%'-stripping bug."""
    mapping = {"discount_pct_col": "discount_pct"}
    row = {"discount_pct_col": "10%"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields.get("discount_pct") == "10"
    assert result.unmapped_columns == []
    assert result.field_confidence.get("discount_pct") == 1.0


def test_percent_cell_without_percent_sign_still_parses():
    mapping = {"discount_pct_col": "discount_pct"}
    row = {"discount_pct_col": "15"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields.get("discount_pct") == "15"


def test_percent_cell_with_decimal_and_percent_sign():
    mapping = {"discount_pct_col": "discount_pct"}
    row = {"discount_pct_col": "12.5%"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields.get("discount_pct") == "12.5"


def test_money_field_parses_typed_and_records_raw_and_provenance():
    mapping = {"Unit Price": "unit_price"}
    row = {"Unit Price": "19.99"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields["unit_price"] == "19.99"
    assert result.raw_fields["unit_price"] == "19.99"
    assert result.header_mapping["unit_price"] == "Unit Price"


def test_quantity_integer_parse_is_exact_and_high_confidence():
    mapping = {"Qty": "quantity"}
    row = {"Qty": "5"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields["quantity"] == "5"
    assert result.field_confidence["quantity"] == 1.0


def test_quantity_non_integer_rounds_with_reduced_confidence():
    mapping = {"Qty": "quantity"}
    row = {"Qty": "1.5"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields["quantity"] == "2"
    assert result.field_confidence["quantity"] == 0.7
    assert result.raw_fields["quantity"] == "1.5"  # untouched original survives separately


def test_unmapped_column_falls_back_to_regex_extraction():
    mapping = {}  # nothing mapped
    row = {"notes": "Sold for 45.00 JOD"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.unmapped_columns == ["notes"]
    assert any(e.entity_type == "MONEY" for e in result.fallback_entities)


def test_empty_and_none_cells_are_skipped_entirely():
    mapping = {"unit_price_col": "unit_price", "qty_col": "quantity"}
    row = {"unit_price_col": "", "qty_col": None}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields == {}
    assert result.unmapped_columns == []  # blank cells aren't "unmapped", they're just skipped


def test_currency_code_parses_and_normalizes_case():
    """currency (template_contract.py's canonical template) is a plain
    3-letter ISO code, kept separate from unit_price/amount_raw's cells
    rather than accepted combined ("24.50 JOD") - normalize_number_string()
    has no currency-symbol handling at all."""
    mapping = {"Currency": "currency"}
    row = {"Currency": "jod"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert result.typed_fields["currency"] == "JOD"
    assert result.field_confidence["currency"] == 1.0


def test_currency_code_rejects_non_3_letter_values():
    mapping = {"Currency": "currency"}
    row = {"Currency": "Jordanian Dinar"}
    result = parse_mapped_row(row, mapping, tenant_id="t1")
    assert "currency" not in result.typed_fields
    assert result.unmapped_columns == ["Currency"]
