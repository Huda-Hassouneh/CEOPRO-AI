"""Barcode column on sales/product imports: cell repair, header recognition, row parsing,
and promotion (fill-only, no duplicates for a re-named product, never blocks the sale)."""
from unittest.mock import MagicMock, patch

import pytest

from src.ai.core.barcode import parse_barcode_cell
from src.ai.extraction import promotion
from src.ai.extraction.ingestion_pipeline import IngestionRowOutcome, IngestionSummary
from src.ai.extraction.promotion import (
    _alias_names_by_barcode, _apply_barcodes, _extract_eligible_rows, _load_barcode_index,
)
from src.ai.extraction.row_parsing import RowParseResult, parse_mapped_row
from src.ai.extraction.template_detection import HEADER_SYNONYMS, normalize_header


@pytest.mark.parametrize("cell,expected", [
    ("3017620422003", "3017620422003"),
    ("3017620422003.0", "3017620422003"),          # Excel number formatting
    ("3.017620422003E+12", "3017620422003"),       # Excel scientific notation
    (3017620422003, "3017620422003"),
    ("'3017620422003", "3017620422003"),           # text-forced cell
    ("3017 6204-22003", "3017620422003"),
    ("36000291452", "036000291452"),               # UPC-A that lost its leading zero
    ("96385074", "96385074"),                      # EAN-8
    ("3017620422004", None),                       # wrong check digit
    ("12345", None), ("ABC-123", None), ("", None), (None, None), ("1.5", None),
])
def test_parse_barcode_cell(cell, expected):
    assert parse_barcode_cell(cell) == expected


def test_barcode_headers_are_recognised_but_internal_codes_are_not():
    recognised = {normalize_header(h) for h in HEADER_SYNONYMS["barcode"]}
    for header in ("Barcode", "EAN", "UPC", "GTIN", "Code barre", "الباركود", "Item Barcode"):
        assert normalize_header(header) in recognised
    for header in ("SKU", "Product Code", "Item Code", "Product ID"):
        assert normalize_header(header) not in recognised  # not scannable barcodes


def test_a_valid_barcode_cell_becomes_a_typed_field_and_an_invalid_one_is_dropped_quietly():
    mapping = {"EAN": "barcode", "Item": "product_name"}
    good = parse_mapped_row({"EAN": "3017620422003.0", "Item": "Nutella"}, mapping, "t1")
    assert good.typed_fields["barcode"] == "3017620422003" and good.raw_fields["barcode"] == "3017620422003.0"
    bad = parse_mapped_row({"EAN": "3017620422004", "Item": "Nutella"}, mapping, "t1")
    assert "barcode" not in bad.typed_fields and bad.typed_fields["product_name"] == "Nutella"


_FIELDS = {"product_name": "Nutella 400g", "quantity": "2", "unit_price": "4.5", "currency": "JOD", "transaction_date": "2026-10-01"}


def _rows(*field_dicts):
    summary = IngestionSummary(tenant_id="t1", job_id="j1", source_name="f.csv", template_mode="RECOGNIZED", header_coverage_ratio=1.0)
    summary.row_outcomes = [
        IngestionRowOutcome(row_index=i, staging_row_id=100 + i, mode="RECOGNIZED", parse_result=RowParseResult(tenant_id="t1", typed_fields=dict(f)))
        for i, f in enumerate(field_dicts)
    ]
    return _extract_eligible_rows(summary)[0]


def test_the_barcode_rides_along_but_does_not_change_row_identity_for_duplicate_detection():
    with_code, without = _rows({**_FIELDS, "barcode": "3017620422003"}), _rows(_FIELDS)
    assert with_code[0].barcode == "3017620422003" and without[0].barcode is None
    assert with_code[0].invoice_number == without[0].invoice_number  # re-importing the same sale stays a duplicate


def test_a_renamed_product_is_recognised_by_its_barcode_instead_of_duplicated():
    rows = _rows({**_FIELDS, "product_name": "NUTELLA JAR 400", "barcode": "3017620422003"},
                 {**_FIELDS, "product_name": "Unrelated", "barcode": "96385074"})
    known = {"nutella hazelnut spread 400g": "p-existing"}
    matched = _alias_names_by_barcode(rows, known, {"3017620422003": "p-existing"})
    assert matched == 1 and known["nutella jar 400"] == "p-existing" and "unrelated" not in known


def _conn_with_rowcount(rowcount=1):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.rowcount = rowcount
    return conn


def test_barcodes_are_fill_only_and_never_reused_across_products():
    rows = _rows(
        {**_FIELDS, "product_name": "A", "barcode": "3017620422003"},
        {**_FIELDS, "product_name": "A", "barcode": "96385074"},          # same product, second code: first wins
        {**_FIELDS, "product_name": "B", "barcode": "3017620422003"},    # code already given to A in this file
        {**_FIELDS, "product_name": "C", "barcode": "036000291452"},     # product already has a (different) barcode
        {**_FIELDS, "product_name": "D"},                                 # no barcode
    )
    known = {"a": "pa", "b": "pb", "c": "pc", "d": "pd"}
    conn = _conn_with_rowcount(1)
    with patch.object(promotion, "_run_in_savepoint", side_effect=lambda c, n, fn: fn()):
        applied = _apply_barcodes(conn, "t1", rows, known, {"9999999999994": "pc"})
    sql, params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
    assert "p.metadata->>'barcode' IS NULL" in sql           # a curated barcode is never overwritten
    assert params == (["pa", "pc"], ["3017620422003", "036000291452"], "t1")
    assert applied == 1


def test_a_barcode_write_failure_never_stops_the_import():
    rows = _rows({**_FIELDS, "barcode": "3017620422003"})
    with patch.object(promotion, "_run_in_savepoint", side_effect=RuntimeError("db")):
        assert _apply_barcodes(MagicMock(), "t1", rows, {"nutella 400g": "p1"}, {}) == 0


def test_barcode_index_reads_only_active_products_with_a_barcode():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [("3017620422003", "p1"), (None, "p2")]
    assert _load_barcode_index(conn, "t1") == {"3017620422003": "p1"}
    assert "deleted_at IS NULL" in conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
