"""
Offline tests for data_access.py's pure logic: the pgvector text-literal
helpers, and fetch_document_text()'s extension-based extraction dispatch
(2026-09-01 - PDF/DOCX/XLSX support). No psycopg2 adapter is used for the
`vector` type (see the module docstring), so the literal round-trip
(Python array -> Postgres literal -> Python array) is the actual mechanism
the persistence fix (audit finding P1) depends on being correct.
DB-touching functions (replace_document_chunks, load_tenant_chunks,
list_documents) are covered by test_rag_integration.py's live-DB tests
instead - these tests only need a fake MinIO client, no real Postgres.

PDF extraction is tested against a mocked pdfplumber.open(), matching
test_extraction_adapters.py's established convention (no PDF-writing
library is a project dependency, so a real PDF can't be generated in-test)
- this tests fetch_document_text()'s own dispatch logic, not pdfplumber's
extraction correctness, which isn't this project's code. DOCX and XLSX
extraction are each tested against a real, in-memory file generated with
python-docx/openpyxl themselves (both are writers as well as readers),
which PDF has no equivalent for - more rigorous where the tooling allows it.
"""

import io

import numpy as np
import pytest

from unittest.mock import MagicMock

import src.ai.rag.data_access as data_access_module
from src.ai.rag.data_access import (
    UnsupportedDocumentTypeError,
    _from_pgvector_literal,
    _to_pgvector_literal,
    fetch_document_text,
    get_document_processed_status,
    register_document_upload,
    validate_document_extension,
)


def test_round_trips_a_realistic_384_dim_embedding():
    original = np.random.RandomState(42).normal(size=384).astype(np.float32)
    literal = _to_pgvector_literal(original)
    restored = _from_pgvector_literal(literal)

    assert restored.shape == original.shape
    np.testing.assert_allclose(restored, original, rtol=1e-5)


def test_literal_format_matches_pgvector_bracket_syntax():
    literal = _to_pgvector_literal(np.array([0.1, -0.2, 0.3], dtype=np.float32))
    assert literal.startswith("[")
    assert literal.endswith("]")
    assert literal.count(",") == 2  # 3 values -> 2 separators


def test_negative_and_zero_values_round_trip_correctly():
    original = np.array([0.0, -1.5, 1.5], dtype=np.float32)
    restored = _from_pgvector_literal(_to_pgvector_literal(original))
    np.testing.assert_allclose(restored, original, rtol=1e-6)


class _FakeMinioResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass

    def release_conn(self):
        pass


class _FakeMinioClient:
    def __init__(self, data: bytes):
        self._data = data

    def get_object(self, bucket, object_key):
        return _FakeMinioResponse(self._data)


def test_fetch_document_text_reads_plain_txt():
    client = _FakeMinioClient("Sunscreen SPF 50 is our best seller.".encode("utf-8"))
    assert fetch_document_text(client, "bucket", "policy.txt") == "Sunscreen SPF 50 is our best seller."


def test_fetch_document_text_reads_markdown_as_plain_text():
    client = _FakeMinioClient("# Policy\nReturns within 30 days.".encode("utf-8"))
    assert fetch_document_text(client, "bucket", "policy.md") == "# Policy\nReturns within 30 days."


def test_fetch_document_text_raises_for_an_unsupported_extension():
    client = _FakeMinioClient(b"whatever bytes")
    with pytest.raises(UnsupportedDocumentTypeError, match="\\.pptx"):
        fetch_document_text(client, "bucket", "slides.pptx")


def test_fetch_document_text_raises_for_no_extension_at_all():
    client = _FakeMinioClient(b"whatever bytes")
    with pytest.raises(UnsupportedDocumentTypeError, match="no extension"):
        fetch_document_text(client, "bucket", "README")


class _FakePdfPage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_document_text_extracts_pdf_text_per_page(monkeypatch):
    """Mocks pdfplumber.open() - see this file's own module docstring for why."""
    pages = [_FakePdfPage("Page one content."), _FakePdfPage("Page two content.")]
    monkeypatch.setattr(data_access_module.pdfplumber, "open", lambda file_obj: _FakePdf(pages))

    client = _FakeMinioClient(b"%PDF-1.4 fake pdf bytes")
    text = fetch_document_text(client, "bucket", "policy.pdf")

    assert "Page one content." in text
    assert "Page two content." in text


def test_fetch_document_text_skips_pdf_pages_with_no_extractable_text(monkeypatch):
    """A scanned/image-only page returns None from extract_text() - must be
    dropped, not turned into a literal "None" string in the joined output."""
    pages = [_FakePdfPage("Real content."), _FakePdfPage(None)]
    monkeypatch.setattr(data_access_module.pdfplumber, "open", lambda file_obj: _FakePdf(pages))

    client = _FakeMinioClient(b"%PDF-1.4 fake pdf bytes")
    text = fetch_document_text(client, "bucket", "policy.pdf")

    assert text == "Real content."


def test_fetch_document_text_extracts_docx_paragraphs():
    """Real .docx, generated in-memory with python-docx itself (a writer as
    well as a reader) - no mocking needed, unlike the PDF case above."""
    import docx

    document = docx.Document()
    document.add_paragraph("Our return policy allows returns within 30 days.")
    document.add_paragraph("Sunscreen SPF 50 is our best selling product.")
    buffer = io.BytesIO()
    document.save(buffer)

    client = _FakeMinioClient(buffer.getvalue())
    text = fetch_document_text(client, "bucket", "policy.docx")

    assert "Our return policy allows returns within 30 days." in text
    assert "Sunscreen SPF 50 is our best selling product." in text


def test_fetch_document_text_skips_empty_docx_paragraphs():
    import docx

    document = docx.Document()
    document.add_paragraph("Real content.")
    document.add_paragraph("")  # a blank line in the source document
    document.add_paragraph("   ")  # whitespace-only
    buffer = io.BytesIO()
    document.save(buffer)

    client = _FakeMinioClient(buffer.getvalue())
    text = fetch_document_text(client, "bucket", "policy.docx")

    assert text == "Real content."


def test_fetch_document_text_extracts_xlsx_rows_tab_separated():
    """Real .xlsx, generated in-memory with openpyxl itself - no mocking
    needed, same reasoning as the DOCX tests above."""
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["Product", "Price", "Currency"])
    sheet.append(["Premium Olive Oil 1L", 24.5, "JOD"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    client = _FakeMinioClient(buffer.getvalue())
    text = fetch_document_text(client, "bucket", "catalog.xlsx")

    assert "Sheet: Products" in text
    assert "Product\tPrice\tCurrency" in text
    assert "Premium Olive Oil 1L\t24.5\tJOD" in text


def test_fetch_document_text_covers_every_sheet_in_a_multi_sheet_xlsx():
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet1 = workbook.active
    sheet1.title = "Products"
    sheet1.append(["Sunscreen SPF 50"])
    sheet2 = workbook.create_sheet("Policies")
    sheet2.append(["Returns accepted within 30 days"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    client = _FakeMinioClient(buffer.getvalue())
    text = fetch_document_text(client, "bucket", "handbook.xlsx")

    assert "Sheet: Products" in text
    assert "Sunscreen SPF 50" in text
    assert "Sheet: Policies" in text
    assert "Returns accepted within 30 days" in text


def test_fetch_document_text_skips_fully_blank_xlsx_rows_and_renders_empty_cells_as_empty():
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Notes"])
    sheet.append(["Widget A", None])  # a genuinely blank cell, not the string "None"
    sheet.append([None, None])  # a fully blank row - must be dropped, not rendered as an empty line
    buffer = io.BytesIO()
    workbook.save(buffer)

    client = _FakeMinioClient(buffer.getvalue())
    text = fetch_document_text(client, "bucket", "notes.xlsx")

    assert "None" not in text
    assert "Widget A\t" in text
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 3  # "Sheet: ..." + header row + "Widget A" row, no blank-row artifact


def test_validate_document_extension_accepts_every_supported_format():
    for ext in data_access_module.SUPPORTED_DOCUMENT_EXTENSIONS:
        assert validate_document_extension(f"file{ext}") == ext


def test_validate_document_extension_is_case_insensitive():
    assert validate_document_extension("POLICY.PDF") == ".pdf"


def test_validate_document_extension_rejects_a_tabular_import_format():
    """.csv/.xlsm are /extraction/upload's territory, not this module's -
    confirms the two endpoints' extension sets don't silently overlap."""
    with pytest.raises(UnsupportedDocumentTypeError, match="\\.csv"):
        validate_document_extension("export.csv")


def test_validate_document_extension_rejects_no_extension_at_all():
    with pytest.raises(UnsupportedDocumentTypeError, match="no extension"):
        validate_document_extension("README")


class _FakeMinioClientForUpload:
    """Records what register_document_upload() actually writes, without a
    real MinIO server - bucket_exists/make_bucket/put_object are the only
    methods that function calls."""

    def __init__(self, bucket_already_exists: bool = True):
        self.bucket_already_exists = bucket_already_exists
        self.made_bucket = None
        self.put_calls = []

    def bucket_exists(self, bucket):
        return self.bucket_already_exists

    def make_bucket(self, bucket):
        self.made_bucket = bucket

    def put_object(self, bucket, object_key, data, length, content_type=None):
        self.put_calls.append(
            {"bucket": bucket, "object_key": object_key, "data": data.read(), "length": length, "content_type": content_type}
        )


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))


class _FakeConnForUpload:
    def __init__(self):
        self.cursor_obj = _FakeCursor()

    def cursor(self):
        return self.cursor_obj


def test_register_document_upload_writes_to_the_documented_storage_path():
    minio_client = _FakeMinioClientForUpload()
    conn = _FakeConnForUpload()

    result = register_document_upload(
        conn, minio_client, "ceopro-rag-knowledge", "tenant-1", "user-1", "policy.pdf", b"%PDF-1.4 fake", ".pdf",
    )

    assert result["document_id"]
    assert result["storage_bucket_path"] == f"tenant_tenant-1/rag/{result['document_id']}.pdf"
    assert len(minio_client.put_calls) == 1
    put_call = minio_client.put_calls[0]
    assert put_call["bucket"] == "ceopro-rag-knowledge"
    assert put_call["object_key"] == result["storage_bucket_path"]
    assert put_call["data"] == b"%PDF-1.4 fake"
    assert put_call["content_type"] == "application/pdf"


def test_register_document_upload_creates_the_bucket_if_missing():
    minio_client = _FakeMinioClientForUpload(bucket_already_exists=False)
    conn = _FakeConnForUpload()

    register_document_upload(
        conn, minio_client, "ceopro-rag-knowledge", "tenant-1", "user-1", "policy.txt", b"text", ".txt",
    )

    assert minio_client.made_bucket == "ceopro-rag-knowledge"


def test_register_document_upload_inserts_a_pending_row_with_the_right_fields():
    minio_client = _FakeMinioClientForUpload()
    conn = _FakeConnForUpload()

    result = register_document_upload(
        conn, minio_client, "ceopro-rag-knowledge", "tenant-1", "user-1", "policy.txt", b"hello world", ".txt",
    )

    query, params = conn.cursor_obj.executed[0]
    assert "INSERT INTO rag_documents_metadata" in query
    assert "'Pending'" in query
    document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes, content_type, uploaded_by_user_id = params
    assert document_id == result["document_id"]
    assert tenant_id == "tenant-1"
    assert file_name == "policy.txt"
    assert storage_bucket_path == result["storage_bucket_path"]
    assert file_size_bytes == len(b"hello world")
    assert content_type == "text/plain"
    assert uploaded_by_user_id == "user-1"


def test_get_document_processed_status_returns_the_stored_status():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("Processed",)
    assert get_document_processed_status(conn, "tenant-1", "doc-1") == "Processed"


def test_get_document_processed_status_returns_none_when_no_such_document():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert get_document_processed_status(conn, "tenant-1", "missing-doc") is None
