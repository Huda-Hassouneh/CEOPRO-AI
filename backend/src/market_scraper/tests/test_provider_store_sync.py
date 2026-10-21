import json
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import httpx

import pytest

from src.market_scraper import data_access, provider_store_sync as sync
from src.market_scraper.provider_lifecycle import ProviderLifecycleError, woocommerce_verified_store_id
from src.market_scraper.shopify import ShopifyError, ShopifyGraphQLClient, ShopifyRecord
from src.market_scraper.woocommerce import WooRecord


def test_client_uses_only_verified_store_identity_and_vault_token():
    source = {
        "collector_key": "shopify", "provider": "shopify", "connection_state": "verified",
        "verified_store_id": "gid://shopify/Shop/1", "verified_store_domain": "shop.myshopify.com",
    }
    captured = {}

    def factory(domain, token, **kwargs):
        captured.update(domain=domain, token=token, **kwargs)
        return object()

    result = sync._client_for(source, {
        "connection_credentials": {"access_token": "test-secret"},
        "collector_config": {"api_version": "2026-10", "max_pages": 3},
    }, factory)
    assert result is not None
    assert captured == {"domain": "shop.myshopify.com", "token": "test-secret", "api_version": "2026-10",
                        "max_pages": 3, "include_test_orders": False}
    with pytest.raises(ProviderLifecycleError):
        sync._client_for({**source, "connection_state": "verification_required"},
                         {"connection_credentials": {"access_token": "test-secret"}}, factory)
    with pytest.raises(ShopifyError):
        sync._client_for(source, {"connection_credentials": {}}, factory)


def test_sync_shopify_stream_persists_identities_and_advances_only_provider_checkpoint(monkeypatch):
    conn = Mock()
    conn.cursor.return_value = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        "shopify", "gid://shopify/Shop/1", "shop.myshopify.com", "verified", 4,
    )
    source = {
        "source_id": "source-1", "collector_key": "shopify", "provider": "shopify",
        "verified_store_id": "gid://shopify/Shop/1", "verified_store_domain": "shop.myshopify.com",
        "connection_state": "verified", "configuration_version": 4,
    }
    loaded = {"collector_key": "shopify", "collector_config": {},
              "connection_credentials": {"access_token": "in-memory-test-token"},
              "source_execution_fingerprint": "fingerprint"}
    record = ShopifyRecord("product", "gid://shopify/Product/42", {
        "id": "gid://shopify/Product/42", "updatedAt": "2026-10-20T10:00:00Z",
    })
    client = SimpleNamespace(
        verify_connection=lambda: {"verified": True, "shop_id": source["verified_store_id"],
                                   "shop_domain": source["verified_store_domain"]},
        iter_products=lambda: iter([record]),
    )
    monkeypatch.setattr(sync.data_access, "load_source", lambda *_: loaded)
    monkeypatch.setattr(sync.data_access, "create_or_reuse_receipt_ingestion_job", lambda *_, **__: "job-1")
    monkeypatch.setattr(sync.operation_receipts, "begin_provider", lambda *_: None)
    monkeypatch.setattr(sync, "persist_shopify_records", Mock(return_value=[{"mapping_status": "pending_review"}]))
    staging = Mock(return_value={"records_seen": 1, "revisions_created": 1, "duplicates": 0,
                                 "invalid": 1, "review_required": 0, "valid": 0})
    monkeypatch.setattr(sync, "stage_provider_business_records", staging)
    finish = Mock()
    monkeypatch.setattr(sync.data_access, "finish_ingestion_job", finish)
    receipt = {"operation_type": sync.operation_receipts.SCHEDULED_CONNECTOR_SYNC, "receipt_id": "receipt-1"}

    result = sync.sync_shopify_stream(conn, "tenant-1", source, "products", receipt,
                                      client_factory=lambda *args, **kwargs: client)

    assert result == {"source_id": "source-1", "job_id": "job-1", "stream": "products",
                      "records_persisted": 1, "checkpoint_advanced": True, "canonical_promotion": False,
                      "business_staging": {"records_seen": 1, "revisions_created": 1, "duplicates": 0,
                                            "invalid": 1, "review_required": 0, "valid": 0},
                      "business_records_staged": 1}
    sync.persist_shopify_records.assert_called_once()
    assert sync.persist_shopify_records.call_args.args[0]._conn is conn
    assert sync.persist_shopify_records.call_args.args[1:] == ("source-1", [record])
    staging.assert_called_once()
    assert finish.call_args.kwargs["status"] == "COMPLETED"
    assert finish.call_args.kwargs["provider_checkpoint"] == {
        "source_id": "source-1", "stream_key": "products", "continuation": {},
        "configuration_version": 4,
    }


def test_unverified_woocommerce_sources_remain_blocked_without_receipt_or_provider_call(monkeypatch):
    source = {"source_id": "source-woo", "collector_key": "woocommerce", "provider": None,
              "verified_store_id": None, "verified_store_domain": None, "connection_state": None}
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "service-principal")
    monkeypatch.setattr(sync.operation_receipts, "recover_expired", lambda *_: {})
    monkeypatch.setattr(sync, "load_due_provider_sources", lambda *_: [source])
    receipt = Mock()

    result = sync.run_due_provider_syncs(object(), "tenant-1")

    assert result == [{"source_id": "source-woo", "provider": "woocommerce",
                       "blocked": "verified_provider_source_binding_required"}]
    receipt.create_or_get_operation.assert_not_called()


def test_woocommerce_worker_persists_provider_evidence_and_full_scan_checkpoints(monkeypatch):
    conn = Mock()
    conn.cursor.return_value = MagicMock()
    verified_store_id = woocommerce_verified_store_id("https://shop.example.test")
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        "woocommerce", verified_store_id, "shop.example.test", "verified", 3,
    )
    source = {"source_id": "source-woo", "collector_key": "woocommerce", "provider": "woocommerce",
              "verified_store_id": verified_store_id, "verified_store_domain": "shop.example.test",
              "connection_state": "verified", "configuration_version": 3}
    loaded = {"collector_key": "woocommerce", "collector_config": {"store_url": "https://shop.example.test"},
              "connection_credentials": {"consumer_key": "ck_test", "consumer_secret": "cs_test"},
              "source_execution_fingerprint": "fingerprint"}
    products = [WooRecord("product", 10, {"id": 10, "manage_stock": True, "stock_quantity": 4})]
    orders = [WooRecord("order", 20, {"id": 20, "line_items": [{"id": 30, "product_id": 10}]})]
    client = SimpleNamespace(verify_connection=lambda: {
        "verified": True, "api": "wc/v3", "products_accessible": True, "orders_accessible": True,
        "currency_code": "USD", "canonical_store_url": "https://shop.example.test",
    }, iter_products=lambda: iter(products), iter_orders=lambda: iter(orders))
    monkeypatch.setattr(sync.data_access, "load_source", lambda *_: loaded)
    monkeypatch.setattr(sync.data_access, "create_or_reuse_receipt_ingestion_job", lambda *_, **__: "job-woo")
    monkeypatch.setattr(sync.operation_receipts, "begin_provider", lambda *_: None)
    identities = Mock(return_value=[{"mapping_status": "pending_review"}] * 3)
    inventory = Mock(return_value=[{"reconciliation_status": "unmatched_product"}])
    monkeypatch.setattr(sync, "persist_woocommerce_records", identities)
    monkeypatch.setattr(sync, "persist_woocommerce_inventory_records", inventory)
    business = Mock(return_value={"records_seen": 3, "revisions_created": 3, "duplicates": 0,
                                 "invalid": 3, "review_required": 0, "valid": 0})
    monkeypatch.setattr(sync, "stage_provider_business_records", business)
    finish = Mock()
    monkeypatch.setattr(sync.data_access, "finish_ingestion_job", finish)
    receipt = {"operation_type": sync.operation_receipts.SCHEDULED_CONNECTOR_SYNC, "receipt_id": "receipt-woo"}

    result = sync.sync_woocommerce_source(conn, "tenant-1", source, receipt,
                                         client_factory=lambda *_args, **_kwargs: client)

    assert result["provider"] == "woocommerce" and result["canonical_promotion"] is False
    assert result["full_scan"] is True and result["checkpoint_advanced"] is True
    identities.assert_called_once_with(identities.call_args.args[0], "source-woo", [*products, *orders],
                                       ingestion_job_id="job-woo")
    inventory.assert_called_once()
    business.assert_called_once()
    assert result["business_records_staged"] == 3
    assert {item["stream_key"] for item in finish.call_args.kwargs["provider_checkpoints"]} == {
        "products", "orders", "inventory",
    }
    assert finish.call_args.kwargs["status"] == "COMPLETED"


def test_woocommerce_client_requires_bound_url_and_vault_credentials():
    source = {"collector_key": "woocommerce", "provider": "woocommerce", "connection_state": "verified",
              "verified_store_id": "url-sha256:invalid"}
    factory = Mock()
    with pytest.raises(ProviderLifecycleError):
        sync._woocommerce_client_for(source, {"collector_config": {"store_url": "https://shop.example"},
                                              "connection_credentials": {"consumer_key": "ck", "consumer_secret": "cs"}}, factory)
    factory.assert_not_called()


def test_failed_identity_persistence_fails_job_without_advancing_checkpoint(monkeypatch):
    conn = Mock()
    conn.cursor.return_value = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        "shopify", "gid://shopify/Shop/1", "shop.myshopify.com", "verified", 4,
    )
    source = {
        "source_id": "source-1", "collector_key": "shopify", "provider": "shopify",
        "verified_store_id": "gid://shopify/Shop/1", "verified_store_domain": "shop.myshopify.com",
        "connection_state": "verified", "configuration_version": 4,
    }
    loaded = {"collector_key": "shopify", "collector_config": {},
              "connection_credentials": {"access_token": "in-memory-test-token"},
              "source_execution_fingerprint": "fingerprint"}
    client = SimpleNamespace(
        verify_connection=lambda: {"verified": True, "shop_id": source["verified_store_id"],
                                   "shop_domain": source["verified_store_domain"]},
        iter_products=lambda: iter([ShopifyRecord("product", "gid://shopify/Product/42", {
            "id": "gid://shopify/Product/42", "updatedAt": "2026-10-20T10:00:00Z",
        })]),
    )
    monkeypatch.setattr(sync.data_access, "load_source", lambda *_: loaded)
    monkeypatch.setattr(sync.data_access, "create_or_reuse_receipt_ingestion_job", lambda *_, **__: "job-1")
    monkeypatch.setattr(sync.operation_receipts, "begin_provider", lambda *_: None)
    monkeypatch.setattr(sync, "persist_shopify_records", Mock(side_effect=RuntimeError("database failure")))
    finish = Mock()
    monkeypatch.setattr(sync.data_access, "finish_ingestion_job", finish)
    receipt = {"operation_type": sync.operation_receipts.SCHEDULED_CONNECTOR_SYNC, "receipt_id": "receipt-1"}

    with pytest.raises(RuntimeError, match="database failure"):
        sync.sync_shopify_stream(conn, "tenant-1", source, "products", receipt,
                                 client_factory=lambda *args, **kwargs: client)

    assert finish.call_args.kwargs["status"] == "FAILED"
    assert "provider_checkpoint" not in finish.call_args.kwargs


class _ReceiptCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.connection.calls.append((query, params))
        self.rowcount = 1

    def fetchone(self):
        if self.connection.authorized is False:
            return None
        return (1,)


class _ReceiptConnection:
    def __init__(self, authorized=True):
        self.calls = []
        self.committed = False
        self.authorized = authorized

    def cursor(self):
        return _ReceiptCursor(self)

    def commit(self):
        self.committed = True


def test_expired_receipt_recovery_replays_only_verified_read_only_store_syncs():
    conn = _ReceiptConnection()
    result = sync.operation_receipts.recover_expired(conn, "tenant-1")
    statements = [query for query, _ in conn.calls]
    assert result == {"retryable": 2, "reconciliation_required": 1}
    assert "state='reconciliation_required'" in statements[1]
    assert "AND NOT (operation_type=%s" in statements[1]
    assert "state='retryable',provider_started_at=NULL" in statements[2]
    assert "ds.collector_key IN ('shopify','woocommerce')" in statements[2]
    assert "ps.provider=ds.collector_key" in statements[2]
    assert "ps.connection_state='verified'" in statements[2]
    assert conn.committed is True


def test_safe_read_retry_requires_verified_store_binding():
    conn = _ReceiptConnection(authorized=False)
    receipt = {"operation_type": sync.operation_receipts.SCHEDULED_CONNECTOR_SYNC,
               "tenant_id": "tenant-1", "source_id": "source-1"}
    with pytest.raises(sync.operation_receipts.ReceiptAuthorizationError):
        sync.operation_receipts.finish(conn, receipt, "retryable", replay_safe_provider_read=True)
    assert len(conn.calls) == 1
    assert "ds.collector_key IN ('shopify','woocommerce')" in conn.calls[0][0]
    assert "ps.provider=ds.collector_key" in conn.calls[0][0]


def test_safe_retry_reopens_the_same_failed_job_under_the_receipt_fence(monkeypatch):
    conn = Mock()
    cursor = MagicMock()
    cursor.__enter__.return_value.fetchone.return_value = ("source-1", "FAILED")
    cursor.__enter__.return_value.rowcount = 1
    conn.cursor.return_value = cursor
    monkeypatch.setattr(sync.operation_receipts, "assert_fence", Mock())
    receipt = {"tenant_id": "tenant-1", "source_id": "source-1",
               "operation_type": sync.operation_receipts.SCHEDULED_CONNECTOR_SYNC,
               "ingestion_job_id": "job-1"}

    job_id = data_access.create_or_reuse_receipt_ingestion_job(
        conn, "tenant-1", "source-1", receipt, replay_safe_provider_read=True,
    )

    assert job_id == "job-1"
    sync.operation_receipts.assert_fence.assert_called_once_with(conn, receipt, allow_pre_provider=True)
    statements = [call.args[0] for call in cursor.__enter__.return_value.execute.call_args_list]
    assert "SELECT source_id,job_status" in statements[0]
    assert "SET job_status='PROCESSING'" in statements[1]
    assert "ps.connection_state='verified'" in statements[1]
    conn.commit.assert_called_once()


def test_worker_uses_real_shopify_graphql_client_with_contract_fixture(monkeypatch):
    source = {
        "source_id": "source-1", "collector_key": "shopify", "provider": "shopify",
        "verified_store_id": "gid://shopify/Shop/1", "verified_store_domain": "shop.myshopify.com",
        "connection_state": "verified", "configuration_version": 4,
    }
    conn = Mock()
    conn.cursor.return_value = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        "shopify", source["verified_store_id"], source["verified_store_domain"], "verified", 4,
    )
    loaded = {"collector_key": "shopify", "collector_config": {"api_version": "2026-10"},
              "connection_credentials": {"access_token": "fixture-only-token"},
              "source_execution_fingerprint": "fingerprint"}
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.scheme == "https"
        assert request.headers["X-Shopify-Access-Token"] == "fixture-only-token"
        query = json.loads(request.content)["query"]
        if "currentAppInstallation" in query:
            payload = {"data": {
                "shop": {"id": source["verified_store_id"], "myshopifyDomain": source["verified_store_domain"], "currencyCode": "USD"},
                "currentAppInstallation": {"accessScopes": [{"handle": "read_products"}]},
            }}
        else:
            product = {
                "id": "gid://shopify/Product/42", "title": "Fixture product", "handle": "fixture-product",
                "status": "ACTIVE", "vendor": "Fixture", "createdAt": "2026-10-20T09:00:00Z",
                "updatedAt": "2026-10-20T10:00:00Z",
                "variants": {
                    "edges": [{"cursor": "variant-cursor-1", "node": {
                        "id": "gid://shopify/ProductVariant/43", "title": "Default", "sku": "FIXTURE-43",
                        "barcode": None, "updatedAt": "2026-10-20T10:00:00Z",
                        "inventoryItem": {"id": "gid://shopify/InventoryItem/44", "tracked": True},
                    }}],
                    "pageInfo": {"hasNextPage": False, "endCursor": "variant-cursor-1"},
                },
            }
            payload = {"data": {"products": {
                "edges": [{"cursor": "product-cursor-1", "node": product}],
                "pageInfo": {"hasNextPage": False, "endCursor": "product-cursor-1"},
            }}}
        return httpx.Response(200, json=payload, headers={"X-Shopify-API-Version": "2026-10"}, request=request)

    def client_factory(domain, token, **kwargs):
        return ShopifyGraphQLClient(
            domain, token, resolver=lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
            transport_factory=lambda _ip: httpx.MockTransport(handler), sleeper=lambda _delay: None, **kwargs,
        )

    persisted = Mock(return_value=[
        {"identity_id": "identity-product", "entity_type": "product", "provider_record_id": "gid://shopify/Product/42", "mapping_status": "pending_review"},
        {"identity_id": "identity-variant", "entity_type": "variant", "provider_record_id": "gid://shopify/ProductVariant/43", "mapping_status": "pending_review"},
    ])
    monkeypatch.setattr(sync.data_access, "load_source", lambda *_: loaded)
    monkeypatch.setattr(sync.data_access, "create_or_reuse_receipt_ingestion_job", lambda *_, **__: "job-1")
    monkeypatch.setattr(sync.operation_receipts, "begin_provider", lambda *_: None)
    monkeypatch.setattr(sync, "persist_shopify_records", persisted)
    staging = Mock(return_value={"records_seen": 2, "revisions_created": 2, "duplicates": 0,
                                 "invalid": 0, "review_required": 2, "valid": 0})
    monkeypatch.setattr(sync, "stage_provider_business_records", staging)
    finish = Mock()
    monkeypatch.setattr(sync.data_access, "finish_ingestion_job", finish)
    receipt = {"operation_type": sync.operation_receipts.SCHEDULED_CONNECTOR_SYNC, "receipt_id": "receipt-1"}

    result = sync.sync_shopify_stream(conn, "tenant-1", source, "products", receipt, client_factory=client_factory)

    assert result["records_persisted"] == 2
    assert result["canonical_promotion"] is False
    assert result["business_records_staged"] == 2
    staging.assert_called_once()
    assert len(requests) == 3  # two authenticated shop verifications and one bounded product page
    records = persisted.call_args.args[2]
    assert [(record.entity_type, record.provider_id) for record in records] == [
        ("product", "gid://shopify/Product/42"), ("variant", "gid://shopify/ProductVariant/43"),
    ]
    assert finish.call_args.kwargs["provider_checkpoint"]["stream_key"] == "products"
