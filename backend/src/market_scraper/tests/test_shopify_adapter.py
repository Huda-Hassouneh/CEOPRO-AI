import base64
import hashlib
import hmac
import json
import socket

import httpx
import pytest

from src.market_scraper.network_security import UnsafeTargetError
from src.market_scraper.shopify import (
    DEFAULT_API_VERSION,
    ShopifyError,
    ShopifyGraphQLClient,
    canonical_shop_domain,
    verify_privacy_webhook,
    verify_shopify_webhook,
)

SHOP = "example-shop.myshopify.com"
TOKEN = "shpat_do_not_log_this"


def _resolver(address="8.8.8.8"):
    return lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]


def _client(handler, **kwargs):
    return ShopifyGraphQLClient(
        SHOP,
        TOKEN,
        resolver=_resolver(),
        transport_factory=lambda _ip: httpx.MockTransport(handler),
        **kwargs,
    )


def _response(request, payload, *, status=200, headers=None):
    return httpx.Response(status, json=payload, headers=headers, request=request)


def _scope_response(request, scopes):
    return _response(request, {"data": {"shop": {"id": "gid://shopify/Shop/1", "myshopifyDomain": SHOP,
                                                    "currencyCode": "USD", "plan": {"partnerDevelopment": True}},
                                 "currentAppInstallation": {"accessScopes": [{"handle": item} for item in scopes]}}},
                      headers={"X-Shopify-API-Version": "2026-10"})


def _query(request):
    return json.loads(request.content)["query"]


def test_shop_domain_and_stable_api_version_are_strict():
    assert canonical_shop_domain(" Example-Shop.MyShopify.com ") == SHOP
    for value in (
        "http://example-shop.myshopify.com",
        "https://example-shop.myshopify.com",
        "example-shop.myshopify.com/path",
        "other.example.com",
        "user:pass@example-shop.myshopify.com",
        "127.0.0.1.myshopify.com:443",
    ):
        with pytest.raises(UnsafeTargetError):
            canonical_shop_domain(value)
    assert DEFAULT_API_VERSION == "2026-10"
    with pytest.raises(ValueError):
        ShopifyGraphQLClient(SHOP, TOKEN, api_version="latest")
    with pytest.raises(ValueError):
        ShopifyGraphQLClient(SHOP, TOKEN, api_version="2025-10")


def test_shopify_dns_resolution_rejects_private_addresses_before_transport():
    client = ShopifyGraphQLClient(
        SHOP,
        TOKEN,
        resolver=lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))],
        transport_factory=lambda _ip: pytest.fail("transport must not be opened for a private DNS answer"),
    )
    with pytest.raises(UnsafeTargetError):
        client.execute_query("query { shop { id } }")


def test_connection_verification_uses_pinned_version_token_header_and_current_scopes():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "POST"
        assert request.url == f"https://{SHOP}/admin/api/2026-10/graphql.json"
        assert request.headers["X-Shopify-Access-Token"] == TOKEN
        assert TOKEN not in str(request.url)
        assert "query" in _query(request)
        return _response(
            request,
            {"data": {"shop": {"id": "gid://shopify/Shop/1", "myshopifyDomain": SHOP, "currencyCode": "USD", "plan": {"partnerDevelopment": True}}, "currentAppInstallation": {"accessScopes": [{"handle": "read_products"}, {"handle": "read_orders"}, {"handle": "read_all_orders"}]}}},
            headers={"X-Shopify-API-Version": "2026-10"},
        )

    result = _client(handler).verify_connection()
    assert len(seen) == 1
    assert result["verified"] is True
    assert result["shop_id"] == "gid://shopify/Shop/1"
    assert result["granted_scopes"] == {"read_products", "read_orders", "read_all_orders"}
    assert result["order_history_access"] == "all_orders"
    assert result["development_store"] is True
    assert result["orders_readable"] is True
    recent = _client(lambda request: _scope_response(request, ["read_orders"])).verify_connection()
    assert recent["order_history_access"] == "provider_default_recent_window"
    unavailable = _client(lambda request: _scope_response(request, ["read_products"])).verify_connection()
    assert unavailable["order_history_access"] == "unavailable"


def test_verification_rejects_shop_mismatch_and_missing_scope():
    payload = {"data": {"shop": {"id": "gid://shopify/Shop/2", "myshopifyDomain": "other-shop.myshopify.com", "currencyCode": "USD"}, "currentAppInstallation": {"accessScopes": [{"handle": "read_orders"}]}}}
    with pytest.raises(ShopifyError, match="did not match"):
        _client(lambda request: _response(request, payload)).verify_connection()

    no_scope = {"data": {"shop": {"id": "gid://shopify/Shop/1", "myshopifyDomain": SHOP, "currencyCode": "USD"}, "currentAppInstallation": {"accessScopes": [{"handle": "read_orders"}]}}}
    client = _client(lambda request: _response(request, no_scope))
    with pytest.raises(ShopifyError) as exc:
        list(client.iter_products())
    assert exc.value.code == "insufficient_permissions"


def test_invalid_token_or_permission_errors_are_sanitized():
    for status, code in ((401, "invalid_credentials"), (403, "insufficient_permissions")):
        client = _client(lambda request, status=status: _response(request, {"error": TOKEN}, status=status))
        with pytest.raises(ShopifyError) as exc:
            client.execute_query("query { shop { id } }")
        assert exc.value.code == code
        assert TOKEN not in str(exc.value)


def test_read_only_query_guard_and_fall_forward_detection():
    client = _client(lambda request: _response(request, {"data": {"shop": {"id": "x"}}}, headers={"X-Shopify-API-Version": "2026-07"}))
    with pytest.raises(ValueError):
        client.execute_query("mutation { productUpdate } ")
    with pytest.raises(ShopifyError) as exc:
        client.execute_query("query { shop { id } }")
    assert exc.value.code == "api_version_mismatch"


def test_products_and_nested_variant_cursors_preserve_shopify_ids():
    calls = []
    def handler(request):
        query = _query(request)
        variables = json.loads(request.content)["variables"]
        calls.append((query, variables))
        if "KeelVerifyShop" in query:
            return _scope_response(request, ["read_products"])
        if "KeelProducts" in query:
            node = {"id": "gid://shopify/Product/1", "title": "Shirt", "variants": {"edges": [{"cursor": "v1", "node": {"id": "gid://shopify/ProductVariant/10", "sku": "S", "inventoryItem": {"id": "gid://shopify/InventoryItem/20", "tracked": True}}}], "pageInfo": {"hasNextPage": True, "endCursor": "v1"}}}
            return _response(request, {"data": {"products": {"edges": [{"cursor": "p1", "node": node}], "pageInfo": {"hasNextPage": False, "endCursor": "p1"}}}})
        assert variables["after"] == "v1"
        assert variables["id"] == "gid://shopify/Product/1"
        return _response(request, {"data": {"product": {"variants": {"edges": [{"cursor": "v2", "node": {"id": "gid://shopify/ProductVariant/11", "sku": "M"}}], "pageInfo": {"hasNextPage": False, "endCursor": "v2"}}}}})

    records = list(_client(handler, page_size=1).iter_products())
    assert [(item.entity_type, item.provider_id, item.parent_provider_id) for item in records] == [
        ("product", "gid://shopify/Product/1", None),
        ("variant", "gid://shopify/ProductVariant/10", "gid://shopify/Product/1"),
        ("variant", "gid://shopify/ProductVariant/11", "gid://shopify/Product/1"),
    ]
    assert len(calls) == 3


def test_orders_and_line_items_preserve_money_and_provider_identity():
    def order_node():
        return {"id": "gid://shopify/Order/5", "name": "#5", "currencyCode": "USD", "totalPriceSet": {"shopMoney": {"amount": "13.00", "currencyCode": "USD"}}, "lineItems": {"edges": [{"cursor": "l1", "node": {"id": "gid://shopify/LineItem/9", "quantity": 1, "originalUnitPriceSet": {"shopMoney": {"amount": "13.00", "currencyCode": "USD"}}}}], "pageInfo": {"hasNextPage": False, "endCursor": "l1"}}}
    def handler(request):
        if "KeelVerifyShop" in _query(request):
            return _scope_response(request, ["read_orders"])
        return _response(request, {"data": {"orders": {"edges": [{"cursor": "o1", "node": order_node()}], "pageInfo": {"hasNextPage": False, "endCursor": "o1"}}}})
    records = list(_client(handler).iter_orders())
    assert [(item.entity_type, item.provider_id, item.parent_provider_id) for item in records] == [
        ("order", "gid://shopify/Order/5", None),
        ("line_item", "gid://shopify/LineItem/9", "gid://shopify/Order/5"),
    ]
    assert records[0].payload["totalPriceSet"]["shopMoney"]["amount"] == "13.00"


def test_inventory_is_read_only_and_requires_explicit_scope():
    def handler(request):
        return _response(request, {"data": {"locations": {"edges": [{"cursor": "loc1", "node": {"id": "gid://shopify/Location/1", "name": "Main", "inventoryLevels": {"edges": [{"cursor": "i1", "node": {"id": "gid://shopify/InventoryLevel/2", "item": {"id": "gid://shopify/InventoryItem/3", "variant": {"id": "gid://shopify/ProductVariant/4"}}, "quantities": [{"name": "available", "quantity": 8}]}}], "pageInfo": {"hasNextPage": False, "endCursor": "i1"}}}}], "pageInfo": {"hasNextPage": False, "endCursor": "loc1"}}}})
    def scoped_handler(request):
        if "KeelVerifyShop" in _query(request):
            return _scope_response(request, ["read_inventory"])
        return handler(request)
    client = _client(scoped_handler)
    records = list(client.iter_inventory())
    assert [(item.entity_type, item.provider_id, item.parent_provider_id) for item in records] == [
        ("location", "gid://shopify/Location/1", None),
        ("inventory_level", "gid://shopify/InventoryLevel/2", "gid://shopify/Location/1"),
    ]


def test_partial_graphql_errors_never_return_partial_data():
    client = _client(lambda request: _response(request, {"data": {"shop": {"id": "gid://shopify/Shop/1"}}, "errors": [{"message": "secret and provider detail", "extensions": {"code": "ACCESS_DENIED"}}]}))
    with pytest.raises(ShopifyError) as exc:
        client.execute_query("query { shop { id } }")
    assert exc.value.code == "insufficient_permissions"
    assert "provider detail" not in str(exc.value) and TOKEN not in str(exc.value)


def test_throttle_retry_uses_cost_metadata_and_is_bounded():
    calls = 0
    sleeps = []
    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response(request, {"errors": [{"message": "throttled", "extensions": {"code": "THROTTLED"}}], "extensions": {"cost": {"requestedQueryCost": 20, "throttleStatus": {"currentlyAvailable": 0, "restoreRate": 10}}}})
        return _response(request, {"data": {"shop": {"id": "gid://shopify/Shop/1"}}})
    result = _client(handler, sleeper=sleeps.append, max_retry_delay=1).execute_query("query { shop { id } }")
    assert result["shop"]["id"] == "gid://shopify/Shop/1"
    assert calls == 2 and sleeps == [1]


def test_http_429_retry_and_graphql_cursor_nonprogress_are_bounded():
    calls = 0
    sleeps = []
    def throttled(request):
        nonlocal calls
        calls += 1
        return _response(request, {}, status=429, headers={"Retry-After": "100"}) if calls == 1 else _response(request, {"data": {"shop": {"id": "gid://shopify/Shop/1"}}})
    assert _client(throttled, sleeper=sleeps.append, max_retry_delay=2).execute_query("query { shop { id } }")["shop"]["id"]
    assert sleeps == [2]

    page_calls = 0
    def repeated(request):
        nonlocal page_calls
        page_calls += 1
        if "KeelVerifyShop" in _query(request):
            return _scope_response(request, ["read_products"])
        return _response(request, {"data": {"products": {"edges": [{"cursor": "same", "node": {"id": "gid://shopify/Product/1", "variants": {"edges": [], "pageInfo": {"hasNextPage": False}}}}], "pageInfo": {"hasNextPage": True, "endCursor": "same"}}}})
    with pytest.raises(ShopifyError) as exc:
        list(_client(repeated).iter_products())
    assert exc.value.code == "pagination_nonprogress"
    assert page_calls == 2


def test_hmac_verification_checks_raw_body_topic_shop_and_delivery_identity():
    secret = "app-secret"
    body = json.dumps({"shop_domain": SHOP, "shop_id": 123}, separators=(",", ":")).encode()
    digest = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    headers = {"X-Shopify-Hmac-Sha256": digest, "X-Shopify-Shop-Domain": SHOP, "X-Shopify-Topic": "app/uninstalled", "X-Shopify-Webhook-Id": "delivery-1", "X-Shopify-Event-Id": "event-1"}
    event = verify_shopify_webhook(body, headers, secret, expected_shop=SHOP)
    assert (event.shop_domain, event.topic, event.webhook_id, event.event_id) == (SHOP, "app/uninstalled", "delivery-1", "event-1")
    for changed_headers in (
        {**headers, "X-Shopify-Hmac-Sha256": "bad"},
        {**headers, "X-Shopify-Shop-Domain": "another-shop.myshopify.com"},
        {**headers, "X-Shopify-Topic": "unapproved/topic"},
        {k: v for k, v in headers.items() if k != "X-Shopify-Webhook-Id"},
    ):
        with pytest.raises(ShopifyError):
            verify_shopify_webhook(body, changed_headers, secret, expected_shop=SHOP)
    bad_payload = json.dumps({"shop_domain": "another-shop.myshopify.com"}).encode()
    bad_digest = base64.b64encode(hmac.new(secret.encode(), bad_payload, hashlib.sha256).digest()).decode()
    with pytest.raises(ShopifyError) as exc:
        verify_shopify_webhook(bad_payload, {**headers, "X-Shopify-Hmac-Sha256": bad_digest}, secret, expected_shop=SHOP)
    assert exc.value.code == "shop_mismatch"


def test_privacy_verifier_returns_only_minimal_ids_and_never_performs_erasure():
    secret = "app-secret"
    payload = {"shop_id": 123, "shop_domain": SHOP, "customer": {"id": 456, "email": "private@example.com", "phone": "555-0100"}, "orders_to_redact": [7]}
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    headers = {"X-Shopify-Hmac-Sha256": digest, "X-Shopify-Shop-Domain": SHOP, "X-Shopify-Topic": "customers/redact", "X-Shopify-Webhook-Id": "privacy-1"}
    result = verify_privacy_webhook(body, headers, secret, expected_shop=SHOP)
    assert result.request_id == "456"
    assert result.shop_id == "123"
    assert result.processing_status == "AUTHENTICATED_NOT_PERSISTED"
    with pytest.raises(ShopifyError) as mismatch:
        verify_privacy_webhook(body, headers, secret, expected_shop=SHOP, expected_shop_id="999")
    assert mismatch.value.code == "shop_mismatch"
    with pytest.raises(ShopifyError):
        verify_shopify_webhook(body, headers, secret, expected_shop=SHOP, max_body_bytes=1)
    assert not hasattr(result, "email") and not hasattr(result, "orders_to_redact")
    assert "private@example.com" not in repr(result)
    with pytest.raises(ShopifyError):
        verify_privacy_webhook(body, {**headers, "X-Shopify-Topic": "orders/create"}, secret, expected_shop=SHOP)


@pytest.mark.parametrize("include_tests,expected", [(False, ["gid://shopify/Order/2"]),
                                                     (True, ["gid://shopify/Order/1", "gid://shopify/Order/2"])])
def test_test_orders_are_only_included_when_explicitly_enabled(include_tests, expected):
    client = object.__new__(ShopifyGraphQLClient)
    client._page_size = 10
    client._include_test_orders = include_tests
    client.verify_connection = lambda: {"granted_scopes": frozenset({"read_orders"})}
    items = [
        {"id": "gid://shopify/Order/1", "test": True,
         "lineItems": {"edges": [], "pageInfo": {"hasNextPage": False}}},
        {"id": "gid://shopify/Order/2", "test": False,
         "lineItems": {"edges": [], "pageInfo": {"hasNextPage": False}}},
    ]
    client._iterate_connection = lambda *_args, **_kwargs: iter(items)

    records = list(client.iter_orders())

    assert [record.provider_id for record in records] == expected
