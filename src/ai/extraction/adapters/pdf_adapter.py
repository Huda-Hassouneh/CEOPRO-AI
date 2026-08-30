"""
CEOPRO AI - PDF Source Adapter.

Tries real structured extraction first: pdfplumber.extract_tables() per
page, using the header row of the first table found across the document
as the canonical header set for every subsequent table (the common shape
for a "standard PDF form" - a line-item table, possibly continuing across
pages, sharing one header row). A table on a later page whose header row
doesn't match (once normalized) is skipped rather than guessed at - mixing
mismatched column counts under one header set would silently misalign
cells, which is a worse outcome than not using that table at all; its
content is not otherwise recovered in this version (a known, documented
scope boundary, not a silent gap - see the module-level note below).

Only when NO table is found anywhere in the document does this fall back
to the original behavior: one row per page, the page's full text under a
single PAGE_TEXT_HEADER column, routing the file through FALLBACK/NER
extraction the same as before this file was upgraded - unstructured PDFs
lose nothing they weren't already losing.

Scope boundary, stated plainly: a page that DOES contain a detected table
only contributes that table's rows - any other text on the same page
(header info like "Invoice #, Date" printed above the line-item table) is
not separately captured in this version. The canonical template's fields
are expected to live IN the table for a page to be treated as structured;
free text alongside it is not part of the guaranteed data contract, the
same way a CSV/XLSX file has no equivalent for "text near the data".

Requires pdfplumber (pip install pdfplumber).
"""
from typing import Dict, List, Optional, Tuple

import pdfplumber

from src.ai.extraction.template_detection import normalize_header

PAGE_TEXT_HEADER = "page_text"

# A table needs at least a header row and one data row to be usable -
# pdfplumber's table detector can return single-row false positives from
# unrelated bordered boxes/rules on a page.
_MIN_TABLE_ROWS = 2


def _clean_header_row(raw_header_row: List[Optional[str]]) -> List[str]:
    return [(cell or "").strip() for cell in raw_header_row]


def _row_is_blank(raw_row: List[Optional[str]]) -> bool:
    return all(cell is None or str(cell).strip() == "" for cell in raw_row)


def _headers_match(a: List[str], b: List[str]) -> bool:
    return [normalize_header(h) for h in a] == [normalize_header(h) for h in b]


def _rows_from_table(table: list, canonical_headers: List[str]) -> List[Dict[str, object]]:
    rows = []
    for raw_row in table[1:]:
        if _row_is_blank(raw_row):
            continue
        rows.append({
            canonical_headers[idx]: raw_row[idx]
            for idx in range(len(canonical_headers))
            if idx < len(raw_row)
        })
    return rows


def _process_page_tables(
    page, canonical_headers: Optional[List[str]]
) -> Tuple[Optional[List[str]], List[Dict[str, object]]]:
    """
    Returns (possibly-newly-set canonical_headers, rows found on this
    page). A table whose header doesn't match an already-established
    canonical_headers is skipped (see module docstring) - checking
    continues over this page's remaining tables rather than aborting.
    """
    page_rows: List[Dict[str, object]] = []

    for table in page.extract_tables():
        if not table or len(table) < _MIN_TABLE_ROWS:
            continue
        header_row = _clean_header_row(table[0])
        if not any(header_row):
            continue
        if canonical_headers is None:
            canonical_headers = header_row
        elif not _headers_match(header_row, canonical_headers):
            continue

        page_rows.extend(_rows_from_table(table, canonical_headers))

    return canonical_headers, page_rows


def read_pdf_file(file_path: str) -> Tuple[List[str], List[Dict[str, object]]]:
    canonical_headers: Optional[List[str]] = None
    structured_rows: List[Dict[str, object]] = []
    fallback_rows: List[Dict[str, object]] = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            canonical_headers, page_rows = _process_page_tables(page, canonical_headers)
            if page_rows:
                structured_rows.extend(page_rows)
                continue

            text = page.extract_text() or ""
            if text.strip():
                fallback_rows.append({PAGE_TEXT_HEADER: text})

    if structured_rows:
        return canonical_headers, structured_rows
    return [PAGE_TEXT_HEADER], fallback_rows
