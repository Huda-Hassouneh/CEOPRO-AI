"""
Live-DB regression test for extraction.py::_register_pdf_as_rag_document() -
the real gap found live in a full customer-acceptance test: a PDF uploaded
through /extraction/upload only ever went through the tabular-extraction
pipeline, never reached rag_documents_metadata, so it was never available
to the RAG Assistant chatbot no matter what the PDF actually said.

Same convention as test_extraction_upload_pool_lifecycle_db.py: calls
extraction.extraction_upload() directly (bypassing FastAPI's dependency
injection) against a real Postgres instance. The embedding/chunking step
itself (rag.pipeline.ingest_pending_documents()'s own real work) is
monkeypatched to a fast stand-in rather than exercised for real - it
needs a real embedding model download, which test_rag_integration.py's
own AI_TEST_EMBEDDINGS-gated tests already own; this file is about
whether the right MinIO object + rag_documents_metadata row get created
and whether the endpoint reports and degrades correctly, not about
whether a real transformer model can be downloaded in CI.

Skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD are both set.
"""
import io
import os
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.core.security import TenantContext
from src.ai.rag import data_access as rag_data_access
from src.ai.routers import extraction

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB RAG-upload integration test",
)


def _app_database_url() -> str:
    parsed = urlparse(ADMIN_DATABASE_URL)
    netloc = f"ceopro_app:{APP_DB_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


# Hand-built minimal single-page PDF (catalog -> page tree -> one page
# with a content stream) rather than generating one with reportlab -
# reportlab is not one of this project's actual pinned dependencies (it
# was only ever available ambiently in the dev sandbox this test was
# first written in, not in CI - confirmed live via a real GitHub Actions
# failure: ModuleNotFoundError: No module named 'reportlab'). pdfplumber,
# which both this test and the endpoint's own tabular-extraction fallback
# already depend on, opens and extracts text from this fine.
def _make_pdf_bytes(text: str) -> bytes:
    content_stream = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("latin-1")
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << >> >>
endobj
4 0 obj
<< /Length """ + str(len(content_stream)).encode("ascii") + b""" >>
stream
""" + content_stream + b"""
endstream
endobj
xref
0 5
0000000000 65535 f
trailer
<< /Size 5 /Root 1 0 R >>
startxref
0
%%EOF"""


class _FakeUploadFile:
    def __init__(self, filename, content: bytes):
        self.filename = filename
        self.file = io.BytesIO(content)


class _FakeMinioClient:
    """Records put_object calls instead of touching a real MinIO - same
    role test_extraction_ingestion_pipeline.py's MagicMock(minio_client)
    plays for the tabular-extraction tests, just a hand-written stand-in
    here since we also need deterministic bucket/key assertions."""

    def __init__(self):
        self.put_calls = []
        self.buckets = set()  # a fresh MinIO: no buckets yet

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.buckets.add(bucket)

    def put_object(self, bucket, object_key, data, length=None, content_type=None):
        if bucket not in self.buckets:
            raise RuntimeError(f"NoSuchBucket: {bucket}")  # what real MinIO does
        self.put_calls.append({"bucket": bucket, "object_key": object_key, "content_type": content_type})


@pytest.fixture
def tenant():
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    cursor = admin.cursor()
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
        "VALUES (%s, 'RAG Upload Test Co', 'JO', 'JOD');",
        (tenant_id,),
    )
    cursor.execute(
        "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'Test User');",
        (user_id, f"{user_id}@example.com"),
    )
    cursor.execute("SELECT role_key FROM system_roles LIMIT 1;")
    row = cursor.fetchone()
    role_key = row[0] if row else "OWNER"
    if not row:
        cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES ('OWNER', 'Owner');")
    cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role_key))
    admin.close()
    return tenant_id, user_id


def _rag_documents_for(tenant_id):
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute(
            "SELECT file_name, storage_bucket_path, content_type, processed_status "
            "FROM rag_documents_metadata WHERE tenant_id = %s;",
            (tenant_id,),
        )
        rows = cursor.fetchall()
    admin.close()
    return rows


def test_pdf_upload_registers_and_ingests_a_real_rag_document(tenant, monkeypatch):
    tenant_id, user_id = tenant
    fake_minio = _FakeMinioClient()
    monkeypatch.setattr(extraction.db, "minio_client", lambda: fake_minio)

    def _fast_ingest(conn, minio_client, tid):
        docs = rag_data_access.list_documents(conn, tid, status="Pending")
        for doc in docs:
            rag_data_access.mark_document_status(conn, doc["document_id"], "Processed")
        conn.commit()
        return len(docs)

    monkeypatch.setattr(extraction.rag_pipeline, "ingest_pending_documents", _fast_ingest)

    ctx = TenantContext(tenant_id, user_id)
    file = _FakeUploadFile("company_overview.pdf", _make_pdf_bytes("Our best-seller is Widget Pro."))
    response = extraction.extraction_upload(file=file, ctx=ctx)

    assert response["rag_document_status"] == "Processed"
    assert len(fake_minio.put_calls) == 1
    assert fake_minio.put_calls[0]["bucket"] == extraction.rag_pipeline.DEFAULT_BUCKET
    # Created on first use - it used to be assumed to exist (NoSuchBucket on a fresh deployment).
    assert extraction.rag_pipeline.DEFAULT_BUCKET in fake_minio.buckets
    assert fake_minio.put_calls[0]["object_key"].startswith(f"uploads/{response['job_id']}")

    rows = _rag_documents_for(tenant_id)
    assert len(rows) == 1
    file_name, storage_bucket_path, content_type, processed_status = rows[0]
    assert file_name == "company_overview.pdf"
    assert storage_bucket_path == fake_minio.put_calls[0]["object_key"]
    assert content_type == "application/pdf"
    assert processed_status == "Processed"


def test_pdf_upload_still_succeeds_when_rag_ingestion_fails(tenant, monkeypatch):
    """The products/inventory/sales side of the upload (already committed
    before this step runs) must never be undone by a RAG-specific
    failure - same best-effort isolation as the optional MinIO
    extraction-results upload already has."""
    tenant_id, user_id = tenant
    fake_minio = _FakeMinioClient()
    monkeypatch.setattr(extraction.db, "minio_client", lambda: fake_minio)

    def _failing_ingest(conn, minio_client, tid):
        raise ConnectionError("embedding model unreachable")

    monkeypatch.setattr(extraction.rag_pipeline, "ingest_pending_documents", _failing_ingest)

    ctx = TenantContext(tenant_id, user_id)
    file = _FakeUploadFile("company_overview.pdf", _make_pdf_bytes("Our best-seller is Widget Pro."))
    response = extraction.extraction_upload(file=file, ctx=ctx)

    assert response["rag_document_status"] == "Failed"
    rows = _rag_documents_for(tenant_id)
    assert len(rows) == 1
    assert rows[0][3] in ("Pending", "Failed")  # row survives; never silently dropped (spec S12)


def test_csv_upload_does_not_touch_rag_documents_at_all(tenant, monkeypatch):
    """Only PDF is wired into RAG registration - a CSV sales-history
    import must behave exactly as before this change."""
    tenant_id, user_id = tenant
    fake_minio = _FakeMinioClient()
    monkeypatch.setattr(extraction.db, "minio_client", lambda: fake_minio)
    called = []
    monkeypatch.setattr(
        extraction.rag_pipeline, "ingest_pending_documents",
        lambda *a, **k: called.append(1),
    )

    ctx = TenantContext(tenant_id, user_id)
    csv_bytes = b"product_name,quantity,unit_price,currency,transaction_date\nWidget,1,10.00,JOD,2026-09-27\n"
    file = _FakeUploadFile("sales.csv", csv_bytes)
    response = extraction.extraction_upload(file=file, ctx=ctx)

    assert response["rag_document_status"] is None
    assert called == []
    assert fake_minio.put_calls == []
    assert _rag_documents_for(tenant_id) == []
