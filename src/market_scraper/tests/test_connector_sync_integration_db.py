"""
Integration tests for connector_sync.py against a real PostgreSQL
instance for the PLATFORM's own database (companies/data_sources/
ingestion_jobs/products/etc.) - same convention as every other live-DB
test in this package. The CLIENT database connection (what a real
connector would poll) is mocked throughout (psycopg2.connect is patched
for connector_sync's own module, not for the platform conn fixture
below) - this verifies the scheduling/persistence/ingestion wiring, not
a real external database.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from cryptography.fernet import Fernet

from src.market_scraper.connector_sync import (
    DB_CONNECTOR_COLLECTOR_KEY, load_due_db_connector_sources, run_due_connector_syncs,
    sync_db_connector_source,
)
from src.market_scraper.data_access import set_source_credentials

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


def _insert_allowed_db_connector_source(
    conn, tenant_id: str, collector_config: dict, last_synced_at=None, sync_frequency_minutes=15,
) -> str:
    source_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO data_sources
                (source_id, tenant_id, source_name, source_type, collector_key,
                 collector_config, policy_status, is_active, last_synced_at, sync_frequency_minutes)
            VALUES (%s, %s, 'Client POS DB', 'DB_CONNECTOR', %s, %s::jsonb, 'ALLOWED', TRUE, %s, %s);
            """,
            (
                source_id, tenant_id, DB_CONNECTOR_COLLECTOR_KEY, json.dumps(collector_config),
                last_synced_at, sync_frequency_minutes,
            ),
        )
    conn.commit()
    return source_id


_VALID_CONFIG = {
    "host": "client-db.example", "port": 5432, "dbname": "pos",
    "query": "SELECT product_name, quantity, unit_price, currency, transaction_date FROM sales",
    "field_mapping": {
        "product_name": "product_name", "quantity": "quantity",
        "unit_price": "unit_price", "currency": "currency", "transaction_date": "transaction_date",
    },
}


def test_load_due_db_connector_sources_includes_a_never_synced_source(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_db_connector_source(conn, tenant_id, _VALID_CONFIG, last_synced_at=None)
    due = load_due_db_connector_sources(conn, tenant_id)
    assert [d["source_id"] for d in due] == [source_id]


def test_load_due_db_connector_sources_excludes_a_recently_synced_source(conn):
    tenant_id = _insert_company(conn)
    _insert_allowed_db_connector_source(
        conn, tenant_id, _VALID_CONFIG,
        last_synced_at=datetime.now(timezone.utc) - timedelta(minutes=1), sync_frequency_minutes=15,
    )
    assert load_due_db_connector_sources(conn, tenant_id) == []


def test_load_due_db_connector_sources_includes_an_overdue_source(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_db_connector_source(
        conn, tenant_id, _VALID_CONFIG,
        last_synced_at=datetime.now(timezone.utc) - timedelta(minutes=30), sync_frequency_minutes=15,
    )
    assert [d["source_id"] for d in load_due_db_connector_sources(conn, tenant_id)] == [source_id]


def test_sync_rejects_a_source_missing_required_config(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_db_connector_source(conn, tenant_id, {"host": "x"})  # missing most keys
    set_source_credentials(conn, tenant_id, source_id, {"user": "u", "password": "p"})
    with pytest.raises(ValueError, match="missing required key"):
        sync_db_connector_source(conn, tenant_id, source_id)


def test_sync_rejects_a_source_missing_credentials(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_db_connector_source(conn, tenant_id, _VALID_CONFIG)
    # no set_source_credentials() call at all
    with pytest.raises(ValueError, match="must include 'user' and 'password'"):
        sync_db_connector_source(conn, tenant_id, source_id)


def _fake_client_connection(rows):
    """A fake psycopg2 connection standing in for the real client database
    - real network calls to an arbitrary client's DB are not something a
    unit test should ever attempt."""
    fake_cursor = MagicMock()
    fake_cursor.__enter__ = MagicMock(return_value=fake_cursor)
    fake_cursor.__exit__ = MagicMock(return_value=False)
    fake_cursor.description = [("product_name",), ("quantity",), ("unit_price",), ("currency",), ("transaction_date",)]
    fake_cursor.fetchall.return_value = rows
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor
    return fake_conn


def test_sync_processes_real_rows_and_advances_the_watermark(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_db_connector_source(conn, tenant_id, _VALID_CONFIG, last_synced_at=None)
    set_source_credentials(conn, tenant_id, source_id, {"user": "readonly_user", "password": "s3cret"})

    fake_client_conn = _fake_client_connection([
        ("Espresso Machine", 2, 45.5, "JOD", "2026-09-10"),
    ])

    with patch("src.market_scraper.connector_sync.psycopg2.connect", return_value=fake_client_conn) as mock_connect:
        result = sync_db_connector_source(conn, tenant_id, source_id)

    # Connected with the real config/credentials, never the platform's own conn
    mock_connect.assert_called_once_with(
        host="client-db.example", port=5432, dbname="pos",
        user="readonly_user", password="s3cret", connect_timeout=15,
    )
    fake_client_conn.set_session.assert_called_once_with(readonly=True)
    fake_client_conn.close.assert_called_once()

    assert result["rows_processed"] >= 0  # real ingestion_pipeline result, not a stub
    assert result["source_id"] == source_id

    with conn.cursor() as cursor:
        cursor.execute("SELECT last_synced_at FROM data_sources WHERE tenant_id = %s AND source_id = %s;", (tenant_id, source_id))
        last_synced_at = cursor.fetchone()[0]
    assert last_synced_at is not None  # watermark advanced on success

    with conn.cursor() as cursor:
        cursor.execute("SELECT job_status FROM ingestion_jobs WHERE tenant_id = %s AND job_id = %s;", (tenant_id, result["job_id"]))
        assert cursor.fetchone()[0] == "COMPLETED"


def test_sync_does_not_advance_the_watermark_on_a_client_connection_failure(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_db_connector_source(conn, tenant_id, _VALID_CONFIG, last_synced_at=None)
    set_source_credentials(conn, tenant_id, source_id, {"user": "u", "password": "wrong"})

    with patch("src.market_scraper.connector_sync.psycopg2.connect", side_effect=RuntimeError("connection refused")):
        with pytest.raises(RuntimeError, match="connection refused"):
            sync_db_connector_source(conn, tenant_id, source_id)

    with conn.cursor() as cursor:
        cursor.execute("SELECT last_synced_at FROM data_sources WHERE tenant_id = %s AND source_id = %s;", (tenant_id, source_id))
        assert cursor.fetchone()[0] is None  # never advanced - this sync must be retried, not skipped


def test_run_due_connector_syncs_continues_past_one_sources_failure(conn):
    tenant_id = _insert_company(conn)
    bad_source_id = _insert_allowed_db_connector_source(conn, tenant_id, {"host": "x"})  # invalid config
    set_source_credentials(conn, tenant_id, bad_source_id, {"user": "u", "password": "p"})
    good_source_id = _insert_allowed_db_connector_source(conn, tenant_id, _VALID_CONFIG)
    set_source_credentials(conn, tenant_id, good_source_id, {"user": "u", "password": "p"})

    fake_client_conn = _fake_client_connection([])
    with patch("src.market_scraper.connector_sync.psycopg2.connect", return_value=fake_client_conn):
        results = run_due_connector_syncs(conn, tenant_id)

    by_source = {r["source_id"]: r for r in results}
    assert "error" in by_source[bad_source_id]
    assert "error" not in by_source[good_source_id]
