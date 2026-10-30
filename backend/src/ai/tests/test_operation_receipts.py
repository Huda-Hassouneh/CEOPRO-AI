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

def test_connector_source_fingerprint_changes_with_config_or_encrypted_credential():
    from src.ai.core.operation_receipts import connector_source_fingerprint

    baseline = connector_source_fingerprint({"base_url": "https://pos.example/sales"}, "ciphertext-v1")
    assert baseline == connector_source_fingerprint({"base_url": "https://pos.example/sales"}, "ciphertext-v1")
    assert baseline != connector_source_fingerprint({"base_url": "https://pos.example/orders"}, "ciphertext-v1")
    assert baseline != connector_source_fingerprint({"base_url": "https://pos.example/sales"}, "ciphertext-v2")


@pytest.mark.parametrize("provider", ["shopify", "woocommerce"])
def test_verified_store_providers_share_existing_connector_receipt_authority(monkeypatch, provider):
    conn = _Connection((1,))
    monkeypatch.setattr(operation_receipts, "_principal_is_active", lambda *_: True)
    monkeypatch.setattr(operation_receipts.usage, "get_plan", lambda *_: {"period_start": None})
    monkeypatch.setattr(operation_receipts.usage, "_require_active", lambda *_: None)

    operation_receipts.authorize_operation(
        conn, operation_receipts.SCHEDULED_CONNECTOR_SYNC, "tenant", "source", "source",
        "service-actor",
    )

    statement = conn.cursor_instance.sql[-1][0]
    assert "collector_key IN ('shopify','woocommerce')" in statement
    assert "p.provider=data_sources.collector_key" in statement
