"""
Integration tests for connector_worker.py - the real running process
that finally calls connector_sync.py's/api_connector_sync.py's own sync
logic on a schedule (see that module's own docstring for why neither had
ever actually been wired into anything before this).

discover_tenants_with_connectors() is tested against a REAL PostgreSQL
instance with the SCRAPER_DATABASE_URL/SCRAPER_ACTOR_USER_ID pooled
connection this worker actually uses in production - the part that
specifically needs genuine live-DB proof (the whole point is proving the
SECURITY DEFINER grant lets the restricted ceopro_app role see across
tenants for this one call; mocking it would defeat that). The per-tenant
sync orchestration (run_connector_syncs_for_tenant()/run_once()) mocks
connector_sync.run_due_connector_syncs()/api_connector_sync.
run_due_api_connector_syncs() directly - their own real DB behavior is
already covered by their own dedicated test files; this file only tests
connector_worker.py's OWN new logic (isolating one connector type's
failure from the other, one tenant's failure from another's).
"""
import os
import uuid
from unittest.mock import patch

import psycopg2
import pytest

from src.market_scraper import connector_worker, data_access

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
SCRAPER_DATABASE_URL = os.getenv("SCRAPER_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not SCRAPER_DATABASE_URL,
    reason="AI_TEST_DATABASE_URL and/or SCRAPER_DATABASE_URL not set - skipping live-DB integration test",
)


@pytest.fixture
def admin_conn():
    connection = psycopg2.connect(ADMIN_DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _scraper_env(monkeypatch):
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "00000000-0000-0000-0000-000000000000")


@pytest.fixture(autouse=True)
def _reset_pool_singleton():
    data_access._POOL = None
    yield
    data_access._POOL = None


def _insert_active_connector(admin_conn, collector_key: str) -> str:
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    approved_by = str(uuid.uuid4())
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO data_sources
                (source_id, tenant_id, source_name, source_type, collector_key, is_active,
                 policy_status, approval_reference, approved_by, approved_at, privacy_reviewed_at)
            VALUES (%s, %s, 'Test Connector', 'TEST', %s, TRUE, 'ALLOWED', 'test-approval', %s, NOW(), NOW());
            """,
            (source_id, tenant_id, collector_key, approved_by),
        )
    return tenant_id


def test_discover_tenants_with_connectors_finds_a_real_active_source(admin_conn):
    tenant_id = _insert_active_connector(admin_conn, connector_worker.connector_sync.DB_CONNECTOR_COLLECTOR_KEY)

    discovered = connector_worker.discover_tenants_with_connectors()

    assert tenant_id in discovered


def test_discover_tenants_with_connectors_finds_api_connector_sources_too(admin_conn):
    tenant_id = _insert_active_connector(admin_conn, connector_worker.api_connector_sync.API_CONNECTOR_COLLECTOR_KEY)

    discovered = connector_worker.discover_tenants_with_connectors()

    assert tenant_id in discovered


def test_discover_tenants_with_connectors_excludes_an_inactive_source(admin_conn):
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    approved_by = str(uuid.uuid4())
    with admin_conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO data_sources
                (source_id, tenant_id, source_name, source_type, collector_key, is_active,
                 policy_status, approval_reference, approved_by, approved_at, privacy_reviewed_at)
            VALUES (%s, %s, 'Test Connector', 'TEST', %s, FALSE, 'ALLOWED', 'test-approval', %s, NOW(), NOW());
            """,
            (source_id, tenant_id, connector_worker.connector_sync.DB_CONNECTOR_COLLECTOR_KEY, approved_by),
        )

    discovered = connector_worker.discover_tenants_with_connectors()

    assert tenant_id not in discovered


def test_run_connector_syncs_for_tenant_runs_both_connector_types_independently(admin_conn):
    tenant_id = _insert_active_connector(admin_conn, connector_worker.connector_sync.DB_CONNECTOR_COLLECTOR_KEY)

    with patch("src.market_scraper.connector_worker.connector_sync.run_due_connector_syncs", return_value=[{"source_id": "s1"}]) as mock_db, \
         patch("src.market_scraper.connector_worker.api_connector_sync.run_due_api_connector_syncs", return_value=[{"source_id": "s2"}]) as mock_api:
        result = connector_worker.run_connector_syncs_for_tenant(tenant_id)

    mock_db.assert_called_once()
    mock_api.assert_called_once()
    assert mock_db.call_args.args[1] == tenant_id
    assert mock_api.call_args.args[1] == tenant_id
    assert result == {"db_connector": [{"source_id": "s1"}], "api_connector": [{"source_id": "s2"}]}


def test_run_connector_syncs_for_tenant_isolates_db_connector_failure_from_api_connector(admin_conn):
    """A crash in the whole DB-connector batch (not just one source within
    it - see run_due_connector_syncs()'s own per-source isolation) must
    never prevent the API-connector batch from running for the same
    tenant, and vice versa."""
    tenant_id = _insert_active_connector(admin_conn, connector_worker.connector_sync.DB_CONNECTOR_COLLECTOR_KEY)

    with patch("src.market_scraper.connector_worker.connector_sync.run_due_connector_syncs", side_effect=RuntimeError("boom")), \
         patch("src.market_scraper.connector_worker.api_connector_sync.run_due_api_connector_syncs", return_value=[{"source_id": "s2"}]) as mock_api:
        result = connector_worker.run_connector_syncs_for_tenant(tenant_id)

    mock_api.assert_called_once()  # still ran despite the DB-connector batch crashing
    assert "error" in result["db_connector"][0]
    assert result["api_connector"] == [{"source_id": "s2"}]


def test_run_once_isolates_one_tenants_failure_from_another(admin_conn):
    tenant_a = _insert_active_connector(admin_conn, connector_worker.connector_sync.DB_CONNECTOR_COLLECTOR_KEY)
    tenant_b = _insert_active_connector(admin_conn, connector_worker.connector_sync.DB_CONNECTOR_COLLECTOR_KEY)

    def fake_run_for_tenant(tenant_id):
        if tenant_id == tenant_a:
            raise RuntimeError("tenant A blew up")
        return {"db_connector": [], "api_connector": []}

    with patch("src.market_scraper.connector_worker.run_connector_syncs_for_tenant", side_effect=fake_run_for_tenant):
        results = connector_worker.run_once()

    assert "error" in results[tenant_a]
    assert results[tenant_b] == {"db_connector": [], "api_connector": []}
