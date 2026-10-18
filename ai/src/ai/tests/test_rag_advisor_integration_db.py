"""
The assistant against a real PostgreSQL database (skipped unless
AI_TEST_DATABASE_URL and APP_DB_PASSWORD are set): every query runs as the
restricted ceopro_app role with row-level security, so these prove that a
member only ever gets evidence their company owns AND their role may see,
and that answers, references and conversation state persist. The model's
reply is scripted; nothing leaves the machine.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.rag import access as acl
from src.ai.rag import advisor, conversation_store, pipeline
from src.ai.research import page_reader, research
from src.ai.tests.test_rls_integration_db import _insert_user

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB integration test",
)


def _app_conn(tenant_id: str, user_id: str):
    parsed = urlparse(ADMIN_DATABASE_URL)
    url = urlunparse(parsed._replace(netloc=f"ceopro_app:{APP_DB_PASSWORD}@{parsed.hostname}:{parsed.port}"))
    connection = psycopg2.connect(url)
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id', %s, false);", (tenant_id,))
        cursor.execute("SELECT set_config('app.current_user_id', %s, false);", (user_id,))
    connection.commit()
    return connection


@pytest.fixture
def companies():
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    cursor = admin.cursor()
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    for tenant_id, name in [(tenant_a, "Advisor Test Foods"), (tenant_b, "Advisor Test Other")]:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, business_type, country_code, primary_currency) "
                       "VALUES (%s, %s, 'grocery', 'JO', 'JOD');", (tenant_id, name))
    for role in ("owner", "staff"):
        cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (role, role))
    owner_a, staff_a, owner_b = _insert_user(cursor, "adv-owner-a"), _insert_user(cursor, "adv-staff-a"), \
        _insert_user(cursor, "adv-owner-b")
    for tenant_id, user_id, role in [(tenant_a, owner_a, "owner"), (tenant_a, staff_a, "staff"), (tenant_b, owner_b, "owner")]:
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role))
    product_a, product_b = str(uuid.uuid4()), str(uuid.uuid4())
    cursor.execute("INSERT INTO products (product_id, tenant_id, product_name, current_price, cost_price, currency) VALUES "
                   "(%s, %s, %s, 6.000, 3.500, 'JOD'), (%s, %s, %s, 9.000, 7.000, 'JOD');",
                   (product_a, tenant_a, json.dumps({"en": "Cold Pressed Olive Oil 1L", "ar": "زيت زيتون معصور على البارد"}),
                    product_b, tenant_b, json.dumps({"en": "Secret Widget Pro"})))
    issued = datetime.now(timezone.utc) - timedelta(days=3)
    invoice = str(uuid.uuid4())
    cursor.execute("INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
                   "VALUES (%s, %s, 'ADV-1', %s, 777.000, 777.000, 'JOD');", (invoice, tenant_a, issued))
    cursor.execute("INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
                   "VALUES (%s, %s, %s, 129.5, 6.000, 777.000);", (tenant_a, invoice, product_a))
    document = str(uuid.uuid4())
    cursor.execute("INSERT INTO rag_documents_metadata (document_id, tenant_id, file_name, storage_bucket_path, "
                   "file_size_bytes, processed_status) VALUES (%s, %s, 'supplier terms.pdf', 'uploads/terms.pdf', 10, 'Processed');",
                   (document, tenant_a))
    cursor.execute("INSERT INTO rag_document_chunks (tenant_id, document_id, chunk_index, chunk_text_content, page_number) "
                   "VALUES (%s, %s, 0, 'Supplier payment terms: olive oil deliveries are paid within 45 days of the "
                   "invoice date.', 2);", (tenant_a, document))
    pipeline.invalidate_tenant_index_cache(tenant_a)
    pipeline.invalidate_tenant_index_cache(tenant_b)
    yield {"tenant_a": tenant_a, "tenant_b": tenant_b, "owner_a": owner_a, "staff_a": staff_a, "owner_b": owner_b,
           "product_a": product_a}
    for tenant_id in (tenant_a, tenant_b):
        for table in ("invoice_items", "invoices", "conversation_sessions"):
            cursor.execute(f"DELETE FROM {table} WHERE tenant_id = %s;", (tenant_id,))
        cursor.execute("DELETE FROM companies WHERE tenant_id = %s;", (tenant_id,))
    admin.close()


@pytest.fixture
def scripted(monkeypatch):
    prompts = []

    def call(messages, usage, max_tokens=None):
        prompts.append(messages[-1]["content"])
        return json.dumps({"blocks": [{"type": "paragraph", "claims": [
            {"text": "Here is what the records show.", "kind": "general", "evidence": []}]}]})
    monkeypatch.setattr(advisor, "_call", call)
    return prompts


def test_roles_are_read_from_the_membership(companies):
    conn = _app_conn(companies["tenant_a"], companies["owner_a"])
    try:
        assert acl.load_access(conn, companies["tenant_a"], companies["owner_a"]).role == "owner"
        assert acl.load_access(conn, companies["tenant_a"], companies["staff_a"]).role == "staff"
        # A member of another company has no access here at all.
        assert acl.load_access(conn, companies["tenant_a"], companies["owner_b"]) == acl.NO_ACCESS
    finally:
        conn.close()


def test_the_owner_gets_sales_evidence_linked_to_the_sales_screen(companies, scripted):
    conn = _app_conn(companies["tenant_a"], companies["owner_a"])
    try:
        result = advisor.answer(conn, companies["tenant_a"], "How were my sales this month?",
                                user_id=companies["owner_a"], enable_research=False)
    finally:
        conn.close()
    assert "777" in scripted[0] and "Cold Pressed Olive Oil 1L" in scripted[0]
    assert not any(s["status"] == "not_permitted" for s in result["evidence_status"])


def test_staff_never_receive_sales_or_cost_figures(companies, scripted):
    conn = _app_conn(companies["tenant_a"], companies["staff_a"])
    try:
        result = advisor.answer(conn, companies["tenant_a"], "How were my sales and profit margin this month?",
                                user_id=companies["staff_a"], enable_research=False)
    finally:
        conn.close()
    prompt = scripted[0]
    assert "777" not in prompt and "3.5" not in prompt, "no revenue or cost reaches the model for a staff member"
    assert {"sales", "financials"} <= {s["need"] for s in result["evidence_status"] if s["status"] == "not_permitted"}


def test_documents_need_the_documents_capability_and_never_cross_companies(companies, scripted):
    question = "What are the supplier payment terms for olive oil deliveries?"
    for tenant, user in [("tenant_a", "owner_a"), ("tenant_a", "staff_a"), ("tenant_b", "owner_b")]:
        conn = _app_conn(companies[tenant], companies[user])
        try:
            advisor.answer(conn, companies[tenant], question, user_id=companies[user], enable_research=False)
        finally:
            conn.close()
    owner_prompt, staff_prompt, other_prompt = scripted
    assert "45 days" in owner_prompt and "supplier terms.pdf" in owner_prompt
    assert "45 days" not in staff_prompt
    assert "45 days" not in other_prompt and "Cold Pressed" not in other_prompt


def test_another_company_never_sees_this_companys_products(companies, scripted):
    conn = _app_conn(companies["tenant_b"], companies["owner_b"])
    try:
        advisor.answer(conn, companies["tenant_b"], "What does Cold Pressed Olive Oil 1L cost me?",
                       user_id=companies["owner_b"], enable_research=False)
    finally:
        conn.close()
    assert "3.5" not in scripted[0] and "Cold Pressed Olive Oil 1L:" not in scripted[0]


def test_answers_references_and_conversation_state_persist(companies, scripted):
    conn = _app_conn(companies["tenant_a"], companies["owner_a"])
    try:
        session = conversation_store.create_session(conn, companies["tenant_a"], companies["owner_a"], "q")
        payload = {"answer_blocks": [{"type": "paragraph", "claims": [{"text": "x", "refs": [1]}]}],
                   "references": [{"n": 1, "title": "Sales"}]}
        conversation_store.append_message(conn, companies["tenant_a"], session, companies["owner_a"], "assistant",
                                          "x¹", sources=[], answer_payload=payload)
        conversation_store.save_session_state(conn, companies["tenant_a"], session,
                                              {"question": "q", "intents": ["sales"], "slots": {"period_days": 90}})
        conn.commit()
        messages = conversation_store.load_session_messages_for_display(conn, companies["tenant_a"], session)
        assert messages[0]["references"] == [{"n": 1, "title": "Sales"}] and messages[0]["answer_blocks"]
        assert conversation_store.load_session_state(conn, companies["tenant_a"], session)["slots"] == {"period_days": 90}
    finally:
        conn.close()
    other = _app_conn(companies["tenant_b"], companies["owner_b"])
    try:
        assert conversation_store.load_session_state(other, companies["tenant_a"], session) is None
    finally:
        other.close()


def test_research_pages_are_cached_as_public_data_only(companies):
    url = f"https://customs.gov.jo/test-{uuid.uuid4()}"
    page = page_reader.Page(url=url, status=page_reader.OK, title="Tariff", site_name="Jordan Customs",
                            published_at="2026-01-02", text="Olive oil duty 20%.")
    conn = _app_conn(companies["tenant_a"], companies["owner_a"])
    try:
        research._store_page(conn, page)
        cached = research._cached_page(conn, url, "regulation")
        assert cached.title == "Tariff" and cached.text == "Olive oil duty 20%." and cached.retrieved_at
        with conn.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'research_pages';")
            columns = {row[0] for row in cursor.fetchall()}
        assert not {"tenant_id", "user_id", "question"} & columns
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM research_pages WHERE url = %s;", (url,))
        conn.commit()
    finally:
        conn.close()
