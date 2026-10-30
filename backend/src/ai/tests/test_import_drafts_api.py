"""HTTP contract tests for the tenant-scoped M97 preview/review routes."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.core.security import get_tenant_context
from src.ai.routers import extraction

_BATCH = "00000000-0000-4000-8000-000000000001"
_REVISION = "00000000-0000-4000-8000-000000000002"
_ROW = "00000000-0000-4000-8000-000000000003"


def _client():
    app = FastAPI()
    app.include_router(extraction.router)
    app.dependency_overrides[get_tenant_context] = lambda: SimpleNamespace(tenant_id="tenant-a", user_id="owner-a")
    return TestClient(app)


def test_import_draft_list_is_paginated_and_filterable(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(extraction.db, "app_role_connection", lambda tenant, actor: conn)
    monkeypatch.setattr(extraction.typed_imports, "list_import_drafts", lambda *a, **kw: [{"batch_id": "b1"}])
    response = _client().get("/extraction/import-drafts?limit=10&offset=20&category=invoice&state=review_required")
    assert response.status_code == 200
    assert response.json() == {"items": [{"batch_id": "b1"}], "limit": 10, "offset": 20}
    conn.close.assert_called_once()


def test_import_draft_preview_hides_missing_or_cross_tenant_batch(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(extraction.db, "app_role_connection", lambda tenant, actor: conn)
    monkeypatch.setattr(extraction.typed_imports, "get_import_draft", lambda *a, **kw: None)
    response = _client().get(f"/extraction/import-drafts/{_BATCH}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Import draft not found."


def test_review_uses_authenticated_context_and_does_not_post(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(extraction.db, "app_role_connection", lambda tenant, actor: conn)
    current = {"current_revision_id": _REVISION, "posting_status": "not_committed"}
    monkeypatch.setattr(extraction.typed_imports, "get_import_draft", lambda *a, **kw: current)
    calls = []

    def decide(conn_arg, **kwargs):
        calls.append((conn_arg, kwargs))
        return {"decision_id": "decision-1", "duplicate": False, "decision": "approve",
                "canonical_write_performed": False}

    monkeypatch.setattr(extraction.typed_imports, "decide_import_review", decide)
    response = _client().post(f"/extraction/import-drafts/{_BATCH}/reviews", json={
        "revision_id": _REVISION, "decision": "approve", "idempotency_key": "request-1",
        "reason_code": "reviewed", "row_id": _ROW,
    })
    assert response.status_code == 200
    assert response.json()["canonical_write_performed"] is False
    assert response.json()["posting_status"] == "not_committed"
    assert calls[0][0] is conn
    assert calls[0][1] == {"batch_id": _BATCH, "revision_id": _REVISION, "row_id": _ROW,
                           "decision": "approve", "idempotency_key": "request-1", "reason_code": "reviewed"}
    conn.commit.assert_called_once()


def test_stale_revision_review_returns_conflict_without_writing(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(extraction.db, "app_role_connection", lambda tenant, actor: conn)
    monkeypatch.setattr(extraction.typed_imports, "get_import_draft", lambda *a, **kw: {"current_revision_id": "00000000-0000-4000-8000-000000000004"})
    decide = MagicMock()
    monkeypatch.setattr(extraction.typed_imports, "decide_import_review", decide)
    response = _client().post(f"/extraction/import-drafts/{_BATCH}/reviews", json={
        "revision_id": _REVISION, "decision": "reject", "idempotency_key": "request-1", "reason_code": "test",
    })
    assert response.status_code == 409
    decide.assert_not_called()
    conn.rollback.assert_called_once()


def test_review_requires_valid_decision_and_identity_is_not_client_supplied(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(extraction.db, "app_role_connection", lambda tenant, actor: conn)
    monkeypatch.setattr(extraction.typed_imports, "get_import_draft", lambda *a, **kw: {
        "current_revision_id": _REVISION, "posting_status": "not_committed"})
    decide = MagicMock(return_value={"decision_id": "d", "duplicate": False, "decision": "approve"})
    monkeypatch.setattr(extraction.typed_imports, "decide_import_review", decide)
    response = _client().post(f"/extraction/import-drafts/{_BATCH}/reviews", json={
        "revision_id": _REVISION, "decision": "approve", "idempotency_key": "request-1", "reason_code": "checked",
        "reviewer_user_id": "attacker",
    })
    assert response.status_code == 200
    assert "reviewer_user_id" not in decide.call_args.kwargs
    unauthenticated = _client()
    unauthenticated.app.dependency_overrides.clear()
    assert unauthenticated.get("/extraction/import-drafts").status_code == 401
