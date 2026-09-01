"""
CEOPRO AI - RAG Document Data Access.
Reads/updates rag_documents_metadata (existing table, no schema change) and
fetches raw object bytes from MinIO's ceopro-rag-knowledge bucket (per
MINIO_STORAGE_ARCHITECTURE.md - this bucket is already AI-owned).

fetch_document_text() dispatches by file extension: .txt/.md as plain UTF-8,
.pdf via pdfplumber (already a project dependency, extraction/adapters/
pdf_adapter.py's own library), .docx via python-docx, .xlsx via openpyxl
(also already a project dependency, extraction/adapters/xlsx_adapter.py's
own library) (2026-09-01 - a real document-based RAG system needs to read
the policy/manual/regulation/spreadsheet documents its own use case names,
not just plain text). An unsupported extension raises
UnsupportedDocumentTypeError with a clear message rather than silently
mis-decoding binary content as text - it's still caught by
ingest_pending_documents()'s existing per-document error handling and
marked 'Failed' with that message, spec S12's "never silently discard
invalid data" applied to a format gap the same way as any other failure.

Also owns rag_document_chunks persistence (text + pgvector embedding) -
audit finding P1: this table has existed, with its embedding vector(384)
column, since migration 20260827000100_add_rag_embedding_column.sql, but
no code read or wrote it - every retrieval call re-fetched every document
from MinIO, re-chunked, and re-embedded the entire corpus from scratch.
replace_document_chunks() persists chunks once, at ingest time; the
retrieval path (pipeline.py) reads them back instead of rebuilding.

No pgvector Python client dependency is added for this - psycopg2 alone is
enough: an embedding is sent as a bracketed literal cast with ::vector on
the way in, and read back as pgvector's own text representation
('[0.1,0.2,...]') on the way out, parsed by hand. One fewer dependency for
a format this simple.
"""

import io
import os
from typing import List, Optional, Tuple

import docx
import numpy as np
import openpyxl
import pdfplumber

SUPPORTED_DOCUMENT_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".xlsx"}


class UnsupportedDocumentTypeError(ValueError):
    """Raised for a file extension fetch_document_text() has no extractor for."""


def _to_pgvector_literal(embedding: np.ndarray) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def _from_pgvector_literal(value: str) -> np.ndarray:
    return np.array([float(x) for x in value.strip("[]").split(",")], dtype=np.float32)


def list_documents(conn, tenant_id: str, status: str = None) -> List[dict]:
    query = """
        SELECT document_id, file_name, storage_bucket_path, processed_status
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
        {"document_id": str(row[0]), "file_name": row[1], "storage_bucket_path": row[2], "processed_status": row[3]}
        for row in rows
    ]


def mark_document_status(conn, document_id: str, status: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE rag_documents_metadata SET processed_status = %s WHERE document_id = %s;",
            (status, document_id),
        )


def fetch_document_text(minio_client, bucket: str, object_key: str) -> str:
    """
    Fetches an object from MinIO and extracts its text content, dispatched
    by `object_key`'s file extension (see SUPPORTED_DOCUMENT_EXTENSIONS).
    Raises UnsupportedDocumentTypeError for anything else - see this
    module's own docstring for why that's a deliberate error, not a
    silent best-effort decode.
    """
    ext = os.path.splitext(object_key)[1].lower()
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise UnsupportedDocumentTypeError(
            f"Unsupported document type '{ext or '(no extension)'}' for '{object_key}' - "
            f"supported: {', '.join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))}"
        )

    response = minio_client.get_object(bucket, object_key)
    try:
        raw = response.read()
    finally:
        response.close()
        response.release_conn()

    if ext in (".txt", ".md"):
        return raw.decode("utf-8")
    if ext == ".pdf":
        return _extract_pdf_text(raw)
    if ext == ".docx":
        return _extract_docx_text(raw)
    return _extract_xlsx_text(raw)


def _extract_pdf_text(raw: bytes) -> str:
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        pages = [page.extract_text() for page in pdf.pages]
    return "\n\n".join(page for page in pages if page)


def _extract_docx_text(raw: bytes) -> str:
    document = docx.Document(io.BytesIO(raw))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_xlsx_text(raw: bytes) -> str:
    """
    Flattens every sheet into readable text: a "Sheet: <name>" heading per
    sheet, then one tab-separated line per row (blank cells rendered as
    empty, not "None" - a spreadsheet's own visual shape, not a literal
    dump of Python None values). read_only=True and data_only=True match
    extraction/adapters/xlsx_adapter.py's own convention - read the last
    computed values, not formula source text, and don't hold the whole
    workbook's object graph in memory for a large sheet.
    """
    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    sections = []
    for sheet in workbook.worksheets:
        lines = [
            "\t".join("" if cell is None else str(cell) for cell in row)
            for row in sheet.iter_rows(values_only=True)
        ]
        lines = [line for line in lines if line.strip("\t")]  # skip fully-blank rows
        if lines:
            sections.append(f"Sheet: {sheet.title}\n" + "\n".join(lines))
    return "\n\n".join(sections)


def replace_document_chunks(
    conn, tenant_id: str, document_id: str, chunks: List[str], embeddings: np.ndarray, model_version: str
) -> None:
    """
    Idempotent wipe-and-replace: deletes every existing chunk for this
    document, then inserts the freshly chunked/embedded set. Safe to call
    any number of times for the same document_id (re-ingestion after a
    re-upload, a retry after a partial failure, or a first-time ingest all
    take the same path) - there is no accumulation of stale rows, and no
    separate "is this an update or an insert" branch to get wrong.

    This only fires when ingest_pending_documents() actually processes the
    document - i.e. when its processed_status is 'Pending'. A re-uploaded
    file needs whatever writes rag_documents_metadata on upload to flip
    processed_status back to 'Pending' for its existing document_id (or
    insert a fresh document_id, in which case DELETE here is a no-op and a
    new row set is inserted) - that upload path doesn't exist in this
    module yet, so this is the half of "solve the lifecycle" this module
    owns; the other half is a prerequisite outside its boundary.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM rag_document_chunks WHERE tenant_id = %s AND document_id = %s;",
            (tenant_id, document_id),
        )
        for chunk_index, (text, embedding) in enumerate(zip(chunks, embeddings)):
            cursor.execute(
                """
                INSERT INTO rag_document_chunks
                    (tenant_id, document_id, chunk_index, chunk_text_content, embedding, embedding_model_version)
                VALUES (%s, %s, %s, %s, %s::vector, %s);
                """,
                (tenant_id, document_id, chunk_index, text, _to_pgvector_literal(embedding), model_version),
            )


def load_tenant_chunks(conn, tenant_id: str) -> List[Tuple[str, str, Optional[np.ndarray]]]:
    """Returns every persisted (chunk_id, chunk_text, embedding) row for a tenant, oldest first."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT chunk_id, chunk_text_content, embedding
            FROM rag_document_chunks
            WHERE tenant_id = %s
            ORDER BY document_id, chunk_index;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    return [
        (str(chunk_id), text, _from_pgvector_literal(embedding) if embedding is not None else None)
        for chunk_id, text, embedding in rows
    ]
