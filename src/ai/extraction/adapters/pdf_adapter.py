"""
CEOPRO AI - PDF Source Adapter.
PDFs have no reliable column structure, so this extracts text per page
and hands each page to the pipeline as a single-column row. The header
["page_text"] matches no FIELD_PARSERS synonym, so the file automatically
routes to FALLBACK mode - no special-casing needed elsewhere.
Requires pdfplumber (pip install pdfplumber).
"""
from typing import Dict, List, Tuple

import pdfplumber

PAGE_TEXT_HEADER = "page_text"


def read_pdf_file(file_path: str) -> Tuple[List[str], List[Dict[str, object]]]:
    rows: List[Dict[str, object]] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                rows.append({PAGE_TEXT_HEADER: text})
    return [PAGE_TEXT_HEADER], rows
