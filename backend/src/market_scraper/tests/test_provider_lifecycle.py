import pytest

from src.market_scraper.provider_lifecycle import (
    ProviderLifecycleError,
    advance_completed_checkpoint,
    bind_verified_provider_source,
)


class _Cursor:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        return (self.result,)


class _Connection:
    def __init__(self, result=None):
        self._cursor = _Cursor(result)

    def cursor(self):
        return self._cursor


def test_shopify_binding_requires_provider_verified_stable_identity():
    conn = _Connection({"source_id": "source", "reconnected": False})
    result = bind_verified_provider_source(
        conn,
        tenant_id="tenant",
        source_id="source",
        provider="shopify",
        verification={
            "verified": True,
            "shop_id": "gid://shopify/Shop/123",
            "shop_domain": "example.myshopify.com",
            "api_version": "2026-10",
            "currency_code": "USD",
        },
    )
    assert result["reconnected"] is False
    assert "bind_verified" in conn._cursor.calls[0][0]
    assert "Shop/123" in conn._cursor.calls[0][1][0]


@pytest.mark.parametrize("provider,verification", [
    ("shopify", {"verified": False, "shop_id": "gid://shopify/Shop/1", "shop_domain": "example.myshopify.com"}),
    ("shopify", {"verified": True, "shop_id": "", "shop_domain": "example.myshopify.com"}),
    ("woocommerce", {"verified": True, "store_url": "https://shop.example"}),
])
def test_binding_fails_closed_without_a_provider_verified_store_id(provider, verification):
    conn = _Connection()
    with pytest.raises(ProviderLifecycleError):
        bind_verified_provider_source(
            conn, tenant_id="tenant", source_id="source", provider=provider, verification=verification,
        )
    assert conn._cursor.calls == []


def test_sensitive_verification_evidence_is_never_sent_to_database():
    conn = _Connection()
    with pytest.raises(ProviderLifecycleError):
        bind_verified_provider_source(
            conn,
            tenant_id="tenant",
            source_id="source",
            provider="shopify",
            verification={
                "verified": True,
                "shop_id": "gid://shopify/Shop/123",
                "shop_domain": "example.myshopify.com",
                "access_token": "must not persist",
            },
        )
    assert conn._cursor.calls == []


def test_partial_connector_completion_never_advances_checkpoint():
    conn = _Connection()
    with pytest.raises(ProviderLifecycleError):
        advance_completed_checkpoint(
            conn,
            tenant_id="tenant",
            source_id="source",
            stream_key="products",
            continuation={"cursor": "next"},
            receipt={"operation_type": "scheduled_connector_sync", "receipt_id": "r", "lease_generation": 2},
            job_id="job",
            configuration_version=1,
            job_completed=False,
            rows_partial=1,
        )
    assert conn._cursor.calls == []
