"""
CEOPRO AI - Pooled, real ceopro_app connections with RLS transaction
context set.

Every DB-touching codepath in src/ai/ before this file existed read
DATABASE_URL directly - which, per docker-compose.yml/.env.example, resolves
to the superuser ceopro_admin. Superusers unconditionally bypass Row-Level
Security regardless of policy correctness (PENDING_ACTIONS.md #2/#25), so in
practice RLS provided zero tenant isolation in the deployed system: the
policies were correct (and regression-tested, test_rls_integration_db.py) but
nothing ever connected as the restricted ceopro_app role to exercise them.

This module is main.py's one call site for opening a real per-request
connection: swaps DATABASE_URL's credentials for ceopro_app/APP_DB_PASSWORD
(the exact pattern already proven in
tests/test_rls_integration_db.py::_app_database_url()/_app_conn()).

Production-hardening audit follow-up: this used to open a brand-new
psycopg2.connect() per call and set app.current_tenant_id/app.current_user_id
via a SESSION-scoped set_config(..., is_local=false) - correct only because
each connection was single-use (opened fresh, closed once per request).
Now backed by a real connection pool (src/infrastructure/db_pool.py) for the
real latency/concurrency win pooling gives - see that module's own docstring
for the full reasoning on why session-scoped context would have been a real
cross-tenant leak risk under pooling, and why transaction-scoped SET LOCAL
(via set_config(..., is_local=true), re-applied after every commit/rollback)
is what makes reusing connections across different tenants' requests safe.
No caller needs to change: app_role_connection() still returns something
that duck-types a plain psycopg2 connection (cursor()/commit()/rollback()/
close()) exactly as before.
"""

import os
from typing import Optional
from urllib.parse import urlparse, urlunparse

from minio import Minio

from src.infrastructure.db_pool import PooledTenantConnection, TenantConnectionPool

_POOL: Optional[TenantConnectionPool] = None


def _admin_database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return db_url


def _app_database_url() -> str:
    app_password = os.getenv("APP_DB_PASSWORD")
    if not app_password:
        raise RuntimeError("APP_DB_PASSWORD environment variable is not set.")
    parsed = urlparse(_admin_database_url())
    netloc = f"ceopro_app:{app_password}@{parsed.hostname}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _get_pool() -> TenantConnectionPool:
    """
    Created lazily on first real use, not at import time - importing this
    module must never require a reachable database, exactly as before this
    change. A single pool for this process's whole lifetime: this module is
    only ever imported by long-lived server/worker processes (main.py's
    FastAPI app, forecasting/consumer.py), never a short one-shot script
    that would want to tear a pool down immediately after.
    """
    global _POOL
    if _POOL is None:
        minconn = int(os.getenv("APP_DB_POOL_MIN_SIZE", "1"))
        maxconn = int(os.getenv("APP_DB_POOL_MAX_SIZE", "10"))
        _POOL = TenantConnectionPool(_app_database_url(), minconn=minconn, maxconn=maxconn)
    return _POOL


def app_role_connection(tenant_id: str, user_id: str) -> PooledTenantConnection:
    """
    Returns a pooled connection as the restricted, non-superuser ceopro_app
    role (never ceopro_admin) with app.current_tenant_id/app.current_user_id
    set via SET LOCAL for the current transaction, so every RLS policy on
    this connection actually scopes to the caller's tenant instead of
    running unrestricted - and stays correctly scoped across however many
    commits the caller makes on it (see PooledTenantConnection's own
    docstring), even though the underlying socket may have served a
    different tenant's request before this one.
    """
    return _get_pool().get_tenant_connection(tenant_id, user_id)


def minio_client() -> Minio:
    """
    MINIO_ROOT_USER/MINIO_ROOT_PASSWORD (.env.example) - there is no
    restricted, non-root MinIO service account today, unlike ceopro_app for
    Postgres. Root credentials for a bucket-scoped upload endpoint is a real,
    known gap (matches this repo's own convention of flagging what's not
    ideal rather than silently using it as if it were fine) - genuinely
    the only working MinIO credential in this repo until a scoped
    IAM policy/user is set up, which is infra work, not this call site's to
    invent unilaterally.
    """
    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ROOT_USER")
    secret_key = os.getenv("MINIO_ROOT_PASSWORD")
    if not endpoint or not access_key or not secret_key:
        raise RuntimeError("MINIO_ENDPOINT/MINIO_ROOT_USER/MINIO_ROOT_PASSWORD must all be set.")

    parsed = urlparse(endpoint)
    secure = parsed.scheme == "https"
    host = parsed.netloc or parsed.path  # netloc empty if endpoint had no scheme at all
    return Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
