from types import SimpleNamespace

import pytest

from src.market_scraper import data_access


class FakeCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params):
        self.calls.append((" ".join(query.split()), params))


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


def test_tenant_connection_requires_service_principal(monkeypatch):
    monkeypatch.setenv("SCRAPER_DATABASE_URL", "postgresql://example/test")
    monkeypatch.delenv("SCRAPER_ACTOR_USER_ID", raising=False)
    with pytest.raises(RuntimeError, match="SCRAPER_ACTOR_USER_ID"):
        data_access.get_tenant_connection("tenant-1")
