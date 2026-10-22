"""Authenticated RAG document upload against PostgreSQL and real MinIO.

This proves Knowledge Base uploads use only the RAG object/index path and
are not routed through structured business-data ingestion or promotion.
"""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.core import entitlements
from src.ai.rag import pipeline
from src.ai.tests.signup_helpers import create_verified_test_account

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
MINIO_READY = all(os.getenv(key) for key in ("MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"))
pytestmark = [
    pytest.mark.skipif(not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                       reason="disposable PostgreSQL and ceopro_app role are required"),
    pytest.mark.skipif(not MINIO_READY, reason="disposable MinIO is required"),
]


def _admin(sql, params=()):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall() if cursor.description else None
        conn.commit()
        return rows
    finally:
        conn.close()


@pytest.fixture
def client():
    from src.ai.main import app

    return TestClient(app)


def test_authenticated_upload_is_rag_only_searchable_and_idempotent(client, monkeypatch):
    monkeypatch.setattr(pipeline, "try_embed", lambda chunks: None)
    from src.ai.core import usage
    original_reserve = usage.reserve
    reservations = []
    def _reserve(*args, **kwargs):
        value = original_reserve(*args, **kwargs)
        reservations.append(value)
        return value
    monkeypatch.setattr(usage, "reserve", _reserve)
    email = f"rag-upload+{uuid.uuid4().hex[:10]}@example.com"
    session = create_verified_test_account(client, {
        "full_name": "RAG Owner", "business_name": "RAG Upload Test", "email": email,
        "country_code": "JO", "primary_currency": "JOD", "password": "Rag!Upload-2026",
    })
    tenant_id = session["tenant_id"]
    user_id = session["user_id"]
    _admin("UPDATE tenant_plan_assignments SET plan_key='growth',status='active',source='manual' WHERE tenant_id=%s;",
           (tenant_id,))
    entitlements.forget(tenant_id)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    payload = ("Returns are accepted within thirty calendar days when the product is unused. "
               "Contact the service desk with the original order reference.").encode()

    response = client.post("/rag/documents/upload", files={"file": ("returns-policy.txt", payload, "text/plain")},
                           headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready" and body["searchable"] is True and body["duplicate"] is False

    documents = client.get("/rag/documents", headers=headers)
    assert documents.status_code == 200
    doc = next(item for item in documents.json()["documents"] if item["document_id"] == body["document_id"])
    assert doc["searchable"] is True and doc["chunk_count"] > 0

    # Replaying the same bytes resolves to the existing source document and
    # does not increment document-processing usage or stored byte count.
    replay = client.post("/rag/documents/upload", files={"file": ("different-display-name.txt", payload, "text/plain")},
                         headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["document_id"] == body["document_id"]
    assert replay.json()["duplicate"] is True

    counts = _admin(
        "SELECT (SELECT COUNT(*) FROM rag_documents_metadata WHERE tenant_id=%s AND document_id=%s), "
        "(SELECT COUNT(*) FROM ingestion_jobs WHERE tenant_id=%s), "
        "(SELECT COUNT(*) FROM products WHERE tenant_id=%s), "
        "(SELECT COUNT(*) FROM invoices WHERE tenant_id=%s);",
        (tenant_id, body["document_id"], tenant_id, tenant_id, tenant_id),
    )[0]
    assert counts == (1, 0, 0, 0)
    assert len(reservations) == 1
    assert reservations[0]["feature_code"] == "document_extraction"
    assert reservations[0]["amount"] == max(1, -(-len(payload) // 1024))

    # The upload had no business-ingestion job or canonical writes. The
    # corresponding object key stays tenant-scoped and metadata references
    # the actual chunk evidence used by retrieval.
    path = _admin("SELECT storage_bucket_path FROM rag_documents_metadata WHERE tenant_id=%s AND document_id=%s;",
                  (tenant_id, body["document_id"]))[0][0]
    assert path.startswith(f"uploads/{tenant_id}/")
    with psycopg2.connect(ADMIN_DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM rag_document_chunks WHERE tenant_id=%s AND document_id=%s;",
                           (tenant_id, body["document_id"]))
            assert cursor.fetchone()[0] > 0
