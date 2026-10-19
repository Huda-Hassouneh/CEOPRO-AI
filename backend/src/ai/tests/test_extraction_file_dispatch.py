"""
Unit tests for file_dispatch.py - spec S12's "Receive a file. Detect file
type." step. Before this module existed, none of the 5 extraction/adapters/
files had any caller anywhere in the repo - a real uploaded file had no
path into the ingestion pipeline at all, despite every individual adapter
being built and correct in isolation.
"""
import os
import tempfile

import pytest

from src.ai.extraction.file_dispatch import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFileTypeError,
    detect_file_type,
    read_source_file,
)


def _write_temp_file(suffix: str, content: str = "") -> str:
    path = os.path.join(tempfile.gettempdir(), f"file_dispatch_test{suffix}")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(content)
    return path


def test_detect_file_type_recognizes_supported_extensions():
    assert detect_file_type("invoice.csv") == ".csv"
    assert detect_file_type("invoice.CSV") == ".csv"  # case-insensitive
    assert detect_file_type("invoice.xlsx") == ".xlsx"
    assert detect_file_type("invoice.pdf") == ".pdf"


def test_detect_file_type_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type("invoice.docx")


def test_detect_file_type_rejects_no_extension():
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type("invoice")


def test_read_source_file_dispatches_csv_to_csv_adapter():
    path = _write_temp_file(".csv", "product_name,quantity\nWidget,5\n")
    headers, rows = read_source_file(path)
    assert headers == ["product_name", "quantity"]
    assert rows == [{"product_name": "Widget", "quantity": "5"}]


def test_read_source_file_raises_for_unsupported_type_before_touching_any_adapter():
    with pytest.raises(UnsupportedFileTypeError):
        read_source_file("report.docx")


def test_supported_extensions_all_have_a_working_dispatch_path():
    """Every extension SUPPORTED_EXTENSIONS advertises must actually be
    reachable in read_source_file()'s if/elif chain - guards against the
    two lists silently drifting apart."""
    for ext in SUPPORTED_EXTENSIONS:
        # xlsm and xlsx share the xlsx branch, csv/pdf have their own -
        # just confirm dispatch doesn't fall through to the "no adapter
        # wired" defensive branch for any advertised extension.
        try:
            read_source_file(f"nonexistent{ext}")
        except UnsupportedFileTypeError:
            pytest.fail(f"{ext} is in SUPPORTED_EXTENSIONS but has no dispatch branch")
        except (FileNotFoundError, OSError):
            pass  # expected - the file doesn't exist, dispatch itself worked
