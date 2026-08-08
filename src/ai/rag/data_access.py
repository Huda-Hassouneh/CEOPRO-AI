"""
CEOPRO AI - RAG Document Data Access.
Reads/updates rag_documents_metadata (existing table, no schema change) and
fetches raw object bytes from MinIO's ceopro-rag-knowledge bucket (per
MINIO_STORAGE_ARCHITECTURE.md - this bucket is already AI-owned).

Handles plain text (.txt), PDF (.pdf), and Word (.docx) documents -
MINIO_STORAGE_ARCHITECTURE.md explicitly expects "supplier PDFs, business
text files" in this bucket. File type is detected from the object key's own
extension, not sniffed from content - matches how the bucket's own path
convention already encodes the file type. Extraction failures (corrupted
file, encrypted PDF, unsupported extension) are allowed to raise -
rag/pipeline.py's ingest_pending_documents() already catches any exception
from this function and marks the document "Failed" rather than silently
discarding it (spec S12), so this module doesn't need its own try/except.
"""

import io
from typing import List

import pypdf
from docx import Document as DocxDocument


def list_documents(conn, tenant_id: str, status: str = None) -> List[dict]:
    query = """
        SELECT document_id, file_name, minio_object_key, processed_status
        FROM rag_documents_metadata
        WHERE tenant_id = %s
    """
    params = [tenant_id]
    if status is not None:
        query += " AND processed_status = %s"
        params.append(status)
    query += " ORDER BY uploaded_at;"

    with conn.cursor() as cursor:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

    return [
        {"document_id": str(row[0]), "file_name": row[1], "minio_object_key": row[2], "processed_status": row[3]}
        for row in rows
    ]


def mark_document_status(conn, document_id: str, status: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE rag_documents_metadata SET processed_status = %s WHERE document_id = %s;",
            (status, document_id),
        )


def _extract_pdf_text(raw_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx_text(raw_bytes: bytes) -> str:
    document = DocxDocument(io.BytesIO(raw_bytes))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def fetch_document_text(minio_client, bucket: str, object_key: str) -> str:
    """Fetches an object from MinIO and extracts its text - .pdf/.docx/.txt (default)."""
    response = minio_client.get_object(bucket, object_key)
    try:
        raw_bytes = response.read()
    finally:
        response.close()
        response.release_conn()

    lower_key = object_key.lower()
    if lower_key.endswith(".pdf"):
        return _extract_pdf_text(raw_bytes)
    if lower_key.endswith(".docx"):
        return _extract_docx_text(raw_bytes)
    return raw_bytes.decode("utf-8")
