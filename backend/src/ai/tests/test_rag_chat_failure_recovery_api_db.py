"""Provider-failure recovery through the authenticated RAG HTTP/database path."""
import os
import uuid
from contextlib import nullcontext

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.tests.signup_helpers import create_verified_test_account

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="disposable PostgreSQL and ceopro_app role are required",
)


def _admin(sql, params=()):
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else None


def test_provider_failure_keeps_user_turn_reopens_session_and_releases_usage(monkeypatch):
    from src.ai.main import app
    from src.ai.routers import rag

    monkeypatch.setattr(rag.credits, "metering", lambda *args, **kwargs: nullcontext())

    def unavailable(*_args, **_kwargs):
        raise rag.rag_llm_client.LLMNotConfiguredError("fixture: no provider")

    monkeypatch.setattr(rag.rag_advisor, "answer", unavailable)
    with TestClient(app) as client:
        session = create_verified_test_account(client, {
            "full_name": "RAG Recovery Owner", "business_name": "RAG Recovery Test",
            "email": f"rag-recovery+{uuid.uuid4().hex[:10]}@example.test",
            "country_code": "JO", "primary_currency": "JOD", "password": "Rag!Recovery-2026",
        })
        tenant_id, user_id = session["tenant_id"], session["user_id"]
        _admin("UPDATE tenant_plan_assignments SET plan_key='growth',status='active',source='manual' WHERE tenant_id=%s;",
               (tenant_id,))
        headers = {"Authorization": f"Bearer {session['access_token']}"}
        question = "What does the return policy say about unused items?"
        response = client.post("/rag/query", params={"query_text": question}, headers=headers)
        assert response.status_code == 503
        assert response.headers["x-assistant-reason"] == "not_configured"
        conversation_id = response.headers["x-assistant-session-id"]

        history = client.get("/rag/sessions", headers=headers)
        assert history.status_code == 200
        saved = next(item for item in history.json()["sessions"] if item["session_id"] == conversation_id)
        assert question in saved["title"]
        messages = client.get(f"/rag/sessions/{conversation_id}/messages", headers=headers)
        assert messages.status_code == 200
        assert [item["content"] for item in messages.json()["messages"]] == [question]

    rows = _admin("SELECT used FROM tenant_usage_counters WHERE tenant_id=%s AND feature_code='rag_assistant' "
                  "ORDER BY period_start DESC LIMIT 1;", (tenant_id,))
    assert not rows or rows[0][0] == 0
    assert _admin("SELECT COUNT(*) FROM conversation_sessions WHERE tenant_id=%s AND user_id=%s AND session_id=%s;",
                  (tenant_id, user_id, conversation_id))[0][0] == 1
