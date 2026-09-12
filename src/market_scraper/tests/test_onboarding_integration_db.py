"""
Integration tests for data_access.py's onboarding functions -
register_self_service_data_source() and get_onboarding_status() - against
a real PostgreSQL instance. Same convention as every other
*_integration_db.py test in this package.
"""
import json
import os
import uuid

import psycopg2
import pytest
from cryptography.fernet import Fernet

from src.market_scraper.data_access import get_onboarding_status, load_source, register_self_service_data_source

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _local_kms_master_key(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", Fernet.generate_key().decode())


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def test_register_self_service_data_source_creates_an_immediately_allowed_row(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    actor_user_id = str(uuid.uuid4())

    source_id = register_self_service_data_source(
        conn, tenant_id, actor_user_id, "My POS Database", "db_connector",
        {"host": "db.example.com", "port": 5432, "dbname": "pos", "query": "SELECT 1", "field_mapping": {}},
    )

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT policy_status, collector_key, approved_by, approval_reference, is_active, "
            "approved_at IS NOT NULL, privacy_reviewed_at IS NOT NULL "
            "FROM data_sources WHERE tenant_id = %s AND source_id = %s;",
            (tenant_id, source_id),
        )
        row = cursor.fetchone()

    assert row[0] == "ALLOWED"  # self-service connections are auto-approved, not left pending
    assert row[1] == "db_connector"
    assert row[2] == actor_user_id  # the real acting user, never a placeholder
    assert row[3]  # a real, non-empty approval_reference
    assert row[4] is True
    assert row[5] is True
    assert row[6] is True


def test_register_self_service_data_source_stores_real_encrypted_credentials(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    source_id = register_self_service_data_source(
        conn, tenant_id, str(uuid.uuid4()), "My POS API", "api_connector",
        {"base_url": "https://pos.example.com", "field_mapping": {}},
        credentials={"api_key": "secret-token"},
    )

    loaded = load_source(conn, tenant_id, source_id)
    assert loaded["connection_credentials"] == {"api_key": "secret-token"}


def test_register_self_service_data_source_works_without_credentials(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    source_id = register_self_service_data_source(
        conn, tenant_id, str(uuid.uuid4()), "Public API", "api_connector",
        {"base_url": "https://public.example.com", "field_mapping": {}},
    )

    loaded = load_source(conn, tenant_id, source_id)
    assert loaded["connection_credentials"] == {}


def test_register_self_service_data_source_respects_sync_frequency(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    source_id = register_self_service_data_source(
        conn, tenant_id, str(uuid.uuid4()), "My DB", "db_connector",
        {"host": "x", "port": 5432, "dbname": "x", "query": "SELECT 1", "field_mapping": {}},
        sync_frequency_minutes=60,
    )

    with conn.cursor() as cursor:
        cursor.execute("SELECT sync_frequency_minutes FROM data_sources WHERE tenant_id = %s AND source_id = %s;", (tenant_id, source_id))
        assert cursor.fetchone()[0] == 60


def test_onboarding_status_reports_not_started_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    status = get_onboarding_status(conn, tenant_id)

    assert status["status"] == "not_started"
    assert status["connected_methods"] == []
    assert status["invoice_count"] == 0


def test_onboarding_status_reports_connected_after_registering_a_connector(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    register_self_service_data_source(
        conn, tenant_id, str(uuid.uuid4()), "My DB", "db_connector",
        {"host": "x", "port": 5432, "dbname": "x", "query": "SELECT 1", "field_mapping": {}},
    )

    status = get_onboarding_status(conn, tenant_id)

    assert status["status"] == "connected"
    assert status["connected_methods"] == ["db_connector"]


def test_onboarding_status_reports_connected_from_invoices_alone(conn):
    """A tenant who used Quick Sale, or whose upload never registered a
    formal data_sources row, must still report as genuinely connected -
    the real signal is "is there any data", not "is there a specific
    bookkeeping row"."""
    tenant_id = _insert_company(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invoices (tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
            "VALUES (%s, 'INV-1', NOW(), 10.0, 10.0, 'JOD');",
            (tenant_id,),
        )
    conn.commit()

    status = get_onboarding_status(conn, tenant_id)

    assert status["status"] == "connected"
    assert status["invoice_count"] == 1


def test_onboarding_status_ignores_inactive_sources(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    source_id = register_self_service_data_source(
        conn, tenant_id, str(uuid.uuid4()), "My DB", "db_connector",
        {"host": "x", "port": 5432, "dbname": "x", "query": "SELECT 1", "field_mapping": {}},
    )
    with conn.cursor() as cursor:
        cursor.execute("UPDATE data_sources SET is_active = FALSE WHERE tenant_id = %s AND source_id = %s;", (tenant_id, source_id))
    conn.commit()

    status = get_onboarding_status(conn, tenant_id)

    assert status["status"] == "not_started"
