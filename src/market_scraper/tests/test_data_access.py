from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from src.market_scraper import data_access
from src.market_scraper.credential_vault import CredentialDecryptionError, LocalEnvelopeKMS, encrypt_credentials


class FakeCursor:
    def __init__(self, fetchone_result=None):
        self.calls = []
        self.fetchone_result = fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params):
        self.calls.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.fetchone_result


class FakeConnection:
    def __init__(self):
        self.fake_cursor = FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_pool_singleton():
    """
    _get_pool() caches a module-level pool for the process's lifetime -
    without resetting it between tests, whichever test runs first would
    permanently decide every later test's pool (and its fake double).
    """
    data_access._POOL = None
    yield
    data_access._POOL = None


def test_get_tenant_connection_delegates_to_the_pool_with_the_right_ids(monkeypatch):
    """
    The real fix (production-hardening audit follow-up): get_tenant_
    connection() no longer opens its own psycopg2.connect() and issues
    SET statements directly - it delegates to a pooled
    TenantConnectionPool (src/infrastructure/db_pool.py), which is what
    actually applies RLS context (via SET LOCAL, safe under reuse - see
    that module's own tests for the SET LOCAL/pooling-safety proof this
    file doesn't need to re-verify). This test only checks the
    orchestration: the right tenant_id/actor_user_id reach the pool.
    """
    monkeypatch.setenv("SCRAPER_DATABASE_URL", "postgresql://example/test")
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "user-1")
    fake_pooled_conn = object()
    captured = {}

    def fake_get_tenant_connection(tenant_id, user_id):
        captured["tenant_id"] = tenant_id
        captured["user_id"] = user_id
        return fake_pooled_conn

    fake_pool = SimpleNamespace(get_tenant_connection=fake_get_tenant_connection)
    monkeypatch.setattr(data_access, "_get_pool", lambda: fake_pool)

    result = data_access.get_tenant_connection("tenant-1")

    assert result is fake_pooled_conn
    assert captured == {"tenant_id": "tenant-1", "user_id": "user-1"}


def test_get_pool_constructs_a_pool_from_scraper_env_vars_once(monkeypatch):
    monkeypatch.setenv("SCRAPER_DATABASE_URL", "postgresql://example/test")
    monkeypatch.setenv("SCRAPER_DB_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("SCRAPER_DB_POOL_MAX_SIZE", "7")
    construction_calls = []

    class FakePool:
        def __init__(self, dsn, minconn, maxconn):
            construction_calls.append((dsn, minconn, maxconn))

    monkeypatch.setattr(data_access, "TenantConnectionPool", FakePool)

    pool_a = data_access._get_pool()
    pool_b = data_access._get_pool()

    assert pool_a is pool_b  # cached - constructed exactly once
    assert construction_calls == [("postgresql://example/test", 2, 7)]


def test_get_pool_raises_without_a_database_url(monkeypatch):
    monkeypatch.delenv("SCRAPER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="SCRAPER_DATABASE_URL or DATABASE_URL"):
        data_access._get_pool()


def test_allowed_policy_requires_accountable_approval():
    decision = SimpleNamespace(
        status=SimpleNamespace(value="ALLOWED"),
        method=SimpleNamespace(value="WEB_SCRAPE"), collection_url="https://example.com",
        justification="reviewed",
    )
    with pytest.raises(ValueError, match="approval_reference"):
        data_access.record_policy_decision(FakeConnection(), "tenant", "source", decision)


def test_load_source_decrypts_an_encrypted_credentials_envelope(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", Fernet.generate_key().decode())
    envelope = encrypt_credentials({"api_key": "abc"}, LocalEnvelopeKMS())
    row = (
        "source-1", "Example", "https://shop.example", "STRUCTURED_DATA",
        "ALLOWED", "reviewed", {}, 30, "standards", False, {}, "SEC-1", "2026-01-01",
        "2026-01-01", 90, False, envelope,
    )
    connection = FakeConnection()
    connection.fake_cursor = FakeCursor(fetchone_result=row)
    source = data_access.load_source(connection, "tenant-1", "source-1")
    assert source["connection_credentials"] == {"api_key": "abc"}


def test_load_source_tolerates_empty_credentials_vault():
    row = (
        "source-1", "Example", "https://shop.example", "STRUCTURED_DATA",
        "ALLOWED", "reviewed", {}, 30, "standards", False, {}, "SEC-1", "2026-01-01",
        "2026-01-01", 90, False, None,
    )
    connection = FakeConnection()
    connection.fake_cursor = FakeCursor(fetchone_result=row)
    source = data_access.load_source(connection, "tenant-1", "source-1")
    assert source["connection_credentials"] == {}


def test_load_source_raises_loud_on_a_legacy_plaintext_credential(monkeypatch):
    """The real fix, not a silent one: a pre-encryption plaintext JSON
    value (or any other non-envelope garbage) must fail loud, never
    silently degrade to {} the way the old json.loads()-with-except
    behavior used to - a collector silently getting {} back would
    otherwise surface as a confusing "not configured" error instead of
    the real "this credential predates encryption" problem."""
    import json as _json
    monkeypatch.setenv("CREDENTIAL_VAULT_MASTER_KEY", Fernet.generate_key().decode())
    row = (
        "source-1", "Example", "https://shop.example", "STRUCTURED_DATA",
        "ALLOWED", "reviewed", {}, 30, "standards", False, {}, "SEC-1", "2026-01-01",
        "2026-01-01", 90, False, _json.dumps({"api_key": "plaintext-legacy-value"}),
    )
    connection = FakeConnection()
    connection.fake_cursor = FakeCursor(fetchone_result=row)
    with pytest.raises(CredentialDecryptionError, match="not a recognized encrypted envelope"):
        data_access.load_source(connection, "tenant-1", "source-1")


def test_tenant_connection_requires_service_principal(monkeypatch):
    monkeypatch.setenv("SCRAPER_DATABASE_URL", "postgresql://example/test")
    monkeypatch.delenv("SCRAPER_ACTOR_USER_ID", raising=False)
    with pytest.raises(RuntimeError, match="SCRAPER_ACTOR_USER_ID"):
        data_access.get_tenant_connection("tenant-1")
