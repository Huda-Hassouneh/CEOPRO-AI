"""
CEOPRO AI - Source File Type Detection & Dispatch.
Spec S12's Universal Import Engine requires the pipeline to "Receive a
file. Detect file type." - this is that step. Before this file, all 5
adapters in extraction/adapters/ existed with no caller anywhere in the
repo: nothing decided which adapter a given uploaded file should go
through, so a real upload had no path into the pipeline at all despite
every adapter being built and (individually) correct.

Only covers the 3 adapters that take a file path (csv/xlsx/pdf) -
db_adapter and api_adapter are invoked directly by a caller that already
holds a live connection or a fetch callback, not dispatched by file type.
"""
import os
from typing import Dict, List, Optional, Tuple

from src.ai.extraction.adapters.csv_adapter import read_csv_file
from src.ai.extraction.adapters.pdf_adapter import read_pdf_file
from src.ai.extraction.adapters.xlsx_adapter import read_xlsx_file

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".pdf"}


class UnsupportedFileTypeError(ValueError):
    """
    Raised for a file extension the Universal Import Engine doesn't have
    an adapter for. A distinct exception type (not a bare ValueError) so
    a caller building the "Report invalid records" UI can distinguish
    "we don't support this file type at all" from a row-level parse error.
    """


def detect_file_type(filename: str) -> str:
    """Returns the lowercased extension (with leading '.'), or raises
    UnsupportedFileTypeError if it's not one this engine handles."""
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or '(no extension)'}' for '{filename}' - "
            f"supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return ext


def read_source_file(
    file_path: str, sheet_name: Optional[str] = None
) -> Tuple[List[str], List[Dict[str, object]]]:
    """
    Detects the file type from its extension and dispatches to the
    matching adapter, returning the (headers, rows) shape
    ingestion_pipeline.process_file() expects either way - the caller
    doesn't need to know or care which adapter actually ran.

    sheet_name is xlsx-specific (ignored for csv/pdf) - passed through
    rather than hidden, since a multi-sheet workbook genuinely needs it
    some of the time and there's no equivalent concept in the other two
    formats to name it after instead.
    """
    ext = detect_file_type(file_path)
    if ext == ".csv":
        return read_csv_file(file_path)
    if ext in (".xlsx", ".xlsm"):
        return read_xlsx_file(file_path, sheet_name=sheet_name)
    if ext == ".pdf":
        return read_pdf_file(file_path)
    # Unreachable - detect_file_type() already validated ext is supported,
    # this is a deliberate defensive fallback if SUPPORTED_EXTENSIONS and
    # this if/elif chain ever drift out of sync with each other.
    raise UnsupportedFileTypeError(f"No adapter wired for detected extension '{ext}'")
