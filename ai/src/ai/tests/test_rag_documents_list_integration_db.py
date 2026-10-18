"""
The AI Advisor's document list was a hard-coded empty list, so a customer
could never see which documents the assistant actually has - not even one
they just uploaded. Live-DB, skipped unless AI_TEST_DATABASE_URL is set.
"""
import os
import uuid

import psycopg2
import pytest

from src.ai.routers.rag import list_uploaded_documents

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Docs Co', 'JO', 'JOD');", (tenant_id,))
    return tenant_id


def _document(conn, tenant_id, file_name, path, status="Processed", chunks=0):
    document_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO rag_documents_metadata (document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes, content_type, processed_status) "
            "VALUES (%s, %s, %s, %s, 2048, 'application/pdf', %s);",
            (document_id, tenant_id, file_name, path, status),
        )
        for index in range(chunks):
            cursor.execute(
                "INSERT INTO rag_document_chunks (tenant_id, document_id, chunk_index, chunk_text_content) VALUES (%s, %s, %s, 'text');",
                (tenant_id, document_id, index),
            )
    return document_id


def test_lists_uploaded_documents_with_status_and_passage_count_but_not_generated_summaries(conn):
    tenant_id = _company(conn)
    _document(conn, tenant_id, "Return policy.pdf", f"uploads/{uuid.uuid4()}.pdf", chunks=3)
    _document(conn, tenant_id, "Supplier contract.pdf", f"uploads/{uuid.uuid4()}.pdf", status="Failed")
    _document(conn, tenant_id, "sales_summary.txt", "_generated/sales_summary.txt", chunks=2)

    documents = {d["file_name"]: d for d in list_uploaded_documents(conn, tenant_id)}

    assert set(documents) == {"Return policy.pdf", "Supplier contract.pdf"}
    assert (documents["Return policy.pdf"]["status"], documents["Return policy.pdf"]["chunk_count"]) == ("ready", 3)
    assert documents["Supplier contract.pdf"]["status"] == "failed"
    assert documents["Return policy.pdf"]["type"] == "pdf"


def test_never_lists_another_tenants_documents(conn):
    mine, theirs = _company(conn), _company(conn)
    _document(conn, theirs, "Their pricing strategy.pdf", f"uploads/{uuid.uuid4()}.pdf")
    assert list_uploaded_documents(conn, mine) == []
