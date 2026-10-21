import pytest

from src.ai.core import operation_receipts


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Connection:
    def __init__(self, row):
        self.cursor_instance = _Cursor(row)

    def cursor(self):
        return self.cursor_instance


def test_source_fingerprint_is_stable_and_tenant_bound():
    a = operation_receipts.source_fingerprint("tenant-a", "source-1")
    assert a == operation_receipts.source_fingerprint("tenant-a", "source-1")
    assert a != operation_receipts.source_fingerprint("tenant-b", "source-1")
    assert len(a) == 64


def test_execution_authorization_fails_closed_for_inactive_principal(monkeypatch):
    conn = _Connection((False,))
    monkeypatch.setattr("src.ai.core.operation_receipts.usage.get_plan", lambda *args: pytest.fail("plan read after principal denial"))
    with pytest.raises(operation_receipts.ReceiptAuthorizationError, match="active principal"):
        operation_receipts.authorize_collection(conn, "tenant-a", "source-1", "user-1")
    assert "keel_active_principal" in conn.cursor_instance.sql[0][0]
