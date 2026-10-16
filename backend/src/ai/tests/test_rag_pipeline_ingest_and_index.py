"""
Offline tests for pipeline.ingest_pending_documents() and build_hybrid_index():
per-document commit/rollback isolation, and tolerance of chunks with a NULL or
mismatched-dimension embedding. data_access and the embedding model are mocked.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from src.ai.rag import pipeline


@pytest.fixture(autouse=True)
def clear_cache():
    pipeline._TENANT_INDEX_CACHE.clear()
    yield
    pipeline._TENANT_INDEX_CACHE.clear()


def doc(doc_id):
    return {"document_id": doc_id, "file_name": f"{doc_id}.txt", "storage_bucket_path": f"{doc_id}.txt"}


def patch_ingest(monkeypatch, docs, fail_on=()):
    statuses, events = {}, []
    monkeypatch.setattr(pipeline.data_access, "list_documents", lambda conn, t, status=None: docs)
    monkeypatch.setattr(pipeline.data_access, "fetch_document_text", lambda m, b, key: "some words here")
    monkeypatch.setattr(pipeline, "try_embed", lambda chunks: np.ones((len(chunks), 3), dtype=np.float32))
    monkeypatch.setattr(pipeline, "backfill_missing_embeddings", lambda conn, t: 0)

    def replace(conn, tenant, doc_id, *a, **k):
        if doc_id in fail_on:
            raise RuntimeError("insert failed")
        events.append(("replace", doc_id))

    def mark(conn, doc_id, status):
        statuses[doc_id] = status
        events.append(("mark", doc_id, status))

    monkeypatch.setattr(pipeline.data_access, "replace_document_chunks", replace)
    monkeypatch.setattr(pipeline.data_access, "mark_document_status", mark)
    return statuses, events


def test_ingest_failure_rolls_back_marks_failed_and_continues(monkeypatch):
    statuses, events = patch_ingest(monkeypatch, [doc("bad"), doc("good")], fail_on={"bad"})
    conn = MagicMock()
    conn.commit.side_effect = lambda: events.append(("commit",))
    conn.rollback.side_effect = lambda: events.append(("rollback",))

    count = pipeline.ingest_pending_documents(conn, MagicMock(), "t1")

    assert count == 1
    assert statuses == {"bad": "Failed", "good": "Processed"}
    # rollback must precede the Failed update, which needs a usable transaction
    assert events.index(("rollback",)) < events.index(("mark", "bad", "Failed"))
    # each document is committed individually
    assert events.count(("commit",)) == 2
    assert events[-1] == ("commit",)


def test_ingest_commits_each_successful_document_right_after_marking(monkeypatch):
    statuses, events = patch_ingest(monkeypatch, [doc("a"), doc("b")])
    conn = MagicMock()
    conn.commit.side_effect = lambda: events.append(("commit",))

    assert pipeline.ingest_pending_documents(conn, MagicMock(), "t1") == 2
    assert events == [
        ("replace", "a"), ("mark", "a", "Processed"), ("commit",),
        ("replace", "b"), ("mark", "b", "Processed"), ("commit",),
    ]
    conn.rollback.assert_not_called()


def test_ingest_invalidates_cache_only_when_something_processed(monkeypatch):
    pipeline._TENANT_INDEX_CACHE["t1"] = object()
    patch_ingest(monkeypatch, [doc("bad")], fail_on={"bad"})
    pipeline.ingest_pending_documents(MagicMock(), MagicMock(), "t1")
    assert "t1" in pipeline._TENANT_INDEX_CACHE

    patch_ingest(monkeypatch, [doc("ok")])
    pipeline.ingest_pending_documents(MagicMock(), MagicMock(), "t1")
    assert "t1" not in pipeline._TENANT_INDEX_CACHE


def rows_for(monkeypatch, rows):
    monkeypatch.setattr(pipeline.data_access, "load_tenant_chunks", lambda conn, t: rows)


def vec(*xs):
    return np.array(xs, dtype=np.float32)


def test_build_index_skips_null_embeddings_for_faiss_but_keeps_them_in_bm25(monkeypatch):
    rows_for(monkeypatch, [("c1", "alpha text", vec(1, 0)), ("c2", "beta text", None)])
    index = pipeline.build_hybrid_index(MagicMock(), "t1", use_cache=False)

    assert len(index.bm25) == 2
    assert len(index.faiss) == 1
    assert [r.chunk_id for r in index.faiss.query(vec(1, 0))] == ["c1"]


def test_build_index_skips_dimension_mismatched_embeddings(monkeypatch):
    rows_for(monkeypatch, [("c1", "a", vec(1, 0)), ("c2", "b", vec(1, 0, 0)), ("c3", "c", vec(0, 1))])
    index = pipeline.build_hybrid_index(MagicMock(), "t1", use_cache=False)

    assert len(index.bm25) == 3
    assert len(index.faiss) == 2


def test_build_index_with_no_embeddings_at_all_does_not_crash(monkeypatch):
    rows_for(monkeypatch, [("c1", "a", None), ("c2", "b", None)])
    index = pipeline.build_hybrid_index(MagicMock(), "t1", use_cache=False)

    assert len(index.bm25) == 2
    assert len(index.faiss) == 0
    assert index.faiss.query(vec(1, 0)) == []


def test_build_index_empty_tenant(monkeypatch):
    rows_for(monkeypatch, [])
    index = pipeline.build_hybrid_index(MagicMock(), "t1", use_cache=False)
    assert len(index.bm25) == 0 and len(index.faiss) == 0


def test_build_index_caches_per_tenant(monkeypatch):
    rows_for(monkeypatch, [("c1", "a", vec(1, 0))])
    first = pipeline.build_hybrid_index(MagicMock(), "t1")
    rows_for(monkeypatch, [])
    assert pipeline.build_hybrid_index(MagicMock(), "t1") is first
    assert pipeline.build_hybrid_index(MagicMock(), "t2") is not first
