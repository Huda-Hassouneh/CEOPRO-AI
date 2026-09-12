"""
Integration tests for api_connector_sync.py against a real PostgreSQL
instance for the PLATFORM's own database - same convention as
test_connector_sync_integration_db.py. The CLIENT's REST API is mocked
throughout (httpx.get is patched for api_connector_sync's own module,
not for the platform conn fixture below) - this verifies the scheduling/
persistence/ingestion wiring, not a real external vendor API.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from cryptography.fernet import Fernet

from src.market_scraper.api_connector_sync import (
    API_CONNECTOR_COLLECTOR_KEY, load_due_api_connector_sources, run_due_api_connector_syncs,
    sync_api_connector_source,
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


def _insert_allowed_api_connector_source(
    conn, tenant_id: str, collector_config: dict, last_synced_at=None, sync_frequency_minutes=15,
) -> str:
    """Same chk_allowed_source_has_approval reasoning as
    test_connector_sync_integration_db.py's identical fixture."""
    source_id = str(uuid.uuid4())
    approved_by = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO data_sources
                (source_id, tenant_id, source_name, source_type, collector_key,
                 collector_config, policy_status, is_active, last_synced_at, sync_frequency_minutes,
                 approval_reference, approved_by, approved_at, privacy_reviewed_at)
            VALUES (%s, %s, 'Client POS API', 'API_CONNECTOR', %s, %s::jsonb, 'ALLOWED', TRUE, %s, %s,
                    'test-fixture-approval', %s, %s, %s);
            """,
            (
                source_id, tenant_id, API_CONNECTOR_COLLECTOR_KEY, json.dumps(collector_config),
                last_synced_at, sync_frequency_minutes, approved_by, now, now,
            ),
        )
    conn.commit()
    return source_id


_VALID_CONFIG = {
    "base_url": "https://pos.example.com/api/sales",
    "field_mapping": {"name": "product_name", "qty": "quantity", "price": "unit_price"},
}


def test_load_due_api_connector_sources_includes_a_never_synced_source(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_api_connector_source(conn, tenant_id, _VALID_CONFIG, last_synced_at=None)
    due = load_due_api_connector_sources(conn, tenant_id)
    assert [d["source_id"] for d in due] == [source_id]


def test_load_due_api_connector_sources_excludes_a_recently_synced_source(conn):
    tenant_id = _insert_company(conn)
    _insert_allowed_api_connector_source(
        conn, tenant_id, _VALID_CONFIG,
        last_synced_at=datetime.now(timezone.utc) - timedelta(minutes=1), sync_frequency_minutes=15,
    )
    assert load_due_api_connector_sources(conn, tenant_id) == []


def test_sync_rejects_a_source_missing_required_config(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_api_connector_source(conn, tenant_id, {"base_url": "https://x.example"})  # missing field_mapping
    with pytest.raises(ValueError, match="missing required key"):
        sync_api_connector_source(conn, tenant_id, source_id)


def _fake_api_response(records):
    response = MagicMock()
    response.json.return_value = records
    response.raise_for_status = MagicMock()
    return response


def test_sync_processes_real_rows_and_advances_the_watermark(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_api_connector_source(conn, tenant_id, _VALID_CONFIG, last_synced_at=None)
    set_source_credentials(conn, tenant_id, source_id, {"api_key": "secret-token"})

    page_1 = _fake_api_response([{"name": "Espresso Machine", "qty": 2, "price": 45.5}])
    page_2 = _fake_api_response([])

    with patch("src.market_scraper.api_connector_sync.httpx.get", side_effect=[page_1, page_2]) as mock_get:
        result = sync_api_connector_source(conn, tenant_id, source_id)

    first_call_headers = mock_get.call_args_list[0].kwargs["headers"]
    assert first_call_headers == {"Authorization": "Bearer secret-token"}

    assert result["rows_processed"] >= 0
    assert result["source_id"] == source_id

    with conn.cursor() as cursor:
        cursor.execute("SELECT last_synced_at FROM data_sources WHERE tenant_id = %s AND source_id = %s;", (tenant_id, source_id))
        assert cursor.fetchone()[0] is not None  # watermark advanced on success

    with conn.cursor() as cursor:
        cursor.execute("SELECT job_status FROM ingestion_jobs WHERE tenant_id = %s AND job_id = %s;", (tenant_id, result["job_id"]))
        assert cursor.fetchone()[0] == "COMPLETED"


def test_sync_does_not_advance_the_watermark_on_a_request_failure(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_allowed_api_connector_source(conn, tenant_id, _VALID_CONFIG, last_synced_at=None)

    with patch("src.market_scraper.api_connector_sync.httpx.get", side_effect=RuntimeError("connection refused")):
        with pytest.raises(RuntimeError, match="connection refused"):
            sync_api_connector_source(conn, tenant_id, source_id)

    with conn.cursor() as cursor:
        cursor.execute("SELECT last_synced_at FROM data_sources WHERE tenant_id = %s AND source_id = %s;", (tenant_id, source_id))
        assert cursor.fetchone()[0] is None

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT job_status FROM ingestion_jobs WHERE tenant_id = %s ORDER BY started_at DESC LIMIT 1;",
            (tenant_id,),
        )
        assert cursor.fetchone()[0] == "FAILED"


def test_run_due_api_connector_syncs_continues_past_one_sources_failure(conn):
    tenant_id = _insert_company(conn)
    bad_source_id = _insert_allowed_api_connector_source(conn, tenant_id, {"base_url": "https://x.example"})
    good_source_id = _insert_allowed_api_connector_source(conn, tenant_id, _VALID_CONFIG)

    with patch("src.market_scraper.api_connector_sync.httpx.get", return_value=_fake_api_response([])):
        results = run_due_api_connector_syncs(conn, tenant_id)

    by_source = {r["source_id"]: r for r in results}
    assert "error" in by_source[bad_source_id]
    assert "error" not in by_source[good_source_id]
