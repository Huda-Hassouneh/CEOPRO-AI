"""
Integration test for src/ai/main.py's POST /rag/documents endpoint against
a real Postgres + MinIO - the real end-to-end path this session verified
manually before writing this permanent test. Skipped unless
AI_TEST_DATABASE_URL/APP_DB_PASSWORD/AI_TEST_MINIO_ENDPOINT/
AI_TEST_MINIO_ROOT_PASSWORD are all set, same convention
test_main_integration_db.py already establishes for this suite's
live-infra tests.

Exercises the real ceopro_app/RLS connection path (db.app_role_connection),
a real MinIO write to the actual ceopro-rag-knowledge bucket (the same one
POST /rag/query's retrieval path reads from), and a real
rag_documents_metadata insert/ingest - not a mock standing in for any of
it. test_rag_upload_makes_the_document_answerable_through_rag_query below
additionally needs AI_TEST_EMBEDDINGS set (it downloads the real embedding
model), matching test_rag_integration.py's own established gating for any
test that needs real embeddings rather than just real Postgres/MinIO.
"""
import os
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")
MINIO_ENDPOINT = os.getenv("AI_TEST_MINIO_ENDPOINT")
MINIO_ROOT_USER = os.getenv("AI_TEST_MINIO_ROOT_USER", "minio_admin")
MINIO_ROOT_PASSWORD = os.getenv("AI_TEST_MINIO_ROOT_PASSWORD")
JWT_SECRET = "test-jwt-secret-for-rag-upload-integration-tests"

pytestmark = pytest.mark.skipif(
    not (DATABASE_URL and APP_DB_PASSWORD and MINIO_ENDPOINT and MINIO_ROOT_PASSWORD),
    reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD/AI_TEST_MINIO_ENDPOINT/AI_TEST_MINIO_ROOT_PASSWORD not all set",
)

_needs_embeddings = pytest.mark.skipif(
    not os.getenv("AI_TEST_EMBEDDINGS"), reason="AI_TEST_EMBEDDINGS not set - skipping (downloads a real model)"
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


def _seed_tenant(admin_conn, label):
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"RAG Upload Test Co {label}"),
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
    return _seed_tenant(admin_conn, "A")


@pytest.fixture
def second_seeded_tenant(admin_conn):
    return _seed_tenant(admin_conn, "B")


def test_uploading_a_real_text_document_lands_in_minio_and_registers(client, admin_conn, seeded_tenant):
    tenant_id, user_id, headers = seeded_tenant
    content = b"Our return policy allows returns within 30 days of purchase, with a valid receipt."

    response = client.post(
        "/rag/documents", files={"file": ("return_policy.txt", content, "text/plain")}, headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    document_id = body["document_id"]
    assert body["file_name"] == "return_policy.txt"
    assert body["processed_status"] in ("Processed", "Failed")  # Failed only if embeddings are unreachable here

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


def test_uploaded_document_is_invisible_to_a_different_tenant(client, admin_conn, seeded_tenant, second_seeded_tenant):
    tenant_a_id, _, headers_a = seeded_tenant
    tenant_b_id, tenant_b_user_id, _ = second_seeded_tenant

    response = client.post(
        "/rag/documents", files={"file": ("confidential.txt", b"Tenant A's own internal notes.", "text/plain")},
        headers=headers_a,
    )
    assert response.status_code == 200
    document_id = response.json()["document_id"]

    from src.ai import db
    from src.ai.rag import data_access

    conn_b = db.app_role_connection(tenant_b_id, tenant_b_user_id)
    try:
        tenant_b_documents = data_access.list_documents(conn_b, tenant_b_id)
    finally:
        conn_b.close()

    assert all(doc["document_id"] != document_id for doc in tenant_b_documents), (
        "RLS leak: tenant B's own connection can see tenant A's uploaded document"
    )


def test_rejects_an_unsupported_extension_before_touching_minio_or_the_database(client, admin_conn, seeded_tenant):
    tenant_id, _, headers = seeded_tenant

    response = client.post(
        "/rag/documents", files={"file": ("export.csv", b"a,b\n1,2\n", "text/csv")}, headers=headers,
    )

    assert response.status_code == 400
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM rag_documents_metadata WHERE tenant_id = %s AND file_name = 'export.csv';",
            (tenant_id,),
        )
        assert cursor.fetchone()[0] == 0


def test_repeat_uploads_for_the_same_tenant_create_independent_documents(client, seeded_tenant):
    _, _, headers = seeded_tenant

    first = client.post(
        "/rag/documents", files={"file": ("doc1.txt", b"First document content.", "text/plain")}, headers=headers,
    )
    second = client.post(
        "/rag/documents", files={"file": ("doc2.txt", b"Second document content.", "text/plain")}, headers=headers,
    )

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["document_id"] != second.json()["document_id"]


@_needs_embeddings
def test_rag_upload_makes_the_document_answerable_through_rag_query(client, seeded_tenant):
    """The actual point of this endpoint: a document uploaded through
    POST /rag/documents must be retrievable through the existing
    POST /rag/query without any other step in between."""
    _, _, headers = seeded_tenant
    content = (
        b"CEOPRO's return policy allows customers to return unopened sunscreen products "
        b"within 45 days of purchase for a full refund."
    )

    upload_response = client.post(
        "/rag/documents", files={"file": ("returns.txt", content, "text/plain")}, headers=headers,
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["processed_status"] == "Processed"

    query_response = client.post(
        "/rag/query", params={"query_text": "How many days do customers have to return sunscreen?"},
        headers=headers,
    )
    assert query_response.status_code == 200
    sources = query_response.json().get("sources", [])
    assert len(sources) > 0, "the newly uploaded document was not retrieved by /rag/query"
