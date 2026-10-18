"""Offline tests for structured_summaries' unchanged-content skip and per-slot failure isolation."""

import hashlib
from unittest.mock import MagicMock

from src.ai.rag import structured_summaries as ss


def conn_with_existing(row):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [row, ("new-doc-id",)]
    return conn


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_identical_content_already_processed_is_skipped():
    minio = MagicMock()
    doc_id = ss._upsert_summary_document(conn_with_existing(("d1", h("x"), "Processed")), minio, "11111111-1111-4111-8111-111111111111", "sales_history", "x", "b")
    assert doc_id == "d1"
    minio.put_object.assert_not_called()


def test_identical_content_but_failed_is_reuploaded_for_retry():
    minio = MagicMock()
    doc_id = ss._upsert_summary_document(conn_with_existing(("d1", h("x"), "Failed")), minio, "11111111-1111-4111-8111-111111111111", "sales_history", "x", "b")
    assert doc_id == "new-doc-id"
    minio.put_object.assert_called_once()


def test_changed_content_is_reuploaded():
    minio = MagicMock()
    ss._upsert_summary_document(conn_with_existing(("d1", h("old"), "Processed")), minio, "11111111-1111-4111-8111-111111111111", "sales_history", "new", "b")
    minio.put_object.assert_called_once()


def test_failing_slot_rolls_back_and_other_slots_still_run(monkeypatch):
    calls = []

    def bad(conn, tenant):
        raise RuntimeError("sql failed")

    gens = {"a": bad, "b": lambda c, t: "text-b"}
    monkeypatch.setattr(ss, "_GENERATORS", gens)
    monkeypatch.setattr(ss, "_upsert_summary_document", lambda conn, m, t, slot, text, b: calls.append(slot) or f"id-{slot}")
    monkeypatch.setattr(ss, "ingest_pending_documents", lambda *a, **k: 1)
    conn = MagicMock()

    result = ss.regenerate_all_structured_summaries(conn, MagicMock(), "t")

    assert result["document_ids"] == {"a": None, "b": "id-b"}
    assert calls == ["b"]
    conn.rollback.assert_called_once()
