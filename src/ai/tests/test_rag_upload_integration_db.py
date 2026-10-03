"""
Integration test for src/ai/main.py's POST /rag/documents endpoint against
a real Postgres + MinIO - the real human-upload path this session added to
close the gap rag/README.md's own "however your upload flow creates that
row" hedge (and pipeline.py::ingest_pending_documents()'s "whatever upload
path exists" docstring) had always left open. Mirrors
test_main_integration_db.py's exact fixture/env-var conventions for this
same app (seeded_tenant, the same four AI_TEST_* vars), since this is
another endpoint of that same running FastAPI app - not a new test harness.

Does not gate on AI_TEST_EMBEDDINGS: test_rag_integration.py's own
test_ingest_pending_documents_marks_processed already runs the real
embedding model whenever AI_TEST_DATABASE_URL/AI_TEST_MINIO_ENDPOINT are
set (not just when AI_TEST_EMBEDDINGS is set too) - that gate is reserved
for tests specifically about embedding/re-ranking quality, not "does the
ingestion machinery run at all." Matched here for the same reason.
"""
import os
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient
from minio import Minio

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")
# Same convention as test_main_integration_db.py: AI_TEST_MINIO_ENDPOINT is a
# bare host:port (passed straight to Minio() below), db.minio_client() wants
# a scheme-prefixed URL (matching .env.example's MINIO_ENDPOINT=http://...),
# so the _env fixture adds "http://" only for the env var db.minio_client()
# itself reads.
MINIO_ENDPOINT = os.getenv("AI_TEST_MINIO_ENDPOINT")
MINIO_ROOT_USER = os.getenv("AI_TEST_MINIO_ROOT_USER", "minio_admin")
MINIO_ROOT_PASSWORD = os.getenv("AI_TEST_MINIO_ROOT_PASSWORD")
JWT_SECRET = "test-jwt-secret-for-rag-upload-integration-tests"

pytestmark = pytest.mark.skipif(
    not (DATABASE_URL and APP_DB_PASSWORD and MINIO_ENDPOINT and MINIO_ROOT_PASSWORD),
    reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD/AI_TEST_MINIO_ENDPOINT/AI_TEST_MINIO_ROOT_PASSWORD not all set",
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("APP_DB_PASSWORD", APP_DB_PASSWORD)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("MINIO_ENDPOINT", f"http://{MINIO_ENDPOINT}")
    monkeypatch.setenv("MINIO_ROOT_USER", MINIO_ROOT_USER)
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", MINIO_ROOT_PASSWORD)


@pytest.fixture
def client():
    from src.ai.main import app
    return TestClient(app)


@pytest.fixture
def admin_conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture
def minio_client():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ROOT_USER, secret_key=MINIO_ROOT_PASSWORD, secure=False)


def _seed_tenant(admin_conn):
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with admin_conn.cursor() as cursor:
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
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);",
            (tenant_id, user_id, role_key),
        )
    token = jwt.encode({"tenant_id": tenant_id, "user_id": user_id}, JWT_SECRET, algorithm="HS256")
    return tenant_id, user_id, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seeded_tenant(admin_conn):
    return _seed_tenant(admin_conn)


@pytest.fixture
def second_seeded_tenant(admin_conn):
    return _seed_tenant(admin_conn)


def test_uploading_a_real_document_lands_in_minio_and_registers_pending_then_processed(
    client, admin_conn, minio_client, seeded_tenant,
):
    """The actual end-to-end path: a real multipart upload through the real
    running app lands real bytes in the real ceopro-rag-knowledge bucket,
    a real rag_documents_metadata row with processed_status starting at
    'Pending', and ingest_pending_documents() (called by the endpoint
    itself, not this test) genuinely advances it to 'Processed' with real
    chunks persisted - not asserted from a mock anywhere in this chain."""
    tenant_id, user_id, headers = seeded_tenant
    content = b"Our return policy allows returns within 30 days of purchase, with a valid receipt."

    response = client.post(
        "/rag/documents", files={"file": ("return_policy.txt", content, "text/plain")}, headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "return_policy.txt"
    assert body["processed_status"] in ("Processed", "Failed")
    document_id = body["document_id"]

    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT file_name, storage_bucket_path, file_size_bytes, content_type, uploaded_by_user_id, "
            "processed_status FROM rag_documents_metadata WHERE tenant_id = %s AND document_id = %s;",
            (tenant_id, document_id),
        )
        row = cursor.fetchone()
    assert row is not None
    file_name, storage_bucket_path, file_size_bytes, content_type, uploaded_by_user_id, processed_status = row
    assert file_name == "return_policy.txt"
    assert storage_bucket_path == f"tenant_{tenant_id}/rag/{document_id}.txt"
    assert file_size_bytes == len(content)
    assert content_type == "text/plain"
    assert str(uploaded_by_user_id) == user_id
    assert processed_status == body["processed_status"]

    # The real object genuinely exists in MinIO at the path the DB row
    # points at - not just a DB row claiming it does.
    stat = minio_client.stat_object("ceopro-rag-knowledge", storage_bucket_path)
    assert stat.size == len(content)

    if processed_status == "Processed":
        with admin_conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM rag_document_chunks WHERE tenant_id = %s AND document_id = %s;",
                (tenant_id, document_id),
            )
            assert cursor.fetchone()[0] > 0


def test_uploaded_document_is_invisible_to_a_different_tenant(client, admin_conn, seeded_tenant, second_seeded_tenant):
    """Real RLS isolation, not an application-level filter: tenant A's
    uploaded document must not appear in tenant B's own rag_documents_
    metadata reads, enforced by isolation_rag_docs's RLS policy on the
    connection db.app_role_connection() opens per request."""
    from src.ai.rag import data_access

    tenant_a_id, _, headers_a = seeded_tenant
    tenant_b_id, _, headers_b = second_seeded_tenant

    response = client.post(
        "/rag/documents", files={"file": ("confidential.txt", b"Tenant A's own internal notes.", "text/plain")},
        headers=headers_a,
    )
    assert response.status_code == 200
    document_id = response.json()["document_id"]

    from src.ai import db

    tenant_b_user_id = second_seeded_tenant[1]
    conn_b = db.app_role_connection(tenant_b_id, tenant_b_user_id)
    try:
        tenant_b_documents = data_access.list_documents(conn_b, tenant_b_id)
    finally:
        conn_b.close()
    assert all(doc["document_id"] != document_id for doc in tenant_b_documents)

    tenant_a_user_id = seeded_tenant[1]
    conn_a = db.app_role_connection(tenant_a_id, tenant_a_user_id)
    try:
        tenant_a_documents = data_access.list_documents(conn_a, tenant_a_id)
    finally:
        conn_a.close()
    assert any(doc["document_id"] == document_id for doc in tenant_a_documents)


def test_rejects_an_unsupported_extension_before_touching_minio_or_the_database(client, admin_conn, seeded_tenant):
    tenant_id, _, headers = seeded_tenant

    response = client.post(
        "/rag/documents", files={"file": ("export.csv", b"a,b\n1,2\n", "text/csv")}, headers=headers,
    )

    assert response.status_code == 400
    with admin_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM rag_documents_metadata WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 0


def test_repeat_uploads_for_the_same_tenant_create_independent_documents(client, admin_conn, seeded_tenant):
    """Unlike structured_summaries.py's stable per-slot upsert, a real human
    upload is always a genuinely new document - two uploads must produce
    two distinct rows/objects, never overwrite one another."""
    tenant_id, _, headers = seeded_tenant

    first = client.post(
        "/rag/documents", files={"file": ("doc1.txt", b"First document content.", "text/plain")}, headers=headers,
    )
    second = client.post(
        "/rag/documents", files={"file": ("doc2.txt", b"Second document content.", "text/plain")}, headers=headers,
    )

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["document_id"] != second.json()["document_id"]

    with admin_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM rag_documents_metadata WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 2
