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
import uuid
from typing import List, Optional, Tuple

import docx
import numpy as np
import openpyxl
import pdfplumber
from psycopg2.extras import execute_values

SUPPORTED_DOCUMENT_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".xlsx"}

# Server-derived, never trusted from the client's own multipart content-type
# header (the same reasoning extraction/file_dispatch.py's extension
# allowlist already applies to the filename) - one real MIME type per
# extension this module actually knows how to extract text from.
CONTENT_TYPES_BY_EXTENSION = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class UnsupportedDocumentTypeError(ValueError):
    """Raised for a file extension fetch_document_text() has no extractor for."""


def _to_pgvector_literal(embedding: np.ndarray) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def _from_pgvector_literal(value: str) -> np.ndarray:
    return np.array([float(x) for x in value.strip("[]").split(",")], dtype=np.float32)


def detect_document_type(filename: str) -> str:
    """
    Returns the lowercased extension (with leading '.'), or raises
    UnsupportedDocumentTypeError if it's not one this module can extract
    text from. Mirrors extraction/file_dispatch.py::detect_file_type()'s
    exact convention (same shape, same error message style) for this
    module's own, differently-scoped extension set - that module validates
    against SUPPORTED_EXTENSIONS (tabular import formats), this one against
    SUPPORTED_DOCUMENT_EXTENSIONS (prose/knowledge-base document formats).
    """
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise UnsupportedDocumentTypeError(
            f"Unsupported document type '{ext or '(no extension)'}' for '{filename}' - "
            f"supported: {', '.join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))}"
        )
    return ext


def register_uploaded_document(
    conn, minio_client, bucket: str, tenant_id: str, uploaded_by_user_id: str, file_name: str,
    contents: bytes, ext: str,
) -> dict:
    """
    The real human-upload half of this module's own document lifecycle -
    rag/README.md's "Ingest a document" section has always hedged this
    exact gap ("rag_documents_metadata needs a row with processed_status=
    'Pending' first - however your upload flow creates that row"), and
    pipeline.py::ingest_pending_documents()'s own docstring talks about
    "whatever upload path exists" the same way: a real caller that lands a
    human-uploaded file in MinIO and registers it never existed anywhere in
    this codebase until now. structured_summaries.py's auto-generated
    narrative documents are the only thing that has ever written a real
    rag_documents_metadata row - this is the human-upload counterpart to
    that, landing in the exact same table/bucket/pipeline, not a parallel
    mechanism.

    Storage path follows MINIO_STORAGE_ARCHITECTURE.md's own documented
    convention for this bucket (tenant_{tenant_id}/rag/{document_id}{ext}),
    generated here (not left to the DB's gen_random_uuid() default) since
    the object key the row points at has to exist before the row does -
    MinIO is written to FIRST, so a document_id is needed up front.

    Bucket creation mirrors the only other place in this codebase that has
    ever actually performed the first real write to this bucket
    (scripts/run_e2e_pipeline.py's own stage_rag_grounding()) - a plain
    bucket_exists()/make_bucket() - since nothing else in the repo
    provisions ceopro-rag-knowledge ahead of time.

    Returns {"document_id", "storage_bucket_path"} - the registered row's
    identity, for the caller (main.py's endpoint) to look up the
    processed_status ingest_pending_documents() leaves it in afterward.
    Does not call ingest_pending_documents() itself - that stays the
    caller's responsibility, keeping this function's job limited to
    "land the file + register it," the same boundary list_documents()/
    mark_document_status() already keep (reads/writes rag_documents_
    metadata; pipeline.py owns ingestion).
    """
    document_id = str(uuid.uuid4())
    object_key = f"tenant_{tenant_id}/rag/{document_id}{ext}"
    content_type = CONTENT_TYPES_BY_EXTENSION[ext]

    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)
    minio_client.put_object(
        bucket, object_key, io.BytesIO(contents), length=len(contents), content_type=content_type,
    )

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO rag_documents_metadata
                (document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes,
                 content_type, uploaded_by_user_id, processed_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending');
            """,
            (document_id, tenant_id, file_name, object_key, len(contents), content_type, uploaded_by_user_id),
        )

    return {"document_id": document_id, "storage_bucket_path": object_key}


def get_document_status(conn, tenant_id: str, document_id: str) -> Optional[str]:
    """Returns this document's current processed_status (Pending/Processed/
    Failed), or None if it doesn't exist for this tenant - used right after
    ingest_pending_documents() runs to report the real outcome of one
    specific document's ingestion, not just the tenant-wide processed count
    that function itself returns."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT processed_status FROM rag_documents_metadata WHERE tenant_id = %s AND document_id = %s;",
            (tenant_id, document_id),
        )
        row = cursor.fetchone()
    return row[0] if row else None


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
    values = [
        (tenant_id, document_id, chunk_index, text, _to_pgvector_literal(embedding), model_version)
        for chunk_index, (text, embedding) in enumerate(zip(chunks, embeddings))
    ]
    with conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM rag_document_chunks WHERE tenant_id = %s AND document_id = %s;",
            (tenant_id, document_id),
        )
        if values:
            # One multi-row INSERT instead of one round trip per chunk -
            # a real N+1 for any document long enough to produce hundreds
            # of chunks (chunking.py). Mirrors the same execute_values()
            # pattern src/ai/extraction/ingestion_pipeline.py/promotion.py
            # already use for their own bulk inserts.
            execute_values(
                cursor,
                """
                INSERT INTO rag_document_chunks
                    (tenant_id, document_id, chunk_index, chunk_text_content, embedding, embedding_model_version)
                VALUES %s;
                """,
                values,
                template="(%s, %s, %s, %s, %s::vector, %s)",
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
