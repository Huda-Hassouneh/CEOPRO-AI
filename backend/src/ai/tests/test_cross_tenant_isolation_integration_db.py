"""
Cross-tenant isolation regressions found by the two-company security test
(docs/SECURITY_MULTI_TENANT_TEST.md). Each test connects as the real
request role (ceopro_app) with the real transaction-scoped context
(db.dedicated_tenant_connection, the same PooledTenantConnection the API
uses), never as the schema owner, which bypasses row-level security.

Skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD are set (same
convention as test_rls_integration_db.py).
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import psycopg2
import pytest

from src.ai.tests.test_rls_integration_db import _app_database_url, _ensure_role_key, _insert_user

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB isolation test",
)


@pytest.fixture
def admin_conn():
    connection = psycopg2.connect(ADMIN_DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture
def app_db(monkeypatch):
    """Points src/ai/db.py at the test database, so the tests use its own connection helpers."""
    monkeypatch.setenv("DATABASE_URL", ADMIN_DATABASE_URL)
    monkeypatch.setenv("APP_DB_PASSWORD", APP_DB_PASSWORD)
    from src.ai import db

    return db


@pytest.fixture
def companies(admin_conn):
    """Two competing companies, one owner each, plus one pending team
    invitation and one email-verification code per company."""
    cursor = admin_conn.cursor()
    role_key = _ensure_role_key(cursor)
    out = {}
    for key in ("a", "b"):
        tenant_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Isolation Co {key.upper()}"),
        )
        user_id = _insert_user(cursor, f"owner-{key}")
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role_key))
        expires = datetime.now(timezone.utc) + timedelta(days=1)
        cursor.execute(
            """INSERT INTO auth_tokens (token_type, token_hash, email, tenant_id, role_key, invited_by_user_id, expires_at)
               VALUES ('TEAM_INVITATION', %s, %s, %s, %s, %s, %s) RETURNING token_id;""",
            (uuid.uuid4().hex * 2, f"invitee-{key}-{tenant_id}@example.com", tenant_id, role_key, user_id, expires),
        )
        invitation_id = str(cursor.fetchone()[0])
        cursor.execute(
            """INSERT INTO auth_tokens (token_type, token_hash, user_id, expires_at)
               VALUES ('EMAIL_VERIFICATION', %s, %s, %s) RETURNING token_id;""",
            (uuid.uuid4().hex * 2, user_id, expires),
        )
        code_id = str(cursor.fetchone()[0])
        out[key] = {"tenant_id": tenant_id, "user_id": user_id, "invitation_id": invitation_id, "code_id": code_id,
                    "role_key": role_key}
    return out


# --- auth_tokens: team invitations and sign-in codes ---------------------------------------------------

def test_tenant_connection_cannot_see_or_change_another_companys_auth_tokens(app_db, companies):
    a, b = companies["a"], companies["b"]
    conn = app_db.dedicated_tenant_connection(a["tenant_id"], a["user_id"])
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT token_id::text FROM auth_tokens WHERE token_id IN (%s, %s);", (b["invitation_id"], b["code_id"]))
            assert cursor.fetchall() == []
            cursor.execute("UPDATE auth_tokens SET used_at = NOW() WHERE token_id IN (%s, %s);", (b["invitation_id"], b["code_id"]))
            assert cursor.rowcount == 0
            cursor.execute("DELETE FROM auth_tokens WHERE token_id IN (%s, %s);", (b["invitation_id"], b["code_id"]))
            assert cursor.rowcount == 0
            # Its own company's invitation and its own user's code stay usable.
            cursor.execute("SELECT token_id::text FROM auth_tokens WHERE token_id IN (%s, %s) ORDER BY 1;", (a["invitation_id"], a["code_id"]))
            assert sorted(r[0] for r in cursor.fetchall()) == sorted([a["invitation_id"], a["code_id"]])
        conn.rollback()
    finally:
        conn.close()


def test_tenant_connection_cannot_point_an_invitation_at_another_company(app_db, companies):
    """Re-pointing (or creating) an invitation for a company you don't belong
    to would let you join a competitor with the role of your choice."""
    a, b = companies["a"], companies["b"]
    for statement, params in (
        ("UPDATE auth_tokens SET tenant_id = %s WHERE token_id = %s;", (b["tenant_id"], a["invitation_id"])),
        ("""INSERT INTO auth_tokens (token_type, token_hash, email, tenant_id, role_key, invited_by_user_id, expires_at)
            VALUES ('TEAM_INVITATION', %s, 'x@example.com', %s, %s, %s, NOW() + INTERVAL '1 day');""",
         (uuid.uuid4().hex * 2, b["tenant_id"], b["role_key"], a["user_id"])),
    ):
        conn = app_db.dedicated_tenant_connection(a["tenant_id"], a["user_id"])
        try:
            with conn.cursor() as cursor, pytest.raises(psycopg2.Error, match="row-level security"):
                cursor.execute(statement, params)
        finally:
            conn.rollback()
            conn.close()


def test_connection_without_context_sees_no_auth_tokens(companies):
    conn = psycopg2.connect(_app_database_url())
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM auth_tokens WHERE token_id IN (%s, %s);",
                           (companies["a"]["invitation_id"], companies["b"]["code_id"]))
            assert cursor.fetchone()[0] == 0
    finally:
        conn.rollback()
        conn.close()


def test_sign_in_lookup_connection_still_reads_and_consumes_tokens(app_db, companies):
    """Password reset, email verification and invitation links run before
    there is any company context: their own connection must keep working."""
    b = companies["b"]
    conn = app_db.auth_lookup_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM auth_tokens WHERE token_id IN (%s, %s);", (b["invitation_id"], b["code_id"]))
            assert cursor.fetchone()[0] == 2
            cursor.execute("UPDATE auth_tokens SET used_at = NOW() WHERE token_id = %s;", (b["code_id"],))
            assert cursor.rowcount == 1
    finally:
        conn.rollback()
        conn.close()


# --- shared tables the request role must not change -----------------------------------------------------

@pytest.mark.parametrize("table", ["system_roles", "usage_plan_entitlements", "schema_migrations", "image_workers"])
def test_request_role_cannot_write_global_tables(admin_conn, table):
    """One company's request must never be able to rewrite what every
    company's roles or plans mean, or the migration history."""
    cursor = admin_conn.cursor()
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        cursor.execute("SELECT has_table_privilege('ceopro_app', %s, %s);", (table, privilege))
        assert cursor.fetchone()[0] is False, f"ceopro_app has {privilege} on {table}"


def test_request_role_cannot_claim_image_jobs(admin_conn):
    """Only the image worker (system connection) claims jobs; a request
    connection claiming one would take another company's job."""
    cursor = admin_conn.cursor()
    cursor.execute("SELECT has_function_privilege('ceopro_app', 'claim_image_generation_job(text, integer)', 'EXECUTE');")
    assert cursor.fetchone()[0] is False


# --- forecast model records -----------------------------------------------------------------------------

def test_forecast_model_records_are_private_to_their_company(app_db, companies):
    from src.ai.forecasting import evidence

    a, b = companies["a"], companies["b"]
    conn = app_db.dedicated_tenant_connection(a["tenant_id"], a["user_id"])
    try:
        model_version_id = evidence.insert_model_version(conn, "xgboost-isolation-test", "2026-10-29", "candidate", {"mae": 1.5})
        conn.commit()
    finally:
        conn.close()
    try:
        for tenant, user, expected in ((b["tenant_id"], b["user_id"], 0), (a["tenant_id"], a["user_id"], 1)):
            conn = app_db.dedicated_tenant_connection(tenant, user)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM model_versions WHERE model_version_id = %s;", (model_version_id,))
                    assert cursor.fetchone()[0] == expected
            finally:
                conn.rollback()
                conn.close()
    finally:
        with psycopg2.connect(ADMIN_DATABASE_URL) as admin:
            admin.cursor().execute("DELETE FROM model_versions WHERE model_version_id = %s;", (model_version_id,))


# --- assistant retrieval (BM25 + vector search) ---------------------------------------------------------

def test_vector_and_keyword_retrieval_never_return_another_companys_chunks(app_db, companies, admin_conn, monkeypatch):
    """Company B's chunk is the exact semantic match for the question and
    shares its keywords; Company A must still never retrieve it."""
    from src.ai.rag import embeddings, pipeline

    a, b = companies["a"], companies["b"]
    dim = 384
    query_vec = np.zeros(dim, dtype=np.float32); query_vec[0] = 1.0
    other_vec = np.zeros(dim, dtype=np.float32); other_vec[1] = 1.0
    cursor = admin_conn.cursor()
    chunk_ids = {}
    for key, text, vec in (("b", "supplier cost per kg confidential BETA-SECRET-SUPPLY", query_vec),
                           ("a", "opening hours and parking information", other_vec)):
        company = companies[key]
        document_id = str(uuid.uuid4())
        cursor.execute(
            """INSERT INTO rag_documents_metadata (document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes, processed_status)
               VALUES (%s, %s, 'doc.pdf', %s, 1024, 'Processed');""",
            (document_id, company["tenant_id"], f"uploads/{document_id}.pdf"),
        )
        cursor.execute(
            """INSERT INTO rag_document_chunks (tenant_id, document_id, chunk_index, chunk_text_content, embedding, embedding_model_version)
               VALUES (%s, %s, 0, %s, %s::vector, %s) RETURNING chunk_id;""",
            (company["tenant_id"], document_id, text, "[" + ",".join(str(float(x)) for x in vec) + "]", embeddings.MODEL_NAME),
        )
        chunk_ids[key] = str(cursor.fetchone()[0])

    monkeypatch.setattr(embeddings, "embed", lambda texts, model_name=None: np.stack([query_vec for _ in texts]))
    monkeypatch.setattr(embeddings, "try_embed", lambda texts, model_name=None: np.stack([query_vec for _ in texts]))
    question = "what is the supplier cost per kg confidential"

    def retrieved_ids(company):
        pipeline.invalidate_tenant_index_cache(company["tenant_id"])
        conn = app_db.dedicated_tenant_connection(company["tenant_id"], company["user_id"])
        try:
            index = pipeline.build_hybrid_index(conn, company["tenant_id"])
            return {chunk.chunk_id for chunk in pipeline.retrieve_hybrid(index, question, top_k=10)}
        finally:
            conn.rollback()
            conn.close()

    try:
        assert chunk_ids["b"] not in retrieved_ids(a)
        # The same search for the owner finds the chunk, so the check above can fail.
        assert chunk_ids["b"] in retrieved_ids(b)
        # A tenant id that doesn't match the connection's own context yields nothing.
        conn = app_db.dedicated_tenant_connection(a["tenant_id"], a["user_id"])
        try:
            index = pipeline.build_hybrid_index(conn, b["tenant_id"], use_cache=False)
            assert pipeline.retrieve_hybrid(index, question, top_k=10) == []
        finally:
            conn.rollback()
            conn.close()
    finally:
        for company in companies.values():
            pipeline.invalidate_tenant_index_cache(company["tenant_id"])


# --- billing status for a company the caller doesn't belong to ------------------------------------------

def test_subscription_status_says_nothing_about_a_company_the_caller_is_not_in(app_db, companies, monkeypatch):
    """A token naming a company its user isn't an active member of (a removed
    member's token that hasn't expired yet) must not learn, through the
    trial check on the billing service's own connection, whether that company
    has had a trial, a plan or a subscription."""
    from fastapi.testclient import TestClient

    from src.ai.core import security
    from src.ai.main import app

    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "false")
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")
    a, b = companies["a"], companies["b"]
    client = TestClient(app)

    def subscription(tenant_id, user_id):
        token, _ = security.create_access_token(tenant_id, user_id, email_verified=True)
        return client.get("/billing/subscription", headers={"Authorization": f"Bearer {token}"})

    # Company B has never had a trial: its own owner is offered one.
    own = subscription(b["tenant_id"], b["user_id"])
    assert own.status_code == 200 and own.json()["trialAvailable"] is True
    # A's owner holding a token for company B (a non-member) must not learn B's
    # trial eligibility: either the request is refused outright (membership is
    # enforced upstream), or it is served but never reveals eligibility as True.
    foreign = subscription(b["tenant_id"], a["user_id"])
    assert foreign.status_code in (401, 403) or (
        foreign.status_code == 200 and foreign.json().get("trialAvailable") is False
    ), f"non-member saw billing status: {foreign.status_code} {foreign.text[:200]}"
