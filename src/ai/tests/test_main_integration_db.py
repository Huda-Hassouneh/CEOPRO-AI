"""
Integration test for src/ai/main.py's /extraction/upload endpoint against
a real Postgres + MinIO - the actual end-to-end path this session verified
manually via curl before writing this permanent test. Skipped unless
AI_TEST_DATABASE_URL/APP_DB_PASSWORD/AI_TEST_MINIO_ENDPOINT are all set,
same convention as the rest of this suite's live-infra tests.

Exercises the real ceopro_app/RLS connection path (db.app_role_connection),
a real data_sources/ingestion_jobs find-or-create, a real MinIO write, and
confirms the canonical template genuinely round-trips as
is_template_compliant=True with 0% data loss through the actual running
FastAPI app - not a mock standing in for any of it.
"""
import os
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")
# Bare host:port, matching test_rag_integration.py's own established
# AI_TEST_MINIO_ENDPOINT convention (it passes this straight to Minio()
# with no scheme) - db.minio_client() wants a scheme-prefixed URL instead
# (matching .env.example's MINIO_ENDPOINT=http://localhost:9000), so the
# _env fixture below adds "http://" when setting MINIO_ENDPOINT for it,
# rather than assuming the two env vars share one literal format.
MINIO_ENDPOINT = os.getenv("AI_TEST_MINIO_ENDPOINT")
MINIO_ROOT_USER = os.getenv("AI_TEST_MINIO_ROOT_USER", "minio_admin")
MINIO_ROOT_PASSWORD = os.getenv("AI_TEST_MINIO_ROOT_PASSWORD")
JWT_SECRET = "test-jwt-secret-for-integration-tests"

pytestmark = pytest.mark.skipif(
    not (DATABASE_URL and APP_DB_PASSWORD and MINIO_ENDPOINT and MINIO_ROOT_PASSWORD),
    reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD/AI_TEST_MINIO_ENDPOINT/AI_TEST_MINIO_ROOT_PASSWORD not all set",
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    # monkeypatch, not raw os.environ mutation - reverted automatically
    # after each test, so this can't leak into other test files' MinIO
    # client construction later in the same pytest session (a real bug
    # this session found and fixed: an earlier raw-os.environ version of
    # this fixture broke test_rag_integration.py by leaving a
    # scheme-prefixed MINIO_ENDPOINT set globally).
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("APP_DB_PASSWORD", APP_DB_PASSWORD)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("MINIO_ENDPOINT", f"http://{MINIO_ENDPOINT}")
    monkeypatch.setenv("MINIO_ROOT_USER", MINIO_ROOT_USER)
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", MINIO_ROOT_PASSWORD)


@pytest.fixture
def client():
    # Imported after _env sets JWT_SECRET - main.py's get_tenant_context
    # reads it from the environment at call time, not import time, so this
    # ordering isn't strictly required, but keeps intent obvious.
    from src.ai.main import app
    return TestClient(app)


@pytest.fixture
def admin_conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture
def seeded_tenant(admin_conn):
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, 'Upload Endpoint Test Co', 'JO', 'JOD');",
            (tenant_id,),
        )
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'Test User');",
            (user_id, f"{user_id}@example.com"),
        )
        cursor.execute("SELECT role_key FROM system_roles LIMIT 1;")
        row = cursor.fetchone()
        role_key = row[0] if row else "OWNER"
        if not row:
            cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES ('OWNER', 'Owner');")
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);",
            (tenant_id, user_id, role_key),
        )
    token = jwt.encode({"tenant_id": tenant_id, "user_id": user_id}, JWT_SECRET, algorithm="HS256")
    return tenant_id, {"Authorization": f"Bearer {token}"}


_TEMPLATE_CSV = (
    b"product_name,quantity,unit_price,currency,transaction_date\n"
    b"Widget A,5,19.99,JOD,2026-08-30\n"
)
_PARTIAL_CSV = (
    b"product_name,quantity,unit_price,currency,transaction_date\n"
    b"Widget A,-3,19.99,JOD,2026-08-30\n"
)


def test_uploading_the_canonical_template_is_verified_zero_loss(client, admin_conn, seeded_tenant):
    tenant_id, headers = seeded_tenant

    response = client.post(
        "/extraction/upload", files={"file": ("upload.csv", _TEMPLATE_CSV, "text/csv")}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["template_mode"] == "TEMPLATE_COMPLIANT"
    assert body["is_template_compliant"] is True
    assert body["rows_processed"] == 1
    assert body["rows_partial"] == 0
    assert body["data_loss_pct"] == 0.0
    assert body["minio_object_key"] is not None

    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT validation_status FROM import_staging_rows WHERE tenant_id = %s;", (tenant_id,)
        )
        assert cursor.fetchone()[0] == "VALID"
        cursor.execute("SELECT job_status FROM ingestion_jobs WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == "COMPLETED"


def test_uploading_a_row_with_one_bad_field_reports_partial_not_full_loss(client, admin_conn, seeded_tenant):
    tenant_id, headers = seeded_tenant

    response = client.post(
        "/extraction/upload", files={"file": ("upload.csv", _PARTIAL_CSV, "text/csv")}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_template_compliant"] is False
    assert body["rows_partial"] == 1
    assert body["rows_failed"] == 0
    assert "quantity" in body["row_outcomes"][0]["field_errors"]

    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT validation_status, validation_errors FROM import_staging_rows WHERE tenant_id = %s;", (tenant_id,)
        )
        status, errors = cursor.fetchone()
        assert status == "PARTIAL"
        assert "quantity" in errors


def test_repeat_uploads_reuse_the_same_data_source_not_duplicate_it(client, admin_conn, seeded_tenant):
    tenant_id, headers = seeded_tenant

    client.post("/extraction/upload", files={"file": ("a.csv", _TEMPLATE_CSV, "text/csv")}, headers=headers)
    client.post("/extraction/upload", files={"file": ("b.csv", _TEMPLATE_CSV, "text/csv")}, headers=headers)

    with admin_conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM data_sources WHERE tenant_id = %s AND source_type = 'CSV_UPLOAD';", (tenant_id,)
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM ingestion_jobs WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 2
