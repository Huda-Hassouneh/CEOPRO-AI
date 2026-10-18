import io
import zipfile

import pytest
from openpyxl import Workbook

from src.ai.core import office_files
from src.ai.core.office_files import InvalidOfficeFileError, ensure_safe_office_archive
from src.ai.extraction.adapters.xlsx_adapter import read_xlsx_file


def _workbook_bytes():
    wb = Workbook()
    wb.active.append(["date", "product", "qty"])
    wb.active.append(["2026-01-01", "Widget", 2])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _bomb(unpacked_mb: int) -> bytes:
    """A valid workbook whose sheet XML is padded to unpacked_mb (compresses ~1000:1)."""
    source = zipfile.ZipFile(io.BytesIO(_workbook_bytes()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b"</worksheet>", b"<!--" + b" " * (unpacked_mb * 1024 * 1024) + b"--></worksheet>")
            archive.writestr(item.filename, data)
    return out.getvalue()


def test_a_normal_workbook_passes_and_still_reads(tmp_path):
    path = tmp_path / "sales.xlsx"
    path.write_bytes(_workbook_bytes())
    ensure_safe_office_archive(str(path))
    headers, rows = read_xlsx_file(str(path))
    assert headers == ["date", "product", "qty"] and rows[0]["product"] == "Widget"


def test_a_zip_bomb_is_rejected_before_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(office_files, "MAX_OFFICE_UNPACKED_MB", 5)
    data = _bomb(8)
    assert len(data) < 1024 * 1024  # small upload, large expansion
    path = tmp_path / "bomb.xlsx"
    path.write_bytes(data)
    with pytest.raises(InvalidOfficeFileError, match="above the 5 MB limit"):
        read_xlsx_file(str(path))
    with pytest.raises(InvalidOfficeFileError):
        ensure_safe_office_archive(data)


@pytest.mark.parametrize("payload", [b"MZ\x90\x00not a zip", b""])
def test_non_zip_content_is_a_clear_invalid_file_error(payload):
    with pytest.raises(InvalidOfficeFileError, match="isn't a valid Excel or Word file"):
        ensure_safe_office_archive(payload)


def test_a_zip_without_a_workbook_is_a_clear_invalid_file_error(tmp_path):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("hello.txt", "not a workbook")
    path = tmp_path / "fake.xlsx"
    path.write_bytes(out.getvalue())
    with pytest.raises(InvalidOfficeFileError, match="couldn't be opened"):
        read_xlsx_file(str(path))
