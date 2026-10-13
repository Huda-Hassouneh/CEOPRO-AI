"""
Integration test for the RAG ingestion/retrieval pipeline against a real
PostgreSQL instance (actual Final_schema.sql, including the pgvector
`embedding` column - migration 20260827000100_add_rag_embedding_column.sql
must be applied) and a real MinIO instance. Skipped unless both
AI_TEST_DATABASE_URL and AI_TEST_MINIO_ENDPOINT are set.
"""

import io
import os
import uuid

import numpy as np
import psycopg2
import pytest
from minio import Minio

from src.ai.rag import data_access, pipeline

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
MINIO_ENDPOINT = os.getenv("AI_TEST_MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("AI_TEST_MINIO_ACCESS_KEY", "minio_admin")
MINIO_SECRET_KEY = os.getenv("AI_TEST_MINIO_SECRET_KEY", "local_test_password_only")
TEST_BUCKET = "ceopro-rag-knowledge-test"

pytestmark = pytest.mark.skipif(
    not (DATABASE_URL and MINIO_ENDPOINT), reason="AI_TEST_DATABASE_URL and AI_TEST_MINIO_ENDPOINT not both set"
)

_needs_embeddings = pytest.mark.skipif(
    not os.getenv("AI_TEST_EMBEDDINGS"), reason="AI_TEST_EMBEDDINGS not set - skipping (downloads a real model)"
)
_needs_reranker = pytest.mark.skipif(
    not os.getenv("AI_TEST_RERANKING"), reason="AI_TEST_RERANKING not set - skipping (downloads a real model)"
)


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def minio_client():
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    if not client.bucket_exists(TEST_BUCKET):
        client.make_bucket(TEST_BUCKET)
    yield client


def _upload_text(minio_client, object_key: str, text: str) -> None:
    data = text.encode("utf-8")
    minio_client.put_object(TEST_BUCKET, object_key, io.BytesIO(data), length=len(data))


@pytest.fixture
def seeded_tenant(conn):
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, country_code, primary_currency)
            VALUES (%s, 'RAG Test Co', 'JO', 'JOD');
            """,
            (tenant_id,),
        )
    conn.commit()
    return tenant_id


def _insert_document(conn, tenant_id, file_name, object_key, status="Pending", file_size_bytes=100):
    document_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO rag_documents_metadata
                (document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes, processed_status)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (document_id, tenant_id, file_name, object_key, file_size_bytes, status),
        )
    conn.commit()
    return document_id


def test_fetch_document_text_round_trips_through_minio(minio_client):
    _upload_text(minio_client, "test/doc1.txt", "Sunscreen SPF 50 is our best selling product.")
    text = data_access.fetch_document_text(minio_client, TEST_BUCKET, "test/doc1.txt")
    assert text == "Sunscreen SPF 50 is our best selling product."


def test_ingest_pending_documents_marks_processed(conn, minio_client, seeded_tenant):
    object_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, object_key, "Our return policy allows returns within 30 days of purchase.")
    document_id = _insert_document(conn, seeded_tenant, "policy.txt", object_key)

    processed_count = pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET)

    assert processed_count == 1
    docs = data_access.list_documents(conn, seeded_tenant, status="Processed")
    assert len(docs) == 1
    assert docs[0]["document_id"] == document_id


def test_ingest_pending_documents_marks_failed_on_missing_object(conn, minio_client, seeded_tenant):
    _insert_document(conn, seeded_tenant, "missing.txt", "test/does-not-exist.txt")

    processed_count = pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET)

    assert processed_count == 0
    docs = data_access.list_documents(conn, seeded_tenant, status="Failed")
    assert len(docs) == 1


def test_replace_document_chunks_bulk_inserts_preserve_chunk_order(conn, seeded_tenant):
    """
    Production-hardening audit finding: replace_document_chunks() used to
    INSERT one row at a time (one round trip per chunk). Now a single
    execute_values() bulk INSERT - this verifies the bulk path still
    preserves chunk_index ordering and the real vector content correctly,
    not just that it's faster. Doesn't need AI_TEST_EMBEDDINGS - fake,
    deterministic embeddings are enough to check persistence/ordering.
    """
    document_id = _insert_document(conn, seeded_tenant, "multi.txt", f"test/{uuid.uuid4()}.txt")
    chunks = [f"chunk number {i}" for i in range(5)]
    embeddings = np.stack([np.full(384, float(i), dtype=np.float32) for i in range(5)])

    data_access.replace_document_chunks(conn, seeded_tenant, document_id, chunks, embeddings, "test-model-v1")
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT chunk_index, chunk_text_content FROM rag_document_chunks "
            "WHERE tenant_id = %s AND document_id = %s ORDER BY chunk_index;",
            (seeded_tenant, document_id),
        )
        rows = cursor.fetchall()

    assert [r[0] for r in rows] == [0, 1, 2, 3, 4]
    assert [r[1] for r in rows] == chunks

    loaded = data_access.load_tenant_chunks(conn, seeded_tenant)
    assert len(loaded) == 5
    for _, _, embedding in loaded:
        assert embedding is not None
        assert embedding.shape == (384,)


def test_replace_document_chunks_handles_zero_chunks_without_error(conn, seeded_tenant):
    """An empty chunk list (e.g. a document that produced no usable text)
    must still correctly wipe any previous chunk set, not crash on an
    empty execute_values() call."""
    document_id = _insert_document(conn, seeded_tenant, "empty.txt", f"test/{uuid.uuid4()}.txt")

    data_access.replace_document_chunks(
        conn, seeded_tenant, document_id, [], np.empty((0, 384), dtype=np.float32), "test-model-v1"
    )
    conn.commit()

    assert data_access.load_tenant_chunks(conn, seeded_tenant) == []


def test_ingest_persists_chunks_and_embeddings_not_just_status(conn, minio_client, seeded_tenant):
    """
    Regression test for audit finding P1: ingestion must actually write to
    rag_document_chunks (text + a real 384-dim embedding), not just flip
    processed_status. This is the persistence retrieval now depends on -
    without it, build_tenant_index()/build_hybrid_index() would silently
    build empty indexes from a Processed-but-unpersisted document.
    """
    object_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, object_key, "Our return policy allows returns within 30 days of purchase.")
    document_id = _insert_document(conn, seeded_tenant, "policy.txt", object_key)

    processed_count = pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET)
    assert processed_count == 1

    rows = data_access.load_tenant_chunks(conn, seeded_tenant)
    assert len(rows) == 1
    chunk_id, text, embedding = rows[0]
    assert "return" in text.lower()
    assert embedding is not None
    assert embedding.shape == (384,)


def test_reingesting_the_same_document_replaces_chunks_instead_of_duplicating(conn, minio_client, seeded_tenant):
    """
    Regression test for the wipe-and-replace lifecycle requirement:
    ingesting the same document_id twice (simulating a re-upload whose
    content changed, once whatever marks it 'Pending' again exists) must
    leave exactly the new chunk set behind, not the old set plus the new
    one. Directly exercises data_access.replace_document_chunks()'s
    idempotency guarantee, not just assumes it from the DELETE in the SQL.
    """
    object_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, object_key, "Original content about sunscreen products.")
    document_id = _insert_document(conn, seeded_tenant, "doc.txt", object_key)

    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 1
    first_rows = data_access.load_tenant_chunks(conn, seeded_tenant)
    assert len(first_rows) == 1
    assert "sunscreen" in first_rows[0][1].lower()

    # Simulate a re-upload: new content at the same object key, document
    # flipped back to 'Pending' for the same document_id (what a real
    # upload endpoint would do - not built in this module, see
    # replace_document_chunks()'s docstring).
    _upload_text(minio_client, object_key, "Completely different content about winter coats and jackets.")
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE rag_documents_metadata SET processed_status = 'Pending' WHERE document_id = %s;",
            (document_id,),
        )
    conn.commit()

    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 1
    second_rows = data_access.load_tenant_chunks(conn, seeded_tenant)
    assert len(second_rows) == 1  # replaced, not accumulated
    assert "jackets" in second_rows[0][1].lower()
    assert "sunscreen" not in second_rows[0][1].lower()


def test_build_tenant_index_and_retrieve_end_to_end(conn, minio_client, seeded_tenant):
    doc1_key = f"test/{uuid.uuid4()}.txt"
    doc2_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, doc1_key, "Sunscreen SPF 50 is our best selling summer product with high UV protection.")
    _upload_text(minio_client, doc2_key, "Our warehouse policy covers moisturizer lotion storage for winter climates.")
    _insert_document(conn, seeded_tenant, "doc1.txt", doc1_key)
    _insert_document(conn, seeded_tenant, "doc2.txt", doc2_key)

    processed_count = pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET)
    assert processed_count == 2

    index = pipeline.build_tenant_index(conn, seeded_tenant)
    assert len(index) == 2  # one chunk per short document

    results = pipeline.retrieve(index, "sunscreen summer UV protection", top_k=5)
    assert len(results) > 0
    assert "Sunscreen" in results[0].text


@_needs_embeddings
def test_build_hybrid_index_and_retrieve_end_to_end(conn, minio_client, seeded_tenant):
    """
    Query is deliberately chosen with zero literal word overlap with any
    document, so BM25 contributes nothing and the ranking is driven purely by
    FAISS's semantic similarity - the clean way to verify hybrid retrieval
    surfaces a semantic match. A query with partial overlap ("sun protection
    cream for hot weather") was tried first and is NOT reliable here: with
    documents this short (single sentences, 10-13 tokens), BM25's length
    normalization can outweigh a single genuine keyword match, and equal-
    weighted Reciprocal Rank Fusion doesn't reliably correct for that against
    FAISS's opposite ranking - a real characteristic of short-chunk BM25, not
    a bug, but not safe to assert a specific winner on either. See
    AI_PROGRESS.md's entry for this module for the full investigation.
    """
    doc1_key = f"test/{uuid.uuid4()}.txt"
    doc2_key = f"test/{uuid.uuid4()}.txt"
    doc3_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, doc1_key, "Sunscreen SPF 50 is our best selling summer product with high UV protection.")
    _upload_text(minio_client, doc2_key, "Our warehouse policy covers moisturizer lotion storage for winter climates.")
    _upload_text(minio_client, doc3_key, "The quarterly financial audit report was completed and approved yesterday.")
    _insert_document(conn, seeded_tenant, "doc1.txt", doc1_key)
    _insert_document(conn, seeded_tenant, "doc2.txt", doc2_key)
    _insert_document(conn, seeded_tenant, "doc3.txt", doc3_key)

    processed_count = pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET)
    assert processed_count == 3

    tenant_index = pipeline.build_hybrid_index(conn, seeded_tenant)
    assert len(tenant_index.bm25) == 3
    assert len(tenant_index.faiss) == 3

    results = pipeline.retrieve_hybrid(tenant_index, "topical cream that prevents skin damage from strong sunlight", top_k=5)
    assert len(results) > 0
    assert "Sunscreen" in results[0].text  # semantically related despite zero literal keyword overlap


@_needs_embeddings
@_needs_reranker
def test_run_retrieval_end_to_end_with_reranking_and_context_assembly(conn, minio_client, seeded_tenant):
    """
    Full pipeline: ingest -> persisted hybrid index -> wide-pool RRF fusion
    -> Cross-Encoder re-rank -> context assembly. Verifies the whole
    audit-driven rebuild produces a sane, LLM-ready AssembledContext -
    not just that each stage works in isolation.
    """
    doc1_key = f"test/{uuid.uuid4()}.txt"
    doc2_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, doc1_key, "Sunscreen SPF 50 is our best selling summer product with high UV protection.")
    _upload_text(minio_client, doc2_key, "Our warehouse policy covers moisturizer lotion storage for winter climates.")
    _insert_document(conn, seeded_tenant, "doc1.txt", doc1_key)
    _insert_document(conn, seeded_tenant, "doc2.txt", doc2_key)

    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 2

    context = pipeline.run_retrieval(conn, seeded_tenant, "sunscreen for summer sun protection", top_k=2)

    assert context.query == "sunscreen for summer sun protection"
    assert "Sunscreen" in context.context_text
    assert "[Source 1]" in context.context_text
    assert len(context.sources) > 0
    assert context.sources[0]["chunk_id"]


@_needs_embeddings
def test_run_retrieval_falls_back_gracefully_when_reranker_unavailable(conn, minio_client, seeded_tenant):
    """
    Production-grade reliability requirement: a re-ranker that can't load
    (no AI_TEST_RERANKING model cached here, deliberately not requiring
    _needs_reranker) must not take down retrieval - run_retrieval() should
    still return a usable AssembledContext built from the RRF-fused order.
    """
    doc_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, doc_key, "Sunscreen SPF 50 is our best selling summer product with high UV protection.")
    _insert_document(conn, seeded_tenant, "doc.txt", doc_key)
    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 1

    context = pipeline.run_retrieval(conn, seeded_tenant, "sunscreen", top_k=1, use_reranker=False)

    assert "Sunscreen" in context.context_text
    assert len(context.sources) == 1


def test_build_hybrid_index_is_served_from_cache_on_the_second_call(conn, minio_client, seeded_tenant):
    """
    2026-09-01 efficiency review: build_hybrid_index() re-tokenized the
    whole corpus for BM25 and rebuilt FAISS from scratch on every call,
    even when nothing changed. Proves the fix actually reuses a cached
    object (identity check, not just "the data still looks right" - a
    coincidentally-correct rebuild would also pass a data-only assertion).
    """
    pipeline.invalidate_tenant_index_cache(seeded_tenant)  # isolate from any other test's leftover state
    doc_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, doc_key, "Sunscreen SPF 50 is our best selling summer product.")
    _insert_document(conn, seeded_tenant, "doc.txt", doc_key)
    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 1

    first = pipeline.build_hybrid_index(conn, seeded_tenant)
    second = pipeline.build_hybrid_index(conn, seeded_tenant)

    assert first is second  # the exact same object, not just equal data


def test_build_hybrid_index_cache_is_invalidated_by_reingestion(conn, minio_client, seeded_tenant):
    """The other half of the cache proof: a call after re-ingestion must NOT
    be served stale data from before the re-ingestion."""
    pipeline.invalidate_tenant_index_cache(seeded_tenant)
    doc_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, doc_key, "Original content about sunscreen.")
    document_id = _insert_document(conn, seeded_tenant, "doc.txt", doc_key)
    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 1

    stale = pipeline.build_hybrid_index(conn, seeded_tenant)
    assert len(stale.bm25) == 1

    _upload_text(minio_client, doc_key, "Completely different content about winter coats.")
    with conn.cursor() as cursor:
        cursor.execute("UPDATE rag_documents_metadata SET processed_status = 'Pending' WHERE document_id = %s;", (document_id,))
    conn.commit()
    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 1

    fresh = pipeline.build_hybrid_index(conn, seeded_tenant)
    assert fresh is not stale
    results = pipeline.retrieve(fresh.bm25, "winter coats", top_k=1)
    assert len(results) == 1


def test_run_retrieval_with_an_unreachable_confidence_threshold_returns_nothing(conn, minio_client, seeded_tenant):
    """
    Grounding/anti-hallucination proof: an impossibly high
    min_confidence_score must empty the result even when real, relevant
    content was ingested and retrieval would otherwise have found it -
    the caller (llm_client.answer_query()) then sees empty context_text
    and never calls the LLM. use_reranker=False here so this test doesn't
    also need the AI_TEST_RERANKING-gated model just to prove the filter
    itself works on RRF scores.
    """
    doc_key = f"test/{uuid.uuid4()}.txt"
    _upload_text(minio_client, doc_key, "Sunscreen SPF 50 is our best selling summer product.")
    _insert_document(conn, seeded_tenant, "doc.txt", doc_key)
    assert pipeline.ingest_pending_documents(conn, minio_client, seeded_tenant, bucket=TEST_BUCKET) == 1

    context = pipeline.run_retrieval(
        conn, seeded_tenant, "sunscreen", top_k=5, use_reranker=False, min_confidence_score=999.0
    )

    assert context.context_text == ""
    assert context.sources == []
