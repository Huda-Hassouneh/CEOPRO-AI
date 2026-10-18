"""scripts/vault_key.py and the billing part of the configuration check,
against a real Postgres: rotating the vault key re-wraps every stored
connector credential or changes nothing; paid integrations without a price
are reported."""
import os
import uuid

import psycopg2
import pytest
from cryptography.fernet import Fernet

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")

from scripts import vault_key  # noqa: E402
from src.ai.core import config_check  # noqa: E402
from src.market_scraper.credential_vault import LocalEnvelopeKMS, decrypt_credentials, encrypt_credentials  # noqa: E402


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    yield connection
    connection.rollback()
    connection.close()


def _source(conn, envelope):
    tenant = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Vault', 'JO', 'JOD');",
                       (tenant,))
        cursor.execute("INSERT INTO data_sources (tenant_id, source_name, source_type, connection_credentials_vault) "
                       "VALUES (%s, 'POS', 'OWN_SYSTEM_CONNECTOR', %s) RETURNING source_id;", (tenant, envelope))
        source = str(cursor.fetchone()[0])
    conn.commit()
    return tenant, source


def _stored(conn, source):
    with conn.cursor() as cursor:
        cursor.execute("SELECT connection_credentials_vault FROM data_sources WHERE source_id = %s;", (source,))
        value = cursor.fetchone()[0]
    conn.rollback()
    return value


@pytest.fixture
def isolated(conn):
    """Only this test's rows: other tests' credentials use other keys."""
    with conn.cursor() as cursor:
        cursor.execute("UPDATE data_sources SET connection_credentials_vault = NULL WHERE connection_credentials_vault IS NOT NULL;")
    conn.commit()


def test_rotation_rewraps_every_credential_and_loses_none(conn, isolated):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    _, a = _source(conn, encrypt_credentials({"password": "a"}, LocalEnvelopeKMS(master_key=old, previous_keys=[])))
    _, b = _source(conn, encrypt_credentials({"password": "b"}, LocalEnvelopeKMS(master_key=old, previous_keys=[])))
    rotating = LocalEnvelopeKMS(master_key=new, previous_keys=[old])
    before = vault_key.check(conn, rotating)
    assert (before["stored"], before["previous_key"], before["unreadable"]) == (2, 2, 0)
    assert vault_key.rewrap(conn, rotating) == {"stored": 2, "rewrapped": 2}
    after = vault_key.check(conn, rotating)
    assert (after["current_key"], after["previous_key"]) == (2, 0)
    new_only = LocalEnvelopeKMS(master_key=new, previous_keys=[])
    assert decrypt_credentials(_stored(conn, a), new_only) == {"password": "a"}
    assert decrypt_credentials(_stored(conn, b), new_only) == {"password": "b"}


def test_rewrap_changes_nothing_when_one_credential_cannot_be_opened(conn, isolated):
    old, new, lost = (Fernet.generate_key().decode() for _ in range(3))
    _, good = _source(conn, encrypt_credentials({"k": "good"}, LocalEnvelopeKMS(master_key=old, previous_keys=[])))
    _, orphan = _source(conn, encrypt_credentials({"k": "x"}, LocalEnvelopeKMS(master_key=lost, previous_keys=[])))
    before_good, before_orphan = _stored(conn, good), _stored(conn, orphan)
    rotating = LocalEnvelopeKMS(master_key=new, previous_keys=[old])
    assert vault_key.check(conn, rotating)["unreadable_source_ids"] == [orphan]
    with pytest.raises(SystemExit, match=orphan):
        vault_key.rewrap(conn, rotating)
    assert (_stored(conn, good), _stored(conn, orphan)) == (before_good, before_orphan)


def test_paid_integrations_without_a_price_are_reported(conn, monkeypatch):
    for name in ("PAID_LLM_BASE_URL", "HUGGINGFACE_LLM_MODEL", "LOCAL_LLM_BASE_URL", "HUGGINGFACE_API_TOKEN",
                 "CLOUDFLARE_API_TOKEN", "BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "SERPAPI_API_KEY", "APIFY_TOKEN",
                 "GOOGLE_MAPS_API_KEY", "GOOGLE_CUSTOM_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GROQ_MODEL", f"model-{uuid.uuid4().hex[:6]}")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "VALUE-MUST-NOT-APPEAR-1")
    monkeypatch.setenv("APIFY_API_TOKEN", "VALUE-MUST-NOT-APPEAR-2")
    messages = [f.message for f in config_check.check_billing(conn)]
    assert any("no confirmed input/output token price" in m for m in messages)
    assert any(m.startswith("Google Places") for m in messages) and any(m.startswith("Apify") for m in messages)
    assert all("VALUE-MUST-NOT-APPEAR" not in m and "gsk_test" not in m for m in messages)
