"""
Integration test for Final_schema.sql's Row-Level Security architecture
against a real PostgreSQL instance - same convention as test_integration_db.py:
skipped unless AI_TEST_DATABASE_URL is set. Also needs APP_DB_PASSWORD, since
these tests connect as the actual restricted `ceopro_app` role (not the
superuser `ceopro_admin` every other integration test in this suite uses) -
RLS provides zero protection against a superuser regardless of policy
correctness, so a superuser connection can't verify any of this.

This file exists because of a real, serious bug this exact testing found:
get_current_tenant() (SECURITY INVOKER by default) queries tenant_users,
which is itself RLS-protected by a policy that calls get_current_tenant()
again - infinite recursion, crashing every RLS-scoped query issued by a
non-superuser role with "stack depth limit exceeded" the instant real tenant
context was set. Invisible all session because every prior verification
connected as the superuser ceopro_admin, which bypasses RLS (and therefore
never evaluates the recursive policy) entirely. Fixed in
migrations/20260827060000_fix_get_current_tenant_recursion.sql by marking the
function SECURITY DEFINER (runs as the function's owner - a superuser -
instead of the calling role, so its internal tenant_users lookup bypasses
RLS instead of re-entering it).
"""

import json
import os
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB RLS integration test",
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


def _insert_user(cursor, label: str) -> str:
    user_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', %s);",
        (user_id, f"{label}-{user_id}@example.com", label),
    )
    return user_id


def _ensure_role_key(cursor) -> str:
    cursor.execute("SELECT role_key FROM system_roles LIMIT 1;")
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES ('OWNER', 'Owner');")
    return "OWNER"


@pytest.fixture
def two_tenant_setup(admin_conn):
    """
    Seeds two tenants, one active member each, one product each, plus a
    removed (revoked) membership on tenant_a - all inserted as the
    superuser admin role, which bypasses RLS entirely for the seed writes.
    """
    cursor = admin_conn.cursor()
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'RLS Test Co A', 'JO', 'JOD');",
        (tenant_a,),
    )
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'RLS Test Co B', 'JO', 'JOD');",
        (tenant_b,),
    )
    role_key = _ensure_role_key(cursor)
    user_a = _insert_user(cursor, "user-a")
    user_b = _insert_user(cursor, "user-b")
    removed_user = _insert_user(cursor, "removed-user")
    cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_a, user_a, role_key))
    cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_b, user_b, role_key))
    cursor.execute(
        "INSERT INTO tenant_users (tenant_id, user_id, role_key, removed_at) VALUES (%s, %s, %s, NOW());",
        (tenant_a, removed_user, role_key),
    )
    product_a = str(uuid.uuid4())
    product_b = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 10.00, 'JOD');",
        (product_a, tenant_a, json.dumps({"en": "A Widget"})),
    )
    cursor.execute(
        "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 10.00, 'JOD');",
        (product_b, tenant_b, json.dumps({"en": "B Widget"})),
    )
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "removed_user": removed_user,
        "product_a": product_a,
        "product_b": product_b,
    }


def _app_conn(tenant_id: str = None, user_id: str = None):
    connection = psycopg2.connect(_app_database_url())
    connection.autocommit = True
    cursor = connection.cursor()
    if tenant_id:
        cursor.execute("SELECT set_config('app.current_tenant_id', %s, false);", (tenant_id,))
    if user_id:
        cursor.execute("SELECT set_config('app.current_user_id', %s, false);", (user_id,))
    return connection, cursor


def test_ceopro_app_role_is_not_superuser_and_does_not_bypass_rls(admin_conn):
    cursor = admin_conn.cursor()
    cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'ceopro_app';")
    rolsuper, rolbypassrls = cursor.fetchone()
    assert rolsuper is False
    assert rolbypassrls is False


def test_app_role_with_no_tenant_context_sees_nothing(two_tenant_setup):
    """Fails closed: the AI pipeline today never sets these session vars at
    all, so this is what a ceopro_app connection actually sees right now."""
    conn, cursor = _app_conn()
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert cursor.fetchall() == []
    finally:
        conn.close()


def test_app_role_scoped_to_tenant_a_sees_only_tenant_a(two_tenant_setup):
    conn, cursor = _app_conn(two_tenant_setup["tenant_a"], two_tenant_setup["user_a"])
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert [r[0] for r in cursor.fetchall()] == [two_tenant_setup["product_a"]]
    finally:
        conn.close()


def test_app_role_scoped_to_tenant_b_sees_only_tenant_b(two_tenant_setup):
    conn, cursor = _app_conn(two_tenant_setup["tenant_b"], two_tenant_setup["user_b"])
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert [r[0] for r in cursor.fetchall()] == [two_tenant_setup["product_b"]]
    finally:
        conn.close()


def test_revoked_membership_loses_tenant_context(two_tenant_setup):
    """removed_at being set is what tenant_users.removed_at is for - a
    revoked user must not keep isolated access just because the session
    variables still claim their old tenant."""
    conn, cursor = _app_conn(two_tenant_setup["tenant_a"], two_tenant_setup["removed_user"])
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert cursor.fetchall() == []
    finally:
        conn.close()


def test_claiming_a_tenant_youre_not_a_member_of_sees_nothing(two_tenant_setup):
    """user_a is a real, active member of tenant_a - but not tenant_b.
    Session variables alone must not be enough to claim tenant_b's context."""
    conn, cursor = _app_conn(two_tenant_setup["tenant_b"], two_tenant_setup["user_a"])
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert cursor.fetchall() == []
    finally:
        conn.close()


def test_service_actor_sees_only_the_tenant_its_connection_is_scoped_to(two_tenant_setup):
    """
    Real, previously-broken behavior this covers: migrations/20260928000000_
    fix_service_actor_tenant_context.sql. The nil UUID
    (00000000-0000-0000-0000-000000000000) is the fixed service-principal
    identity market_scraper/data_access.py::get_tenant_connection() and
    src/ai/forecasting/consumer.py's pooled connections open as (see
    backend/.env.example's own comment: "User/service-principal UUID that
    is an active tenant member; required by RLS") - but no tenant_users
    row for it was ever actually inserted for ANY tenant (deliberately -
    see the migration's own docstring for why that would have leaked a
    fake "team member" into every tenant's Settings > Team page instead).
    Before the fix, get_current_tenant() returned NULL for this UUID on
    every tenant, exactly as if no context had been set at all -
    discover_for_tenant() raised outright on its own companies lookup,
    reproduced directly against a real, freshly-uploaded product before
    this fix existed. It must now see exactly the one tenant its own
    connection is scoped to via SET LOCAL - not both, not neither.
    """
    service_actor_id = "00000000-0000-0000-0000-000000000000"
    conn, cursor = _app_conn(two_tenant_setup["tenant_a"], service_actor_id)
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert [r[0] for r in cursor.fetchall()] == [two_tenant_setup["product_a"]]
    finally:
        conn.close()

    conn, cursor = _app_conn(two_tenant_setup["tenant_b"], service_actor_id)
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert [r[0] for r in cursor.fetchall()] == [two_tenant_setup["product_b"]]
    finally:
        conn.close()


def test_service_actor_with_no_tenant_context_still_sees_nothing(two_tenant_setup):
    """The exemption is scoped to 'trust this identity for whatever single
    tenant SET LOCAL already claims' - never unconditional/global access
    regardless of context, which would be a real cross-tenant hole."""
    service_actor_id = "00000000-0000-0000-0000-000000000000"
    conn, cursor = _app_conn(user_id=service_actor_id)
    try:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
        assert cursor.fetchall() == []
    finally:
        conn.close()


def test_admin_superuser_still_bypasses_rls_entirely(admin_conn, two_tenant_setup):
    """Documents the separate, already-tracked gap (PENDING_ACTIONS.md #25):
    every DB-touching codepath that exists today connects via DATABASE_URL
    built from the superuser POSTGRES_USER (docker-compose.yml's `migrate`
    service is the only service that sets DATABASE_URL at all - there is no
    `ai`/`backend` service yet), so today, in practice, RLS provides no
    isolation regardless of how correct the policies themselves are. This
    test isn't asserting desired behavior - it's a tripwire: if this ever
    starts failing, something changed ceopro_admin's superuser status, which
    would be worth knowing about too."""
    cursor = admin_conn.cursor()
    cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (two_tenant_setup["product_a"], two_tenant_setup["product_b"]))
    rows = {r[0] for r in cursor.fetchall()}
    assert rows == {two_tenant_setup["product_a"], two_tenant_setup["product_b"]}


def test_chk_evidence_shape_rejects_empty_non_forecast_row(admin_conn, two_tenant_setup):
    cursor = admin_conn.cursor()
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            "INSERT INTO evidence_records (tenant_id, forecast_id, metric_name) VALUES (%s, NULL, NULL);",
            (two_tenant_setup["tenant_a"],),
        )


def test_chk_review_subject_consistency_rejects_product_with_competitor_id(admin_conn, two_tenant_setup):
    cursor = admin_conn.cursor()
    competitor_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id) VALUES (%s, 'Rival', 'PRIVATE', %s);",
        (competitor_id, two_tenant_setup["tenant_a"]),
    )
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            "INSERT INTO reviews (tenant_id, subject_type, product_id, competitor_id, review_text, source_platform) "
            "VALUES (%s, 'PRODUCT', %s, %s, 'text', 'GOOGLE');",
            (two_tenant_setup["tenant_a"], two_tenant_setup["product_a"], competitor_id),
        )


def test_uq_competitor_private_allows_same_name_across_different_tenants(admin_conn, two_tenant_setup):
    """Only a same-tenant duplicate should collide - the same competitor
    name legitimately exists for many different tenants independently."""
    cursor = admin_conn.cursor()
    cursor.execute(
        "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id) VALUES (%s, 'Shared Rival Name', 'PRIVATE', %s);",
        (str(uuid.uuid4()), two_tenant_setup["tenant_a"]),
    )
    cursor.execute(
        "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id) VALUES (%s, 'Shared Rival Name', 'PRIVATE', %s);",
        (str(uuid.uuid4()), two_tenant_setup["tenant_b"]),
    )


def test_tenant_b_cannot_see_tenant_a_private_competitor(two_tenant_setup, admin_conn):
    cursor = admin_conn.cursor()
    competitor_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id) VALUES (%s, 'Tenant A Only Rival', 'PRIVATE', %s);",
        (competitor_id, two_tenant_setup["tenant_a"]),
    )
    conn, app_cursor = _app_conn(two_tenant_setup["tenant_b"], two_tenant_setup["user_b"])
    try:
        app_cursor.execute("SELECT competitor_name FROM global_competitors WHERE global_competitor_id = %s;", (competitor_id,))
        assert app_cursor.fetchall() == []
    finally:
        conn.close()


def test_soft_deleting_a_product_as_the_app_role_succeeds(two_tenant_setup):
    """
    Regression test for a real, 100%-reproducible bug: routers/products.py::
    delete_product() soft-deletes via `UPDATE products SET deleted_at =
    NOW() ...` - every unit test for it (test_products.py) mocks the DB
    connection, so none of them ever ran this against real RLS as the
    restricted ceopro_app role. Doing so here reproduced
    "new row violates row-level security policy for table products" on
    every single call, before migrations/20260920000000_fix_products_
    soft_delete_rls.sql: select_products_isolated's own USING clause
    required deleted_at IS NULL, and Postgres checks that same SELECT
    policy against the UPDATE's resulting new row - independent of
    update_products_isolated's own USING/WITH CHECK (confirmed directly:
    even a fully permissive UPDATE policy still hit this error). The row
    becoming soft-deleted made it fail its own visibility policy the
    instant the UPDATE tried to write it.
    """
    conn, app_cursor = _app_conn(two_tenant_setup["tenant_a"], two_tenant_setup["user_a"])
    try:
        app_cursor.execute(
            "UPDATE products SET deleted_at = NOW() WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL RETURNING product_id;",
            (two_tenant_setup["tenant_a"], two_tenant_setup["product_a"]),
        )
        assert app_cursor.fetchall() == [(two_tenant_setup["product_a"],)]

        # Soft-deleted rows must still be invisible to a normal, explicitly-
        # filtered read (the application-level "deliberately redundant with
        # RLS" filter products.py's own docstring describes) - the fix must
        # not accidentally make deleted rows readable again.
        app_cursor.execute(
            "SELECT product_id FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
            (two_tenant_setup["tenant_a"], two_tenant_setup["product_a"]),
        )
        assert app_cursor.fetchall() == []
    finally:
        conn.close()


# --- RAG tables (rag_documents_metadata / rag_document_chunks) -------------
#
# The RAG Business Copilot audit found these two tables use the identical
# RLS policy pattern as products/every other tenant-scoped table, but had
# no table-specific regression test proving it - only inferred from the
# generic mechanism test above. These close that gap directly: a citation
# leaking another tenant's document title/path/chunk text would be a real
# security incident, not just a wrong answer, so this is proven here
# rather than left as an inference from a different table's test.

@pytest.fixture
def two_tenant_rag_documents(admin_conn, two_tenant_setup):
    """One RAG document + one chunk each for tenant_a and tenant_b,
    inserted as the superuser admin role (bypasses RLS for the seed,
    same convention as two_tenant_setup's own product rows)."""
    cursor = admin_conn.cursor()
    doc_a, doc_b = str(uuid.uuid4()), str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO rag_documents_metadata (document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes) "
        "VALUES (%s, %s, 'tenant-a-secret.pdf', 'a/secret.pdf', 100);",
        (doc_a, two_tenant_setup["tenant_a"]),
    )
    cursor.execute(
        "INSERT INTO rag_documents_metadata (document_id, tenant_id, file_name, storage_bucket_path, file_size_bytes) "
        "VALUES (%s, %s, 'tenant-b-secret.pdf', 'b/secret.pdf', 100);",
        (doc_b, two_tenant_setup["tenant_b"]),
    )
    cursor.execute(
        "INSERT INTO rag_document_chunks (tenant_id, document_id, chunk_index, chunk_text_content) "
        "VALUES (%s, %s, 0, 'Tenant A confidential chunk text.');",
        (two_tenant_setup["tenant_a"], doc_a),
    )
    cursor.execute(
        "INSERT INTO rag_document_chunks (tenant_id, document_id, chunk_index, chunk_text_content) "
        "VALUES (%s, %s, 0, 'Tenant B confidential chunk text.');",
        (two_tenant_setup["tenant_b"], doc_b),
    )
    return {**two_tenant_setup, "doc_a": doc_a, "doc_b": doc_b}


def test_rag_documents_metadata_scoped_to_tenant_a_never_sees_tenant_b(two_tenant_rag_documents):
    conn, cursor = _app_conn(two_tenant_rag_documents["tenant_a"], two_tenant_rag_documents["user_a"])
    try:
        cursor.execute(
            "SELECT document_id, file_name FROM rag_documents_metadata WHERE document_id IN (%s, %s);",
            (two_tenant_rag_documents["doc_a"], two_tenant_rag_documents["doc_b"]),
        )
        rows = cursor.fetchall()
        assert [r[1] for r in rows] == ["tenant-a-secret.pdf"]
    finally:
        conn.close()


def test_rag_document_chunks_scoped_to_tenant_a_never_sees_tenant_b_chunk_text(two_tenant_rag_documents):
    """The concrete failure this proves against: a citation or retrieved
    passage that leaks another tenant's document content/title/path."""
    conn, cursor = _app_conn(two_tenant_rag_documents["tenant_a"], two_tenant_rag_documents["user_a"])
    try:
        cursor.execute("SELECT tenant_id, chunk_text_content FROM rag_document_chunks;")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "Tenant A confidential chunk text."
    finally:
        conn.close()


def test_rag_document_chunks_with_no_tenant_context_sees_nothing(two_tenant_rag_documents):
    """Same fail-closed behavior as products' own no-context test above -
    proven separately for this table since it's the one citations/
    retrieval actually read from."""
    conn, cursor = _app_conn()
    try:
        cursor.execute("SELECT chunk_id FROM rag_document_chunks;")
        assert cursor.fetchall() == []
    finally:
        conn.close()


def test_rag_data_access_load_tenant_chunks_respects_tenant_isolation(two_tenant_rag_documents):
    """The actual application-layer function the retrieval pipeline
    calls (rag/data_access.py::load_tenant_chunks) - proves isolation at
    the real call site the chatbot uses, not just the raw table."""
    from src.ai.rag.data_access import load_tenant_chunks

    conn, _cursor = _app_conn(two_tenant_rag_documents["tenant_a"], two_tenant_rag_documents["user_a"])
    try:
        chunks = load_tenant_chunks(conn, two_tenant_rag_documents["tenant_a"])
        assert len(chunks) == 1
        assert chunks[0][1] == "Tenant A confidential chunk text."
    finally:
        conn.close()
