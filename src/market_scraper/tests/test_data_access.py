import json
from types import SimpleNamespace

import pytest

from src.market_scraper import data_access


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


def test_tenant_connection_sets_tenant_and_actor_rls_context(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setenv("SCRAPER_DATABASE_URL", "postgresql://example/test")
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "user-1")
    monkeypatch.setattr(data_access.psycopg2, "connect", lambda url: connection)

    assert data_access.get_tenant_connection("tenant-1") is connection
    assert connection.fake_cursor.calls == [
        ("SET app.current_tenant_id = %s;", ("tenant-1",)),
        ("SET app.current_user_id = %s;", ("user-1",)),
    ]
    assert connection.committed is True


def test_allowed_policy_requires_accountable_approval():
    decision = SimpleNamespace(
        status=SimpleNamespace(value="ALLOWED"),
        method=SimpleNamespace(value="WEB_SCRAPE"), collection_url="https://example.com",
        justification="reviewed",
    )
    with pytest.raises(ValueError, match="approval_reference"):
        data_access.record_policy_decision(FakeConnection(), "tenant", "source", decision)


def test_load_source_parses_connection_credentials_vault():
    row = (
        "source-1", "Example", "https://shop.example", "STRUCTURED_DATA",
        "ALLOWED", "reviewed", {}, 30, "standards", False, {}, "SEC-1", "2026-01-01",
        "2026-01-01", 90, False, json.dumps({"api_key": "abc"}),
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


def test_tenant_connection_requires_service_principal(monkeypatch):
    monkeypatch.setenv("SCRAPER_DATABASE_URL", "postgresql://example/test")
    monkeypatch.delenv("SCRAPER_ACTOR_USER_ID", raising=False)
    with pytest.raises(RuntimeError, match="SCRAPER_ACTOR_USER_ID"):
        data_access.get_tenant_connection("tenant-1")
