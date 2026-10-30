from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.ai.routers import onboarding


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params):
        self.sql = sql

    def fetchall(self):
        return [self.row]


class _Connection:
    def __init__(self, row):
        self.cursor_value = _Cursor(row)
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    ("provider_state", "expected"),
    [("verified", "verified"), ("verification_required", "verification_required"),
     (None, "verification_required")],
)
def test_provider_connection_list_exposes_verified_state_and_last_job(monkeypatch, provider_state, expected):
    verified_at = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
    created_at = datetime(2026, 10, 22, 10, 1, tzinfo=timezone.utc)
    row = ("source-1", "sample-shop", "shopify", 60, None, created_at, True,
           "COMPLETED", 17, 0, created_at, provider_state, verified_at if provider_state else None,
           "job-1", created_at)
    conn = _Connection(row)
    monkeypatch.setattr(onboarding.db, "app_role_connection", lambda *_args: conn)

    result = onboarding.list_connected_sources(SimpleNamespace(tenant_id="tenant-1", user_id="owner-1"))

    source = result["sources"][0]
    assert source["connection_status"] == expected
    assert source["verified_at"] == (verified_at.isoformat() if provider_state else None)
    assert source["last_run"] == {
        "status": "COMPLETED", "rows_processed": 17, "rows_failed": 0,
        "finished_at": created_at.isoformat(), "job_id": "job-1", "created_at": created_at.isoformat(),
    }
    assert "keel_provider_sources" in conn.cursor_value.sql
    assert conn.closed


def test_non_provider_source_status_falls_back_to_active(monkeypatch):
    created_at = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
    conn = _Connection(("source-2", "api", "api_connector", 60, None, created_at, True,
                        None, None, None, None, None, None, None, None))
    monkeypatch.setattr(onboarding.db, "app_role_connection", lambda *_args: conn)

    result = onboarding.list_connected_sources(SimpleNamespace(tenant_id="tenant-1", user_id="owner-1"))

    assert result["sources"][0]["connection_status"] == "active"
    assert result["sources"][0]["last_run"] is None
