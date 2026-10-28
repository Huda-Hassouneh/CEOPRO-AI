"""POST /rag/query end to end (real signup, real database, real credits gate)
with only the Groq HTTP call stubbed: what a person sees when the model has no
price, the key is wrong or missing, the company has no plan, or its AI Credits
are used up. Nothing here calls a model provider."""
import json
import os
import uuid
from datetime import date
from decimal import Decimal

import psycopg2
import pytest
from fastapi.testclient import TestClient

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB assistant router test",
)
PASSWORD = "RagRouter!Test2026"


class _Response:
    def __init__(self, status, body):
        self.status_code, self._body, self.text, self.headers = status, body, str(body), {}

    def json(self):
        return self._body


def _model_reply(text):
    return _Response(200, {"id": "c1", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}})


GOOD_REPLY = json.dumps({"blocks": [{"type": "paragraph", "claims": [
    {"text": "You have 1 product.", "kind": "fact", "evidence": ["E1"]}]}], "follow_up_questions": []})
QUESTION = "How many products do I have?"


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch):
    monkeypatch.delenv("KEEL_TEST_DISABLE_METERING", raising=False)
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_never_logged")


@pytest.fixture
def client():
    from src.ai.main import app

    return TestClient(app)


@pytest.fixture
def model(monkeypatch):
    """Priced model whose HTTP call is scripted; returns the list of calls made."""
    from src.ai.billing import admin
    from src.ai.rag import llm_client

    provider = f"test_ai_{uuid.uuid4().hex[:8]}"
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    for unit, usd in (("input_token", "0.000002"), ("output_token", "0.000008")):
        admin.set_price(conn, budget_kind="ai", provider=provider, operation="*", unit=unit, unit_cost_usd=Decimal(usd),
                        source="test", verified_on=date.today(), approved_by="test", reason="test",
                        safety_margin=Decimal("0"))
    conn.commit()
    conn.close()
    monkeypatch.setattr(llm_client, "active_provider", lambda: provider)
    calls = []
    monkeypatch.setattr(llm_client, "_post_with_retry", lambda *a, **k: calls.append(1) or _model_reply(GOOD_REPLY))
    return provider, calls


def _admin(sql, params=()):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall() if cursor.description else None
    conn.close()
    return rows


def _company_with_one_product(client):
    business = f"Router Test {uuid.uuid4().hex[:8]}"
    email = f"router+{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/auth/signup", json={"full_name": "Owner", "business_name": business, "email": email,
                                                  "country_code": "JO", "primary_currency": "JOD", "password": PASSWORD})
    assert response.status_code == 200, response.text
    tenant = _admin("SELECT tenant_id FROM companies WHERE business_name = %s;", (business,))[0][0]
    _admin("INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s, 2.5, 'JOD');",
           (tenant, json.dumps({"en": "Olive Oil 1L"})))
    return str(tenant), {"Authorization": f"Bearer {response.json()['access_token']}"}


def _ask(client, headers):
    return client.post("/rag/query", params={"query_text": QUESTION}, headers=headers)


def test_a_priced_model_answers_with_references(client, model):
    _, calls = model
    _tenant, headers = _company_with_one_product(client)
    response = _ask(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer_mode"] == "ai" and len(calls) == 1
    assert body["references"] and body["session_id"]


def test_an_unpriced_model_gives_200_evidence_not_a_503(client, model, monkeypatch):
    from src.ai.rag import llm_client

    _, calls = model
    monkeypatch.setattr(llm_client, "active_provider", lambda: f"unpriced_{uuid.uuid4().hex[:6]}")
    _tenant, headers = _company_with_one_product(client)
    response = _ask(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer_mode"] == "evidence" and body["references"] and calls == []
    assert {"need": "answer_writing", "status": "not_configured"} in body["evidence_status"]


def test_a_rejected_key_gives_200_evidence_provider_unavailable(client, model, monkeypatch):
    from src.ai.rag import llm_client

    _, calls = model
    monkeypatch.setattr(llm_client, "_post_with_retry",
                        lambda *a, **k: calls.append(1) or _Response(401, {"error": {"message": "Invalid API Key"}}))
    _tenant, headers = _company_with_one_product(client)
    response = _ask(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer_mode"] == "evidence"
    assert {"need": "answer_writing", "status": "provider_unavailable"} in body["evidence_status"]
    assert "gsk_" not in json.dumps(body) and "Invalid API Key" not in json.dumps(body)


def test_a_missing_key_gives_200_evidence_not_configured(client, model, monkeypatch):
    _, calls = model
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _tenant, headers = _company_with_one_product(client)
    response = _ask(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer_mode"] == "evidence" and calls == []
    assert {"need": "answer_writing", "status": "not_configured"} in body["evidence_status"]


def test_a_company_without_a_plan_is_refused_with_402(client, model):
    tenant, headers = _company_with_one_product(client)
    _admin("DELETE FROM tenant_plan_assignments WHERE tenant_id = %s;", (tenant,))
    response = _ask(client, headers)
    assert response.status_code == 402, response.text
    assert "SUBSCRIPTION_INACTIVE" in response.text


def test_a_company_with_no_ai_credits_left_still_gets_an_evidence_answer(client, model):
    from src.ai.billing import admin
    from src.ai.core import usage

    tenant, headers = _company_with_one_product(client)
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    limit = Decimal(str(usage.get_plan(conn, tenant)["features"]["ai_credits"]["limit"]))
    admin.adjust_credits(conn, tenant_id=tenant, budget_kind="ai", credits_delta=limit,
                         reference=f"t-{uuid.uuid4().hex[:6]}", approved_by="test", reason="test")
    conn.commit()
    conn.close()
    _, calls = model
    response = _ask(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer_mode"] == "evidence" and calls == []
    assert {"need": "answer_writing", "status": "allowance_used"} in body["evidence_status"]
