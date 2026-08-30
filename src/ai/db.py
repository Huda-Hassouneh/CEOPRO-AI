"""
CEOPRO AI - Real ceopro_app connections with RLS session context set.

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
tests/test_rls_integration_db.py::_app_database_url()/_app_conn()) and sets
app.current_tenant_id/app.current_user_id via set_config(..., false) -
session-scoped, not SET LOCAL, matching the reasoning already recorded in
PENDING_ACTIONS.md #2 for this exact call shape (these connections are
short-lived per-request here, but the convention is kept consistent with the
long-lived-connection reasoning it was originally written against).
"""

import os
from urllib.parse import urlparse, urlunparse

import psycopg2
from minio import Minio


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


def app_role_connection(tenant_id: str, user_id: str) -> "psycopg2.extensions.connection":
    """
    Opens a connection as the restricted, non-superuser ceopro_app role (never
    ceopro_admin) with app.current_tenant_id/app.current_user_id set for this
    session, so every RLS policy on this connection actually scopes to the
    caller's tenant instead of running unrestricted.
    """
    connection = psycopg2.connect(_app_database_url())
    connection.autocommit = False
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id', %s, false);", (tenant_id,))
        cursor.execute("SELECT set_config('app.current_user_id', %s, false);", (user_id,))
    connection.commit()
    return connection


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
