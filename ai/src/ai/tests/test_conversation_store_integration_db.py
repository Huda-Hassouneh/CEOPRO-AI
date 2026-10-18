"""
Integration tests for rag/conversation_store.py against a real PostgreSQL
instance - same convention as every other live-DB test in this package
(skipped unless AI_TEST_DATABASE_URL is set). Covers both the plain
CRUD-level behavior (admin connection, no RLS) and real tenant+user
isolation (a live ceopro_app-role connection, matching
test_business_copilot_tools_tenant_isolation.py's own pattern).
"""
import json
import os
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.rag import conversation_store
from src.ai.tests.test_rls_integration_db import _ensure_role_key, _insert_user

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB integration test",
)


def _app_database_url() -> str:
    parsed = urlparse(ADMIN_DATABASE_URL)
    netloc = f"ceopro_app:{APP_DB_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


@pytest.fixture
def admin_conn():
    connection = psycopg2.connect(ADMIN_DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture
def two_users_two_tenants(admin_conn):
    """Two tenants, one active user each - enough to prove both tenant
    AND user isolation (a second user in tenant A would only prove
    tenant isolation, not that conversations are ALSO private within a
    tenant between different users)."""
    cursor = admin_conn.cursor()
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    for tenant_id, name in [(tenant_a, "Conv Test Co A"), (tenant_b, "Conv Test Co B")]:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, name),
        )
    role_key = _ensure_role_key(cursor)
    user_a = _insert_user(cursor, "conv-user-a")
    user_b = _insert_user(cursor, "conv-user-b")
    for user_id, tenant_id in [(user_a, tenant_a), (user_b, tenant_b)]:
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role_key))
    return {"tenant_a": tenant_a, "tenant_b": tenant_b, "user_a": user_a, "user_b": user_b}


def _set_context(connection, tenant_id: str, user_id: str):
    cursor = connection.cursor()
    cursor.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
    cursor.execute("SELECT set_config('app.current_user_id', %s, true);", (user_id,))


def _app_conn(tenant_id: str, user_id: str):
    connection = psycopg2.connect(_app_database_url())
    connection.autocommit = False
    _set_context(connection, tenant_id, user_id)
    return connection


def test_create_session_and_append_and_load_round_trips(two_users_two_tenants):
    fixture = two_users_two_tenants
    conn = _app_conn(fixture["tenant_a"], fixture["user_a"])
    try:
        session_id = conversation_store.create_session(conn, fixture["tenant_a"], fixture["user_a"], "What is my best-selling product?")
        conversation_store.append_message(conn, fixture["tenant_a"], session_id, fixture["user_a"], "user", "What is my best-selling product?")
        conversation_store.append_message(conn, fixture["tenant_a"], session_id, fixture["user_a"], "assistant", "Widget X.", sources=[{"chunk_id": "c1", "score": 0.9}])
        conn.commit()
        # SET LOCAL is transaction-scoped - commit() ends that transaction,
        # so the tenant/user context must be re-applied before the next
        # statement, same as db_pool.py::PooledTenantConnection does for
        # real in production (this raw test connection doesn't get that
        # automatically).
        _set_context(conn, fixture["tenant_a"], fixture["user_a"])

        history = conversation_store.load_session_history(conn, fixture["tenant_a"], session_id)
        assert history == [
            {"role": "user", "content": "What is my best-selling product?"},
            {"role": "assistant", "content": "Widget X."},
        ]

        display = conversation_store.load_session_messages_for_display(conn, fixture["tenant_a"], session_id)
        assert len(display) == 2
        assert display[1]["sources"] == [{"chunk_id": "c1", "score": 0.9}]
    finally:
        conn.rollback()
        conn.close()


def test_session_title_derived_from_first_message_and_truncated():
    long_message = "x" * 200
    assert conversation_store._derive_title(long_message).endswith("...")
    assert len(conversation_store._derive_title(long_message)) == conversation_store._TITLE_MAX_LENGTH + 3
    assert conversation_store._derive_title("short question") == "short question"


def test_list_sessions_orders_most_recently_active_first(two_users_two_tenants):
    fixture = two_users_two_tenants
    conn = _app_conn(fixture["tenant_a"], fixture["user_a"])
    try:
        session_1 = conversation_store.create_session(conn, fixture["tenant_a"], fixture["user_a"], "first session")
        conn.commit()
        _set_context(conn, fixture["tenant_a"], fixture["user_a"])
        session_2 = conversation_store.create_session(conn, fixture["tenant_a"], fixture["user_a"], "second session")
        conn.commit()
        _set_context(conn, fixture["tenant_a"], fixture["user_a"])
        # Touch session_1 again so it becomes the most recently active.
        conversation_store.append_message(conn, fixture["tenant_a"], session_1, fixture["user_a"], "user", "a follow-up")
        conn.commit()
        _set_context(conn, fixture["tenant_a"], fixture["user_a"])

        sessions = conversation_store.list_sessions(conn, fixture["tenant_a"], fixture["user_a"])
        session_ids_in_order = [s["session_id"] for s in sessions]
        assert session_ids_in_order.index(session_1) < session_ids_in_order.index(session_2)
    finally:
        conn.rollback()
        conn.close()


def test_session_exists_is_false_for_a_random_id(two_users_two_tenants):
    fixture = two_users_two_tenants
    conn = _app_conn(fixture["tenant_a"], fixture["user_a"])
    try:
        assert conversation_store.session_exists(conn, fixture["tenant_a"], str(uuid.uuid4())) is False
    finally:
        conn.rollback()
        conn.close()


# --- Tenant + user isolation (the real security property this table exists to have) ---

def test_tenant_b_cannot_see_tenant_a_session(two_users_two_tenants):
    fixture = two_users_two_tenants
    conn_a = _app_conn(fixture["tenant_a"], fixture["user_a"])
    try:
        session_id = conversation_store.create_session(conn_a, fixture["tenant_a"], fixture["user_a"], "tenant A's private question")
        conn_a.commit()
    finally:
        conn_a.close()

    conn_b = _app_conn(fixture["tenant_b"], fixture["user_b"])
    try:
        assert conversation_store.session_exists(conn_b, fixture["tenant_b"], session_id) is False
        assert conversation_store.load_session_history(conn_b, fixture["tenant_b"], session_id) == []
        assert conversation_store.list_sessions(conn_b, fixture["tenant_b"], fixture["user_b"]) == []
    finally:
        conn_b.rollback()
        conn_b.close()


def test_tenant_b_appending_to_tenant_as_session_id_silently_affects_nothing(two_users_two_tenants):
    """Real RLS behavior worth locking in explicitly: an UPDATE/INSERT
    referencing a session_id that doesn't belong to this connection's own
    tenant+user is not an error - it's a no-op (RLS makes the target row
    invisible to begin with) - proving there is no way to graft a message
    onto someone else's conversation even by guessing/knowing their
    session_id."""
    fixture = two_users_two_tenants
    conn_a = _app_conn(fixture["tenant_a"], fixture["user_a"])
    try:
        session_id = conversation_store.create_session(conn_a, fixture["tenant_a"], fixture["user_a"], "tenant A's private question")
        conn_a.commit()
    finally:
        conn_a.close()

    conn_b = _app_conn(fixture["tenant_b"], fixture["user_b"])
    try:
        with pytest.raises(Exception):
            # The message row itself would violate the FK to
            # conversation_sessions(tenant_id, session_id) - tenant B's
            # RLS-scoped view of that table has no row with tenant_a's
            # session_id, so the FK cannot be satisfied. This IS the
            # security property under test: the write is rejected outright.
            conversation_store.append_message(conn_b, fixture["tenant_b"], session_id, fixture["user_b"], "user", "trying to graft onto tenant A's conversation")
    finally:
        conn_b.rollback()
        conn_b.close()


def test_user_b_in_tenant_a_cannot_see_user_as_own_session(two_users_two_tenants, admin_conn):
    """Within the SAME tenant, a second user must not see the first
    user's conversations either - conversation privacy is per-user, not
    just per-tenant (unlike products/competitors, which are shared
    company data)."""
    fixture = two_users_two_tenants
    cursor = admin_conn.cursor()
    role_key = _ensure_role_key(cursor)
    user_c = _insert_user(cursor, "conv-user-c-same-tenant-as-a")
    cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (fixture["tenant_a"], user_c, role_key))

    conn_a = _app_conn(fixture["tenant_a"], fixture["user_a"])
    try:
        session_id = conversation_store.create_session(conn_a, fixture["tenant_a"], fixture["user_a"], "user A's private question")
        conn_a.commit()
    finally:
        conn_a.close()

    conn_c = _app_conn(fixture["tenant_a"], user_c)
    try:
        assert conversation_store.session_exists(conn_c, fixture["tenant_a"], session_id) is False
        assert conversation_store.list_sessions(conn_c, fixture["tenant_a"], user_c) == []
    finally:
        conn_c.rollback()
        conn_c.close()


def test_load_session_history_respects_the_limit(two_users_two_tenants):
    fixture = two_users_two_tenants
    conn = _app_conn(fixture["tenant_a"], fixture["user_a"])
    try:
        session_id = conversation_store.create_session(conn, fixture["tenant_a"], fixture["user_a"], "bounded history test")
        for i in range(5):
            conversation_store.append_message(conn, fixture["tenant_a"], session_id, fixture["user_a"], "user", f"message {i}")
        conn.commit()
        _set_context(conn, fixture["tenant_a"], fixture["user_a"])

        history = conversation_store.load_session_history(conn, fixture["tenant_a"], session_id, limit=2)
        assert len(history) == 2
        # Must be the 2 MOST RECENT messages, still in oldest-first order.
        assert history[0]["content"] == "message 3"
        assert history[1]["content"] == "message 4"
    finally:
        conn.rollback()
        conn.close()
