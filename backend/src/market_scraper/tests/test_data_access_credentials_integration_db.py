"""
Integration test for data_access.py::set_source_credentials against a
real PostgreSQL instance. Skipped unless AI_TEST_DATABASE_URL is set,
same convention as every other *_integration_db.py test in this package.
"""
import json
import os
import uuid

import psycopg2
import pytest
from cryptography.fernet import Fernet

from src.market_scraper.data_access import load_source, set_source_credentials

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
    """set_source_credentials()/load_source() now encrypt/decrypt through
    credential_vault.py's default (local) KMS backend, which requires a
    real Fernet master key - set one for the duration of each test here
    rather than in every test function."""
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


def _insert_source(conn, tenant_id: str) -> str:
    source_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) "
            "VALUES (%s, %s, 'Apify Test Source', 'WEB_SCRAPE');",
            (source_id, tenant_id),
        )
    return source_id


def test_set_credentials_then_load_source_round_trips_real_json(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_source(conn, tenant_id)

    set_source_credentials(conn, tenant_id, source_id, {"api_token": "apify-real-token-123"})

    loaded = load_source(conn, tenant_id, source_id)
    assert loaded["connection_credentials"] == {"api_token": "apify-real-token-123"}


def test_set_credentials_overwrites_a_previous_value(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_source(conn, tenant_id)

    set_source_credentials(conn, tenant_id, source_id, {"api_token": "old"})
    set_source_credentials(conn, tenant_id, source_id, {"api_token": "new"})

    loaded = load_source(conn, tenant_id, source_id)
    assert loaded["connection_credentials"] == {"api_token": "new"}


def test_set_credentials_rejects_a_non_object_value(conn):
    tenant_id = _insert_company(conn)
    source_id = _insert_source(conn, tenant_id)

    with pytest.raises(ValueError, match="JSON object"):
        set_source_credentials(conn, tenant_id, source_id, "not-a-dict")


def test_set_credentials_raises_for_a_source_that_does_not_exist(conn):
    tenant_id = _insert_company(conn)
    with pytest.raises(ValueError, match="source not found"):
        set_source_credentials(conn, tenant_id, str(uuid.uuid4()), {"api_token": "x"})


def test_set_credentials_is_tenant_scoped(conn):
    tenant_a = _insert_company(conn)
    tenant_b = _insert_company(conn)
    source_id = _insert_source(conn, tenant_a)

    with pytest.raises(ValueError, match="source not found"):
        set_source_credentials(conn, tenant_b, source_id, {"api_token": "x"})
