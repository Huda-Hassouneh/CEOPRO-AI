"""
Live-DB regression test for connection-pool exhaustion under concurrent,
fully SUCCESSFUL /extraction/upload requests - distinct from db_pool.py's
own construction-failure leak (fixed separately, see test_db_pool.py's
test_get_tenant_connection_returns_the_connection_on_*). Even a leak-free
pool can be driven into psycopg2.pool.PoolError if each request holds its
pooled connection for longer than the Postgres work it actually needs.

extraction_upload() used to check out its connection BEFORE writing the
uploaded file to a temp path and parsing it (pure file I/O/CPU work - the
size of a real xlsx makes this non-instant, and it never touches
Postgres), and released it only AFTER publishing the downstream discovery
event (a Redis xadd, also not Postgres). Under concurrent uploads, that
needlessly extends how long each request occupies one of only maxconn
pooled connections - reproduced here directly against a real, deliberately
tiny pool, with zero injected failures anywhere in the request.

Same convention as test_db_pool_integration_db.py: skipped unless
AI_TEST_DATABASE_URL and APP_DB_PASSWORD are both set.
"""
import io
import os
import threading
import time
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai import db
from src.ai.core.security import TenantContext
from src.ai.extraction import file_dispatch
from src.ai.routers import extraction
from src.infrastructure.db_pool import TenantConnectionPool

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB pool-lifecycle integration test",
)


def _app_database_url() -> str:
    parsed = urlparse(ADMIN_DATABASE_URL)
    netloc = f"ceopro_app:{APP_DB_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _insert_tenant_with_active_user(cursor, label: str):
    """Same shape as test_db_pool_integration_db.py's own helper - each
    live-DB test file seeds its own minimal fixtures independently."""
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
        (tenant_id, f"Pool Lifecycle Test Co {label}"),
    )
    cursor.execute(
        "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', %s);",
        (user_id, f"{label}-{user_id}@example.com", label),
    )
    cursor.execute("SELECT role_key FROM system_roles LIMIT 1;")
    row = cursor.fetchone()
    if row:
        role_key = row[0]
    else:
        role_key = "OWNER"
        cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES ('OWNER', 'Owner');")
    cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role_key))
    return tenant_id, user_id


@pytest.fixture
def four_tenants():
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    cursor = admin.cursor()
    tenants = [_insert_tenant_with_active_user(cursor, str(i)) for i in range(4)]
    admin.close()
    return tenants


class _FakeUploadFile:
    """Duck-types exactly what extraction_upload() actually reads off the
    UploadFile it receives (.filename, .file.read(...)) - avoids any
    FastAPI/Starlette UploadFile construction quirks across versions."""

    def __init__(self, filename, content: bytes):
        self.filename = filename
        self.file = io.BytesIO(content)


_CSV = b"product_name,quantity,unit_price,currency,transaction_date\nWidget,1,10.00,JOD,2026-09-27\n"


def _run_uploads_concurrently(tenants, pre_db_delay_seconds, start_stagger_seconds, on_pre_db_work=None):
    """
    Fires one real extraction_upload() call per tenant (direct Python
    call, not over HTTP - bypasses FastAPI's own dependency injection,
    which isn't the thing under test here), staggered by
    start_stagger_seconds, each with an artificial pre_db_delay_seconds
    delay injected into file parsing - simulating real, non-instant file
    I/O/CPU work that has nothing to do with Postgres. Returns the list
    of exceptions raised, in tenant order (None where a call succeeded).
    """
    results = [None] * len(tenants)
    real_read_source_file = file_dispatch.read_source_file

    def _slow_read_source_file(*args, **kwargs):
        if on_pre_db_work is not None:
            on_pre_db_work()
        time.sleep(pre_db_delay_seconds)
        return real_read_source_file(*args, **kwargs)

    original_read_source_file = extraction.file_dispatch.read_source_file
    original_minio_client = db.minio_client
    extraction.file_dispatch.read_source_file = _slow_read_source_file
    db.minio_client = lambda: None  # this test is about the Postgres pool only

    def _worker(index, tenant_id, user_id):
        time.sleep(start_stagger_seconds * index)
        ctx = TenantContext(tenant_id, user_id)
        file = _FakeUploadFile("products.csv", _CSV)
        try:
            extraction.extraction_upload(file=file, ctx=ctx)
        except Exception as exc:  # noqa: BLE001 - capturing for the assertion below
            results[index] = exc

    try:
        threads = [threading.Thread(target=_worker, args=(i, t, u)) for i, (t, u) in enumerate(tenants)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        extraction.file_dispatch.read_source_file = original_read_source_file
        db.minio_client = original_minio_client

    return results


def test_concurrent_successful_uploads_do_not_exhaust_a_tiny_pool(four_tenants, monkeypatch):
    """
    Four requests, arriving 0.05s apart, each with 0.25s of file work
    before touching Postgres, against a pool with only 2 connections.
    None of them does anything wrong, so all four must succeed.

    The bug this guards against: the connection used to be checked out
    BEFORE the file work, so every request held one through its whole
    0.25s delay and the 3rd/4th found the pool empty. That is asserted
    directly - no request holds a pool connection while it parses the
    file - rather than inferred from timing, which made this test flaky
    when the machine was busy (a request's own short Postgres phase could
    overlap two others by chance). The pool may wait up to 2s for a
    connection, so such incidental overlap is tolerated; the old bug
    would still fail the "held during file work" check every time.
    """
    pool = TenantConnectionPool(
        _app_database_url(), minconn=1, maxconn=2,
        checkout_wait_seconds=2,
    )
    held, held_lock, held_during_file_work = {}, threading.Lock(), []
    real_checkout, real_return = pool._checkout, pool._return

    def _checkout():
        conn = real_checkout()
        with held_lock:
            held[threading.get_ident()] = held.get(threading.get_ident(), 0) + 1
        return conn

    def _return(raw_conn, close):
        with held_lock:
            held[threading.get_ident()] = held.get(threading.get_ident(), 0) - 1
        real_return(raw_conn, close)

    def _record_connections_held_by_this_request():
        with held_lock:
            held_during_file_work.append(held.get(threading.get_ident(), 0))

    pool._checkout, pool._return = _checkout, _return
    monkeypatch.setattr(db, "_POOL", pool)
    try:
        results = _run_uploads_concurrently(four_tenants, pre_db_delay_seconds=0.25, start_stagger_seconds=0.05,
                                            on_pre_db_work=_record_connections_held_by_this_request)
    finally:
        pool.closeall()

    assert held_during_file_work == [0, 0, 0, 0], f"a request held a pool connection during file work: {held_during_file_work}"
    assert results == [None, None, None, None], f"expected all four uploads to succeed with no exceptions, got: {results}"
