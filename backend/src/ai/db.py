"""
KEEL - Pooled, real ceopro_app connections with RLS transaction
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
from urllib.parse import quote, urlparse, urlunparse

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
    # parsed.port is None whenever DATABASE_URL omits an explicit port -
    # exactly Neon's standard copy-paste format (postgresql://user:pass@
    # ep-xxx.aws.neon.tech/db?sslmode=require, no ":5432"). Falling back to
    # Postgres's own default here avoids literally embedding the string
    # "None" as the port in the reconstructed DSN (a real, reproduced bug:
    # psycopg2 then raises OperationalError, "invalid integer value \"None\"
    # for connection option \"port\""). Every local/docker-compose
    # DATABASE_URL already includes ":5432" explicitly, which is why this
    # never surfaced against the local Postgres instance.
    port = parsed.port or 5432
    # Passwords are arbitrary secrets; encode URL-reserved characters before rebuilding the DSN.
    encoded_password = quote(app_password, safe="")
    netloc = f"ceopro_app:{encoded_password}@{parsed.hostname}:{port}"
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


class _UnpooledOwner:
    """Lets a PooledTenantConnection own a private socket: 'returning' it
    closes it instead of handing it back to the request pool."""

    def putconn(self, raw_conn, discard: bool = False) -> None:
        raw_conn.close()


def dedicated_tenant_connection(tenant_id: str, user_id: str) -> PooledTenantConnection:
    """A tenant-scoped ceopro_app connection outside the request pool, with
    the same RLS context handling. For long background work (forecast
    refreshes) so it can never starve requests of pooled connections."""
    import psycopg2

    raw = psycopg2.connect(_app_database_url())
    return PooledTenantConnection(_UnpooledOwner(), raw, tenant_id, user_id)


def close_pool() -> None:
    """Real shutdown hook, wired into main.py's lifespan - closes every
    pooled connection cleanly on process exit instead of leaving sockets
    to time out on their own. A no-op if the pool was never created (a
    process that never actually handled a tenant-scoped request, e.g. a
    health-check-only run) - TenantConnectionPool.closeall() is a real
    Postgres round-trip per connection, not something to do speculatively."""
    global _POOL
    if _POOL is not None:
        _POOL.closeall()
        _POOL = None


def system_connection():
    """
    An unpooled connection as the schema-owning role, for the few trusted
    system writes no tenant may make about itself: the billing service
    recording a verified Stripe event, starting a company's one free
    trial, and operator scripts. Never use it for anything a request's
    own input decides on its own - those paths go through
    app_role_connection() and row-level security.
    """
    import psycopg2

    return psycopg2.connect(_admin_database_url())


def auth_lookup_connection():
    """
    A plain, unpooled ceopro_app connection with NO tenant/user context set -
    used ONLY by POST /auth/login, which by definition doesn't know either
    one yet. Deliberately not routed through app_role_connection()/the pool
    above: that call requires tenant_id/user_id up front to set SET LOCAL,
    which a pre-authentication request structurally cannot supply.

    Still connects as the restricted ceopro_app role, never ceopro_admin -
    this connection can only do anything useful via the SECURITY DEFINER
    functions in migration 20260915020000_add_auth_lookup_functions.sql
    (auth_lookup_user_by_email/auth_lookup_user_memberships), which are the
    one narrow, auditable exception to "no RLS-bypassing reads from
    application code" this service otherwise holds to everywhere else -
    see that migration's own docstring for why a login flow genuinely
    needs it and why a SECURITY DEFINER function is the safe way to grant
    it, rather than reintroducing the superuser-bypasses-RLS anti-pattern
    this whole module exists to have fixed.

    Login is low-volume relative to every other endpoint here, so a fresh
    connection per attempt (rather than its own dedicated pool) is a
    reasonable, simple choice - not a corner cut, a right-sized one.
    """
    import psycopg2

    return psycopg2.connect(_app_database_url())


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
