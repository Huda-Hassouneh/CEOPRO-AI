import base64
import hashlib
import hmac
import json
import socket

import httpcore
import httpx
import pytest

from src.market_scraper.network_security import UnsafeTargetError
from src.market_scraper.woocommerce import (
    WooCommerceClient,
    WooCommerceError,
    _PinnedBackend,
    _pinned_transport,
    canonical_store_url,
    verify_webhook_signature,
)


def _resolver(address="8.8.8.8"):
    return lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]


def _client(handler, **kwargs):
    return WooCommerceClient(
        "https://shop.example.test",
        "ck_test",
        "cs_test",
        resolver=_resolver(),
        transport_factory=lambda _ip: httpx.MockTransport(handler),
        **kwargs,
    )


def test_url_requires_https_and_rejects_embedded_credentials_or_query():
    assert canonical_store_url(" HTTPS://Shop.Example.Test/store/ ") == "https://shop.example.test/store"
    for url in (
        "http://shop.example.test",
        "https://user:pass@shop.example.test",
        "https://shop.example.test?consumer_key=secret",
        "https://shop.example.test/#fragment",
        "https://127.0.0.1",
    ):
        with pytest.raises(UnsafeTargetError):
            canonical_store_url(url)


def test_connection_verification_uses_wc_v3_and_https_basic_auth():
    observed = []

    def handler(request):
        observed.append(request)
        if request.url.path.endswith("/settings/general/woocommerce_currency"):
            return httpx.Response(200, json={"id": "woocommerce_currency", "value": "USD"})
        return httpx.Response(200, json=[])

    assert _client(handler).verify_connection() == {
        "verified": True,
        "api": "wc/v3",
        "products_accessible": True,
        "orders_accessible": True,
        "currency_code": "USD",
        "canonical_store_url": "https://shop.example.test",
    }
    request = observed[0]
    assert request.url.path == "/wp-json/wc/v3/products"
    assert dict(request.url.params) == {"per_page": "1", "page": "1"}
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"ck_test:cs_test").decode()
    assert "ck_test" not in str(request.url) and "cs_test" not in str(request.url)
    assert [request.url.path for request in observed] == [
        "/wp-json/wc/v3/products", "/wp-json/wc/v3/orders",
        "/wp-json/wc/v3/settings/general/woocommerce_currency",
    ]


def test_connection_verification_requires_order_and_currency_read_contract():
    def denied_orders(request):
        if request.url.path.endswith("/orders"):
            return httpx.Response(403, json={"code": "woocommerce_rest_cannot_view"})
        if request.url.path.endswith("/settings/general/woocommerce_currency"):
            return httpx.Response(200, json={"id": "woocommerce_currency", "value": "USD"})
        return httpx.Response(200, json=[])

    with pytest.raises(WooCommerceError) as error:
        _client(denied_orders).verify_connection()
    assert error.value.code == "authentication_failed"

    invalid_currency = _client(lambda request: httpx.Response(
        200, json={"value": "US"} if request.url.path.endswith("/woocommerce_currency") else []
    ))
    with pytest.raises(WooCommerceError) as error:
        invalid_currency.verify_connection()
    assert error.value.code == "invalid_response"


def test_products_variations_and_orders_are_returned_with_provider_identity():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/products"):
            return httpx.Response(200, json=[{"id": 12, "type": "variable", "variations": [91]}])
        if request.url.path.endswith("/products/12/variations"):
            return httpx.Response(200, json=[{"id": 91, "sku": "VAR-1", "stock_quantity": 3}])
        if request.url.path.endswith("/orders"):
            return httpx.Response(200, json=[{"id": 700, "status": "processing", "line_items": []}])
        raise AssertionError(request.url)

    client = _client(handler)
    products = list(client.iter_products())
    orders = list(client.iter_orders())
    assert [(r.entity_type, r.provider_id, r.parent_provider_id) for r in products] == [
        ("product", 12, None),
        ("variation", 91, 12),
    ]
    assert products[1].payload["stock_quantity"] == 3
    assert [(r.entity_type, r.provider_id) for r in orders] == [("order", 700)]
    assert calls.count("/wp-json/wc/v3/products/12/variations") == 1


def test_pagination_uses_same_api_origin_and_yields_each_page():
    second = "https://shop.example.test/wp-json/wc/v3/products?per_page=2&page=2"

    def handler(request):
        if request.url.params.get("page") == "1":
            return httpx.Response(
                200,
                json=[{"id": 1, "type": "simple"}],
                headers={"Link": f'<{second}>; rel="next"'},
            )
        return httpx.Response(200, json=[{"id": 2, "type": "simple"}])

    records = list(_client(handler, page_size=2).iter_products())
    assert [record.provider_id for record in records] == [1, 2]


def test_missing_total_follows_full_pages_and_repeated_page_fails_closed():
    def missing_total(request):
        page = request.url.params["page"]
        return httpx.Response(200, json=[{"id": int(page)}] if page == "1" else [])

    records = list(_client(missing_total, page_size=1).iter_products())
    assert [record.provider_id for record in records] == [1]

    def repeated_page(_request):
        return httpx.Response(200, json=[{"id": 1}], headers={"X-WP-TotalPages": "3"})

    with pytest.raises(WooCommerceError, match="repeated a page"):
        list(_client(repeated_page, page_size=1).iter_products())


def test_pagination_rejects_external_origin_and_enforces_page_bound():
    external = "https://attacker.example/wp-json/wc/v3/products?page=2"
    client = _client(lambda _request: httpx.Response(200, json=[{"id": 1}]))
    with pytest.raises(UnsafeTargetError):
        list(client._pages(external))

    too_many = _client(
        lambda _request: httpx.Response(200, json=[{"id": 1}], headers={"X-WP-TotalPages": "2"}),
        max_pages=1,
    )
    with pytest.raises(WooCommerceError, match="page limit"):
        list(too_many._pages("https://shop.example.test/wp-json/wc/v3/products?page=1"))


def test_invalid_credentials_redirects_and_provider_errors_are_sanitized():
    for status, code in ((401, "authentication_failed"), (403, "authentication_failed"), (429, "rate_limited"), (503, "provider_unavailable")):
        client = _client(lambda _request, status=status: httpx.Response(status, text="secret=not-logged"))
        with pytest.raises(WooCommerceError) as error:
            client.verify_connection()
        assert error.value.code == code
        assert "secret" not in str(error.value)

    redirecting = _client(lambda _request: httpx.Response(302, headers={"Location": "https://elsewhere.test/"}))
    with pytest.raises(WooCommerceError, match="redirected"):
        redirecting.verify_connection()


def test_private_dns_is_rejected_before_transport_creation():
    invoked = []
    client = WooCommerceClient(
        "https://shop.example.test",
        "ck",
        "cs",
        resolver=_resolver("10.2.3.4"),
        transport_factory=lambda _ip: invoked.append(_ip),
    )
    with pytest.raises(UnsafeTargetError):
        client.verify_connection()
    assert invoked == []


def test_pinned_backend_connects_to_resolved_ip_not_origin_host(monkeypatch):
    backend = _PinnedBackend("8.8.4.4")
    calls = []

    class FakeNetworkBackend:
        def connect_tcp(self, host, port, **kwargs):
            calls.append((host, port, kwargs))
            return "stream"

        def sleep(self, seconds):
            pass

    backend._backend = FakeNetworkBackend()
    assert backend.connect_tcp("shop.example.test", 443, timeout=3) == "stream"
    assert calls[0][0:2] == ("8.8.4.4", 443)


def test_pinned_httpx_transport_constructs_with_real_httpcore_pool():
    transport = _pinned_transport("8.8.4.4")
    try:
        assert isinstance(transport._pool, httpcore.ConnectionPool)
        assert isinstance(transport._pool._network_backend, _PinnedBackend)
    finally:
        transport.close()


def test_webhook_signature_verifies_raw_body_with_constant_contract():
    body = json.dumps({"id": 55, "status": "processing"}, separators=(",", ":")).encode()
    secret = "synthetic-webhook-secret"
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    assert verify_webhook_signature(body, signature, secret)
    assert not verify_webhook_signature(body + b" ", signature, secret)
    assert not verify_webhook_signature(body, "not-base64", secret)
    assert not verify_webhook_signature(body, signature, "wrong-secret")
