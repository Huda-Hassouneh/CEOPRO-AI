"""
Integration tests for db_pool.py against a REAL PostgreSQL instance,
connecting as the actual restricted ceopro_app role (never the superuser) -
same convention and same reason as test_rls_integration_db.py's own
docstring: RLS provides zero protection when verified only against a
superuser connection, so these tests need the real, restricted role to
mean anything at all.

This is the actual safety proof for the production-hardening audit's
connection-pooling fix: pooling is only safe here because RLS context is
set via SET LOCAL (transaction-scoped), which Postgres guarantees cannot
survive a transaction boundary - not because application code is
disciplined about resetting it. These tests drive that mechanism with
REAL concurrent threads sharing a REAL, deliberately tiny pool (so the
same underlying socket is provably forced to serve different tenants
back to back), not just sequential calls on one connection, which could
never have exercised a genuine reuse race.

Skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD are both set.
"""

import json
import os
import threading
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.infrastructure.db_pool import TenantConnectionPool

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB pooling integration test",
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


def _ensure_role_key(cursor) -> str:
    cursor.execute("SELECT role_key FROM system_roles LIMIT 1;")
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES ('OWNER', 'Owner');")
    return "OWNER"


def _insert_tenant_with_active_user(cursor, label: str):
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
        (tenant_id, f"Pool Test Co {label}"),
    )
    cursor.execute(
        "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', %s);",
        (user_id, f"{label}-{user_id}@example.com", label),
    )
    role_key = _ensure_role_key(cursor)
    cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role_key))
    return tenant_id, user_id


@pytest.fixture
def two_tenant_setup(admin_conn):
    cursor = admin_conn.cursor()
    tenant_a, user_a = _insert_tenant_with_active_user(cursor, "A")
    tenant_b, user_b = _insert_tenant_with_active_user(cursor, "B")
    product_a, product_b = str(uuid.uuid4()), str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 10.00, 'JOD');",
        (product_a, tenant_a, json.dumps({"en": "A Widget"})),
    )
    cursor.execute(
        "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 10.00, 'JOD');",
        (product_b, tenant_b, json.dumps({"en": "B Widget"})),
    )
    return {
        "tenant_a": tenant_a, "user_a": user_a, "product_a": product_a,
        "tenant_b": tenant_b, "user_b": user_b, "product_b": product_b,
    }


def _visible_products(conn, product_a, product_b):
    with conn.cursor() as cursor:
        cursor.execute("SELECT product_id FROM products WHERE product_id IN (%s, %s);", (product_a, product_b))
        return {r[0] for r in cursor.fetchall()}


def test_pool_reuses_the_same_socket_across_different_tenants_safely(two_tenant_setup):
    """
    maxconn=1 forces the exact same underlying connection to serve
    tenant A's request, then tenant B's - the real scenario pooling
    exists for, and the one a session-scoped SET would have gotten
    dangerously wrong.
    """
    pool = TenantConnectionPool(_app_database_url(), minconn=1, maxconn=1)
    try:
        conn_a = pool.get_tenant_connection(two_tenant_setup["tenant_a"], two_tenant_setup["user_a"])
        raw_a = conn_a._raw
        seen_a = _visible_products(conn_a, two_tenant_setup["product_a"], two_tenant_setup["product_b"])
        conn_a.close()  # returns the ONLY connection in this pool back to it

        conn_b = pool.get_tenant_connection(two_tenant_setup["tenant_b"], two_tenant_setup["user_b"])
        assert conn_b._raw is raw_a  # proves this is genuinely the same socket, not a fresh one
        seen_b = _visible_products(conn_b, two_tenant_setup["product_a"], two_tenant_setup["product_b"])
        conn_b.close()

        assert seen_a == {two_tenant_setup["product_a"]}
        assert seen_b == {two_tenant_setup["product_b"]}  # no leftover context from tenant A's turn
    finally:
        pool.closeall()


def test_context_stays_correctly_scoped_across_multiple_commits_on_one_connection():
    """
    Real proof against an actual transaction boundary: main.py's upload
    endpoint commits more than once on the same connection within one
    request. Each commit ends the SET LOCAL's transaction - this proves
    the wrapper's re-apply-after-commit actually keeps working against
    real Postgres, not just the mocked cursor in test_db_pool.py.
    """
    pool = TenantConnectionPool(_app_database_url(), minconn=1, maxconn=1)
    try:
        admin = psycopg2.connect(ADMIN_DATABASE_URL)
        admin.autocommit = True
        cursor = admin.cursor()
        tenant_id, user_id = _insert_tenant_with_active_user(cursor, "MultiCommit")
        admin.close()

        conn = pool.get_tenant_connection(tenant_id, user_id)
        try:
            for i in range(3):
                product_id = str(uuid.uuid4())
                with conn.cursor() as c:
                    c.execute(
                        "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
                        "VALUES (%s, %s, %s, 10.00, 'JOD');",
                        (product_id, tenant_id, json.dumps({"en": f"Product {i}"})),
                    )
                conn.commit()  # ends this transaction - context must survive for the NEXT iteration's INSERT

            with conn.cursor() as c:
                c.execute("SELECT COUNT(*) FROM products WHERE tenant_id = %s;", (tenant_id,))
                assert c.fetchone()[0] == 3  # all three inserts succeeded under RLS, none silently rejected
        finally:
            conn.close()
    finally:
        pool.closeall()


def test_closing_mid_transaction_does_not_leak_context_to_the_next_borrower(two_tenant_setup):
    """
    A caller that never commits/rolls back before close() (a bug, or a
    crash mid-request) must not leave the next, unrelated checkout - a
    DIFFERENT tenant's request - inheriting an open transaction or its
    RLS context.
    """
    pool = TenantConnectionPool(_app_database_url(), minconn=1, maxconn=1)
    try:
        conn_a = pool.get_tenant_connection(two_tenant_setup["tenant_a"], two_tenant_setup["user_a"])
        with conn_a.cursor() as c:
            c.execute("SELECT product_id FROM products WHERE tenant_id = %s;", (two_tenant_setup["tenant_a"],))
            c.fetchall()  # a real statement inside an open transaction, never committed
        conn_a.close()  # must roll back before returning to the pool

        conn_b = pool.get_tenant_connection(two_tenant_setup["tenant_b"], two_tenant_setup["user_b"])
        seen_b = _visible_products(conn_b, two_tenant_setup["product_a"], two_tenant_setup["product_b"])
        conn_b.close()

        assert seen_b == {two_tenant_setup["product_b"]}
    finally:
        pool.closeall()


def test_concurrent_pooled_requests_for_different_tenants_never_cross_leak(two_tenant_setup):
    """
    The real stress test: many real threads hammering a small (but >1,
    so real concurrent checkouts happen, not just sequential reuse of
    one socket) pool, half claiming to be tenant A and half tenant B,
    each verifying it only ever sees its own product. Any cross-tenant
    leak under real concurrency would show up here as a wrong product_id
    on at least one iteration - this ran clean, not "no crash occurred",
    is the actual bar for this test to be considered proof.

    maxconn=4 against 8 threads deliberately forces real reuse pressure
    (fewer sockets than concurrent callers) rather than each thread
    getting its own dedicated connection - get_tenant_connection()'s own
    checkout retry (see db_pool.py) absorbs the resulting brief
    PoolError bursts instead of threads dying outright, confirmed by
    this exact test surfacing that gap for real before the retry existed.
    """
    pool = TenantConnectionPool(_app_database_url(), minconn=2, maxconn=4)
    errors = []
    iterations_per_thread = 25

    def _worker(tenant_id, user_id, own_product_id, other_product_id):
        for _ in range(iterations_per_thread):
            conn = pool.get_tenant_connection(tenant_id, user_id)
            try:
                seen = _visible_products(conn, own_product_id, other_product_id)
                if seen != {own_product_id}:
                    errors.append(f"tenant {tenant_id} saw {seen}, expected only {{{own_product_id}}}")
                conn.commit()
            finally:
                conn.close()

    threads = [
        threading.Thread(
            target=_worker,
            args=(
                two_tenant_setup["tenant_a"], two_tenant_setup["user_a"],
                two_tenant_setup["product_a"], two_tenant_setup["product_b"],
            ),
        )
        for _ in range(4)
    ] + [
        threading.Thread(
            target=_worker,
            args=(
                two_tenant_setup["tenant_b"], two_tenant_setup["user_b"],
                two_tenant_setup["product_b"], two_tenant_setup["product_a"],
            ),
        )
        for _ in range(4)
    ]

    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        pool.closeall()

    assert errors == []
