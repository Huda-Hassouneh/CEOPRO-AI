"""
Offline tests for src/ai/rag/data_access.py's PDF/DOCX extraction
(PENDING_ACTIONS.md #15) - pure functions over real bytes built in-memory,
no MinIO needed. The live-MinIO round-trip through fetch_document_text()
itself is covered separately in test_rag_integration.py.
"""

import io

import pytest
from docx import Document as DocxDocument
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.ai.rag.data_access import _extract_docx_text, _extract_pdf_text, fetch_document_text


def _build_pdf_bytes(text: str) -> bytes:
    """A minimal real PDF with one page and a genuinely extractable text stream."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)

    content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("latin-1")
    stream_obj = DecodedStreamObject()
    stream_obj.set_data(content)
    stream_ref = writer._add_object(stream_obj)
    page[NameObject("/Contents")] = stream_ref

    font_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font_dict)
    resources = DictionaryObject()
    font_resources = DictionaryObject()
    font_resources[NameObject("/F1")] = font_ref
    resources[NameObject("/Font")] = font_resources
    page[NameObject("/Resources")] = resources

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _build_docx_bytes(paragraphs: list) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_extract_pdf_text_returns_real_content():
    pdf_bytes = _build_pdf_bytes("Sunscreen SPF 50 supplier invoice")
    text = _extract_pdf_text(pdf_bytes)
    assert "Sunscreen SPF 50 supplier invoice" in text


def test_extract_docx_text_joins_paragraphs():
    docx_bytes = _build_docx_bytes(["First paragraph.", "Second paragraph."])
    text = _extract_docx_text(docx_bytes)
    assert "First paragraph." in text
    assert "Second paragraph." in text
    assert text.index("First paragraph.") < text.index("Second paragraph.")


def test_extract_pdf_text_raises_on_corrupt_bytes():
    """Extraction failures must propagate (not be swallowed here) - rag/pipeline.py's
    ingest_pending_documents() is what catches this and marks the document Failed."""
    with pytest.raises(Exception):
        _extract_pdf_text(b"this is not a real pdf file")


class _FakeMinioResponse:
    def __init__(self, data: bytes):
        self._data = data
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self._data

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class _FakeMinioClient:
    def __init__(self, data: bytes):
        self._data = data
        self.response = None

    def get_object(self, bucket, object_key):
        self.response = _FakeMinioResponse(self._data)
        return self.response


def test_fetch_document_text_routes_pdf_extension_to_pdf_extractor():
    pdf_bytes = _build_pdf_bytes("routed via extension")
    client = _FakeMinioClient(pdf_bytes)

    text = fetch_document_text(client, "bucket", "tenant_x/docs/supplier_notes.PDF")

    assert "routed via extension" in text
    assert client.response.closed is True
    assert client.response.released is True


def test_fetch_document_text_routes_docx_extension_to_docx_extractor():
    docx_bytes = _build_docx_bytes(["routed via extension too"])
    client = _FakeMinioClient(docx_bytes)

    text = fetch_document_text(client, "bucket", "tenant_x/docs/contract.docx")

    assert "routed via extension too" in text


def test_fetch_document_text_defaults_to_plain_text_decoding():
    client = _FakeMinioClient("plain text content, still supported".encode("utf-8"))

    text = fetch_document_text(client, "bucket", "tenant_x/docs/notes.txt")

    assert text == "plain text content, still supported"
