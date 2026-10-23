"""Read-only Shopify GraphQL Admin API adapter and webhook verifiers.

This module performs provider reads and authenticates signed webhook payloads.
It does not register shops, persist tokens/events, execute privacy actions, or
promote provider data into KEEL canonical records. Callers must keep tokens in
the existing credential vault and gate persistence on approved source identity.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from src.market_scraper.network_security import UnsafeTargetError
from src.market_scraper.woocommerce import _pinned_transport, _resolve_public_addresses


DEFAULT_API_VERSION = "2026-10"
# Stable versions still supported by Shopify on 2026-10-21. Never use "latest"
# in a request URL; callers may select another currently supported stable version.
SUPPORTED_API_VERSIONS = frozenset({"2026-01", "2026-04", "2026-07", "2026-10"})
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_RETRY_DELAY_SECONDS = 5.0
SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com$", re.ASCII)
PRIVACY_TOPICS = frozenset({"customers/data_request", "customers/redact", "shop/redact"})
ALLOWED_WEBHOOK_TOPICS = PRIVACY_TOPICS | frozenset(
    {"app/uninstalled", "products/create", "products/update", "products/delete", "orders/create", "orders/updated", "orders/cancelled", "orders/paid", "inventory_levels/update"}
)


class ShopifyError(RuntimeError):
    """Sanitized provider error; never includes request credentials or body."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ShopifyRecord:
    """Raw provider payload with its Shopify-scoped GraphQL identity."""

    entity_type: str
    provider_id: str
    payload: Mapping[str, Any]
    parent_provider_id: str | None = None


@dataclass(frozen=True)
class VerifiedShopifyWebhook:
    """HMAC-verified body with delivery headers, not a durable receipt.

    Shopify signs the raw body; delivery metadata headers are not part of that
    HMAC. A receiver must bind them to a durable registered shop/subscription
    and event receipt before any tenant or business side effect.
    """

    shop_domain: str
    topic: str
    webhook_id: str
    payload: Mapping[str, Any]
    event_id: str | None = None


@dataclass(frozen=True)
class AuthenticatedPrivacyRequest:
    """Minimum non-PII identity extracted from an authenticated privacy event.

    This value is in-memory only. The module has no durable persistence and does
    not acknowledge receipt or claim that any privacy operation was completed.
    """

    shop_domain: str
    topic: str
    webhook_id: str
    shop_id: str | None
    request_id: str | None
    processing_status: str = "AUTHENTICATED_NOT_PERSISTED"


def canonical_shop_domain(value: str) -> str:
    """Accept only a bare Shopify-assigned myshopify.com shop hostname."""
    if not isinstance(value, str) or len(value) > 255:
        raise UnsafeTargetError("Shopify shop domain is invalid")
    candidate = value.strip().lower().rstrip(".")
    try:
        parsed = urlsplit("https://" + candidate)
    except ValueError as exc:
        raise UnsafeTargetError("Shopify shop domain is invalid") from exc
    if (
        parsed.hostname != candidate
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not SHOP_DOMAIN_RE.fullmatch(candidate)
    ):
        raise UnsafeTargetError("Shopify shop domain must be a bare myshopify.com hostname")
    return candidate


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return str(value).strip()
    return None


def verify_shopify_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    client_secret: str,
    *,
    expected_shop: str,
    expected_shop_id: str | None = None,
    allowed_topics: Sequence[str] | frozenset[str] = ALLOWED_WEBHOOK_TOPICS,
    max_body_bytes: int = 2 * 1024 * 1024,
) -> VerifiedShopifyWebhook:
    """Verify Shopify's base64 HMAC-SHA256 against the exact raw request bytes."""
    if not isinstance(raw_body, bytes) or len(raw_body) > max_body_bytes or not client_secret:
        raise ShopifyError("invalid_webhook", "Shopify webhook could not be authenticated")
    signature = _header(headers, "X-Shopify-Hmac-Sha256")
    shop_value = _header(headers, "X-Shopify-Shop-Domain")
    topic = _header(headers, "X-Shopify-Topic")
    webhook_id = _header(headers, "X-Shopify-Webhook-Id")
    event_id = _header(headers, "X-Shopify-Event-Id")
    if not signature or not shop_value or not topic or not webhook_id or len(webhook_id) > 512 or any(ord(ch) < 32 for ch in webhook_id):
        raise ShopifyError("invalid_webhook", "Shopify webhook is missing required delivery headers")
    expected = canonical_shop_domain(expected_shop)
    try:
        supplied_shop = canonical_shop_domain(shop_value)
    except UnsafeTargetError as exc:
        raise ShopifyError("invalid_webhook", "Shopify webhook shop identity is invalid") from exc
    if supplied_shop != expected:
        raise ShopifyError("shop_mismatch", "Shopify webhook shop does not match the expected source")
    if topic not in allowed_topics:
        raise ShopifyError("unsupported_topic", "Shopify webhook topic is not enabled")
    try:
        supplied_digest = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        raise ShopifyError("invalid_webhook", "Shopify webhook signature is invalid") from None
    expected_digest = hmac.new(client_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_digest, supplied_digest):
        raise ShopifyError("invalid_webhook", "Shopify webhook signature is invalid")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ShopifyError("invalid_webhook", "Shopify webhook payload is invalid") from None
    if not isinstance(payload, dict):
        raise ShopifyError("invalid_webhook", "Shopify webhook payload is invalid")
    payload_domain = payload.get("shop_domain")
    if payload_domain is not None:
        try:
            if canonical_shop_domain(str(payload_domain)) != supplied_shop:
                raise ShopifyError("shop_mismatch", "Shopify webhook payload shop does not match its headers")
        except UnsafeTargetError as exc:
            raise ShopifyError("shop_mismatch", "Shopify webhook payload shop is invalid") from exc
    if expected_shop_id is not None and payload.get("shop_id") is not None:
        if str(payload["shop_id"]) != str(expected_shop_id):
            raise ShopifyError("shop_mismatch", "Shopify webhook shop ID does not match the expected source")
    if event_id is not None and (len(event_id) > 512 or any(ord(ch) < 32 for ch in event_id)):
        raise ShopifyError("invalid_webhook", "Shopify webhook event identity is invalid")
    return VerifiedShopifyWebhook(supplied_shop, topic, webhook_id, payload, event_id)


def verify_privacy_webhook(
    raw_body: bytes,
    headers: Mapping[str, str],
    client_secret: str,
    *,
    expected_shop: str,
    expected_shop_id: str | None = None,
) -> AuthenticatedPrivacyRequest:
    """Authenticate a mandatory privacy topic and return only minimal IDs.

    This is a verification helper, not an HTTP receiver: callers must not send
    Shopify a success acknowledgment until a durable, auditable receipt exists.
    No deletion, restriction, export, or re-import fence is performed here.
    """
    verified = verify_shopify_webhook(
        raw_body,
        headers,
        client_secret,
        expected_shop=expected_shop,
        expected_shop_id=expected_shop_id,
        allowed_topics=PRIVACY_TOPICS,
    )
    shop_id = verified.payload.get("shop_id")
    if isinstance(shop_id, bool) or not isinstance(shop_id, (str, int)):
        raise ShopifyError("invalid_webhook", "Shopify privacy request is missing a valid shop identity")
    if not verified.payload.get("shop_domain"):
        raise ShopifyError("invalid_webhook", "Shopify privacy request is missing its signed shop domain")
    request_id: str | None = None
    if verified.topic == "customers/data_request":
        request = verified.payload.get("data_request")
        request_id = str(request.get("id")) if isinstance(request, dict) and request.get("id") is not None else None
    elif verified.topic == "customers/redact":
        customer = verified.payload.get("customer")
        request_id = str(customer.get("id")) if isinstance(customer, dict) and customer.get("id") is not None else None
    if verified.topic != "shop/redact" and request_id is None:
        raise ShopifyError("invalid_webhook", "Shopify privacy request is missing its request identity")
    return AuthenticatedPrivacyRequest(
        shop_domain=verified.shop_domain,
        topic=verified.topic,
        webhook_id=verified.webhook_id,
        shop_id=str(shop_id) if shop_id is not None else None,
        request_id=request_id,
    )


SHOP_QUERY = """query KeelVerifyShop { shop { id myshopifyDomain currencyCode plan { partnerDevelopment } } currentAppInstallation { accessScopes { handle } } }"""
PRODUCTS_QUERY = """query KeelProducts($first:Int!,$after:String,$variantFirst:Int!){ products(first:$first,after:$after) { edges { cursor node { id title handle status vendor createdAt updatedAt variants(first:$variantFirst) { edges { cursor node { id title sku barcode updatedAt price { amount currencyCode } compareAtPrice { amount currencyCode } inventoryItem { id tracked } } } pageInfo { hasNextPage endCursor } } } } pageInfo { hasNextPage endCursor } } }"""
PRODUCT_VARIANTS_QUERY = """query KeelProductVariants($id:ID!,$first:Int!,$after:String){ product(id:$id) { variants(first:$first,after:$after) { edges { cursor node { id title sku barcode updatedAt price { amount currencyCode } compareAtPrice { amount currencyCode } inventoryItem { id tracked } } } pageInfo { hasNextPage endCursor } } } }"""
ORDERS_QUERY = """query KeelOrders($first:Int!,$after:String,$lineFirst:Int!){ orders(first:$first,after:$after,sortKey:UPDATED_AT) { edges { cursor node { id name createdAt updatedAt currencyCode displayFinancialStatus displayFulfillmentStatus cancelledAt test totalPriceSet { shopMoney { amount currencyCode } } totalTaxSet { shopMoney { amount currencyCode } } totalShippingPriceSet { shopMoney { amount currencyCode } } totalDiscountsSet { shopMoney { amount currencyCode } } lineItems(first:$lineFirst) { edges { cursor node { id title quantity sku variant { id product { id } } originalUnitPriceSet { shopMoney { amount currencyCode } } discountedTotalSet(withCodeDiscounts:true) { shopMoney { amount currencyCode } } } } pageInfo { hasNextPage endCursor } } } } pageInfo { hasNextPage endCursor } } }"""
ORDER_LINES_QUERY = """query KeelOrderLines($id:ID!,$first:Int!,$after:String){ order(id:$id) { lineItems(first:$first,after:$after) { edges { cursor node { id title quantity sku variant { id product { id } } originalUnitPriceSet { shopMoney { amount currencyCode } } discountedTotalSet(withCodeDiscounts:true) { shopMoney { amount currencyCode } } } } pageInfo { hasNextPage endCursor } } } }"""
LOCATIONS_QUERY = """query KeelLocations($first:Int!,$after:String,$levelFirst:Int!){ locations(first:$first,after:$after) { edges { cursor node { id name isActive inventoryLevels(first:$levelFirst) { edges { cursor node { id updatedAt item { id sku tracked variant { id } } quantities(names:[\"available\",\"on_hand\"]) { name quantity } } } pageInfo { hasNextPage endCursor } } } } pageInfo { hasNextPage endCursor } } }"""
LOCATION_LEVELS_QUERY = """query KeelLocationLevels($id:ID!,$first:Int!,$after:String){ location(id:$id) { inventoryLevels(first:$first,after:$after) { edges { cursor node { id updatedAt item { id sku tracked variant { id } } quantities(names:[\"available\",\"on_hand\"]) { name quantity } } } pageInfo { hasNextPage endCursor } } } }"""


class ShopifyGraphQLClient:
    """Bounded, read-only Shopify Admin GraphQL client; no OAuth or persistence."""

    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        *,
        api_version: str = DEFAULT_API_VERSION,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_retry_delay: float = DEFAULT_MAX_RETRY_DELAY_SECONDS,
        resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
        transport_factory: Callable[[str], httpx.BaseTransport] = _pinned_transport,
        sleeper: Callable[[float], None] = time.sleep,
        include_test_orders: bool = False,
    ):
        self.shop_domain = canonical_shop_domain(shop_domain)
        if not access_token or len(access_token) > 8192:
            raise ValueError("Shopify access token is required")
        if api_version not in SUPPORTED_API_VERSIONS:
            raise ValueError("Shopify API version must be an explicitly supported stable version")
        if not 1 <= page_size <= 250 or max_pages < 1 or max_response_bytes < 1024:
            raise ValueError("Shopify request bounds are invalid")
        if max_retries < 0 or max_retries > 5 or not 0 <= max_retry_delay <= 30:
            raise ValueError("Shopify retry bounds are invalid")
        if not isinstance(include_test_orders, bool):
            raise ValueError("Shopify test-order setting must be boolean")
        self.api_version = api_version
        self._token = access_token
        self._page_size = page_size
        self._max_pages = max_pages
        self._max_response_bytes = max_response_bytes
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_retry_delay = max_retry_delay
        self._resolver = resolver
        self._transport_factory = transport_factory
        self._sleeper = sleeper
        self._include_test_orders = include_test_orders
        self._endpoint = f"https://{self.shop_domain}/admin/api/{api_version}/graphql.json"

    def execute_query(self, query: str, variables: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Execute a GraphQL query only. Mutations/subscriptions are rejected."""
        if not isinstance(query, str) or len(query) > 100_000 or not re.search(r"\bquery\b", query, re.IGNORECASE):
            raise ValueError("Only bounded read-only Shopify GraphQL queries are supported")
        if re.search(r"\b(mutation|subscription)\b", query, re.IGNORECASE):
            raise ValueError("Only read-only Shopify GraphQL queries are supported")
        try:
            encoded = json.dumps({"query": query, "variables": dict(variables or {})}, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Shopify query variables must be JSON serializable") from exc
        if len(encoded) > 256_000:
            raise ValueError("Shopify query request exceeded the configured size limit")

        for attempt in range(self._max_retries + 1):
            try:
                result, response_headers, _http_status = self._post(encoded)
            except _RetryableHTTP as exc:
                if attempt >= self._max_retries:
                    raise ShopifyError(exc.code, str(exc), retryable=True) from exc
                self._sleeper(min(exc.delay, self._max_retry_delay))
                continue
            except ShopifyError as exc:
                if not exc.retryable or attempt >= self._max_retries:
                    raise
                self._sleeper(min(1.0, self._max_retry_delay))
                continue
            api_version = response_headers.get("X-Shopify-API-Version")
            if api_version and api_version != self.api_version:
                raise ShopifyError("api_version_mismatch", "Shopify served a different API version than requested")
            errors = result.get("errors")
            if errors:
                delay = _graphql_retry_delay(errors, result.get("extensions"))
                if delay is not None and attempt < self._max_retries:
                    self._sleeper(min(delay, self._max_retry_delay))
                    continue
                code = _graphql_error_code(errors)
                raise ShopifyError(code, "Shopify GraphQL request returned an error", retryable=(code == "throttled"))
            data = result.get("data")
            if not isinstance(data, dict):
                raise ShopifyError("invalid_response", "Shopify GraphQL response contained no data")
            return data
        raise ShopifyError("throttled", "Shopify GraphQL request remained throttled", retryable=True)

    def _post(self, body: bytes) -> tuple[Mapping[str, Any], httpx.Headers, int]:
        try:
            addresses = _resolve_public_addresses(self._endpoint, self._resolver)
        except UnsafeTargetError:
            raise
        except Exception as exc:
            raise ShopifyError("dns_error", "Shopify DNS lookup failed", retryable=True) from exc
        try:
            with httpx.Client(
                transport=self._transport_factory(addresses[0]),
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": self._token,
                    "User-Agent": "KEEL-Shopify/1",
                },
            ) as client:
                with client.stream("POST", self._endpoint, content=body) as response:
                    if response.is_redirect:
                        raise ShopifyError("redirect_rejected", "Shopify redirected the GraphQL request")
                    if response.status_code == 401:
                        raise ShopifyError("invalid_credentials", "Shopify rejected the access token")
                    if response.status_code == 403:
                        raise ShopifyError("insufficient_permissions", "Shopify denied the requested access")
                    if response.status_code == 429:
                        delay = _retry_after(response.headers.get("Retry-After"), self._max_retry_delay)
                        raise _RetryableHTTP("throttled", "Shopify rate limited the request", delay)
                    if response.status_code >= 500:
                        raise _RetryableHTTP("provider_unavailable", "Shopify is temporarily unavailable", min(1.0, self._max_retry_delay))
                    if response.status_code >= 400:
                        raise ShopifyError("provider_rejected", f"Shopify rejected the request (HTTP {response.status_code})")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > self._max_response_bytes:
                            raise ShopifyError("response_too_large", "Shopify response exceeded the configured limit")
                    headers = response.headers
                    status = response.status_code
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ShopifyError("invalid_response", "Shopify returned invalid JSON") from None
            if not isinstance(parsed, dict):
                raise ShopifyError("invalid_response", "Shopify returned an invalid GraphQL response")
            return parsed, headers, status
        except _RetryableHTTP as exc:
            # The caller owns the bounded retry loop for these known read-only queries.
            raise exc
        except ShopifyError:
            raise
        except httpx.TimeoutException as exc:
            raise ShopifyError("timeout", "Shopify request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ShopifyError("connection_error", "Shopify request failed", retryable=True) from exc

    def verify_connection(self) -> Mapping[str, Any]:
        data = self.execute_query(SHOP_QUERY)
        shop = data.get("shop")
        installation = data.get("currentAppInstallation")
        if not isinstance(shop, dict) or not isinstance(installation, dict):
            raise ShopifyError("invalid_response", "Shopify connection response was incomplete")
        try:
            returned_domain = canonical_shop_domain(str(shop.get("myshopifyDomain", "")))
        except UnsafeTargetError as exc:
            raise ShopifyError("invalid_response", "Shopify returned an invalid shop identity") from exc
        if returned_domain != self.shop_domain or not shop.get("id"):
            raise ShopifyError("shop_mismatch", "Authenticated Shopify shop did not match the requested source")
        scopes_value = installation.get("accessScopes")
        if not isinstance(scopes_value, list) or any(not isinstance(item, dict) for item in scopes_value):
            raise ShopifyError("invalid_response", "Shopify returned invalid access scopes")
        scopes = frozenset(str(item.get("handle")) for item in scopes_value if item.get("handle"))
        return {
            "verified": True,
            "shop_domain": returned_domain,
            "shop_id": str(shop["id"]),
            "currency_code": shop.get("currencyCode"),
            "development_store": (shop.get("plan") or {}).get("partnerDevelopment") is True
            if isinstance(shop.get("plan") or {}, dict) else False,
            "api_version": self.api_version,
            "granted_scopes": scopes,
            "orders_readable": "read_orders" in scopes,
            "has_read_all_orders": "read_all_orders" in scopes,
            "order_history_access": (
                "unavailable" if "read_orders" not in scopes
                else ("all_orders" if "read_all_orders" in scopes else "provider_default_recent_window")
            ),
            "order_history_note": "Shopify limits default order access to the most recent 60 days unless read_all_orders is granted.",
        }

    @staticmethod
    def require_scopes(verification: Mapping[str, Any], required: Sequence[str]) -> None:
        granted = verification.get("granted_scopes")
        if not isinstance(granted, (set, frozenset)) or not set(required).issubset(granted):
            raise ShopifyError("insufficient_permissions", "Shopify connection is missing a required read scope")

    def iter_products(self) -> Iterator[ShopifyRecord]:
        self.require_scopes(self.verify_connection(), ("read_products",))
        nested_page = min(self._page_size, 250)
        for product in self._iterate_connection(PRODUCTS_QUERY, ("products",), {"variantFirst": nested_page}):
            product_id = _gid(product.get("id"), "product")
            yield ShopifyRecord("product", product_id, product)
            variants = product.get("variants")
            if not isinstance(variants, dict):
                raise ShopifyError("invalid_response", "Shopify product response omitted variants")
            initial_edges = _edge_nodes(variants)
            for variant in initial_edges:
                yield ShopifyRecord("variant", _gid(variant.get("id"), "variant"), variant, product_id)
            page_info = variants.get("pageInfo")
            if isinstance(page_info, dict) and page_info.get("hasNextPage"):
                after = _cursor(page_info.get("endCursor"))
                yield from self._iterate_connection(
                    PRODUCT_VARIANTS_QUERY, ("product", "variants"), {"id": product_id}, initial_after=after
                , parent_id=product_id, entity_type="variant")

    def iter_orders(self) -> Iterator[ShopifyRecord]:
        self.require_scopes(self.verify_connection(), ("read_orders",))
        nested_page = min(self._page_size, 250)
        for order in self._iterate_connection(ORDERS_QUERY, ("orders",), {"lineFirst": nested_page}):
            if order.get("test") is True and not self._include_test_orders:
                continue
            order_id = _gid(order.get("id"), "order")
            yield ShopifyRecord("order", order_id, order)
            lines = order.get("lineItems")
            if not isinstance(lines, dict):
                raise ShopifyError("invalid_response", "Shopify order response omitted line items")
            for line in _edge_nodes(lines):
                yield ShopifyRecord("line_item", _gid(line.get("id"), "line item"), line, order_id)
            page_info = lines.get("pageInfo")
            if isinstance(page_info, dict) and page_info.get("hasNextPage"):
                after = _cursor(page_info.get("endCursor"))
                yield from self._iterate_connection(
                    ORDER_LINES_QUERY, ("order", "lineItems"), {"id": order_id}, initial_after=after
                , parent_id=order_id, entity_type="line_item")

    def iter_inventory(self) -> Iterator[ShopifyRecord]:
        self.require_scopes(self.verify_connection(), ("read_inventory",))
        nested_page = min(self._page_size, 250)
        for location in self._iterate_connection(LOCATIONS_QUERY, ("locations",), {"levelFirst": nested_page}):
            location_id = _gid(location.get("id"), "location")
            yield ShopifyRecord("location", location_id, location)
            levels = location.get("inventoryLevels")
            if not isinstance(levels, dict):
                raise ShopifyError("invalid_response", "Shopify location response omitted inventory levels")
            for level in _edge_nodes(levels):
                yield ShopifyRecord("inventory_level", _gid(level.get("id"), "inventory level"), level, location_id)
            page_info = levels.get("pageInfo")
            if isinstance(page_info, dict) and page_info.get("hasNextPage"):
                after = _cursor(page_info.get("endCursor"))
                yield from self._iterate_connection(
                    LOCATION_LEVELS_QUERY, ("location", "inventoryLevels"), {"id": location_id}, initial_after=after
                , parent_id=location_id, entity_type="inventory_level")

    def _iterate_connection(
        self,
        query: str,
        path: tuple[str, ...],
        variables: Mapping[str, Any],
        *,
        initial_after: str | None = None,
        parent_id: str | None = None,
        entity_type: str | None = None,
        seen_cursors: set[str] | None = None,
    ) -> Iterator[Any]:
        after = initial_after
        cursors: set[str] = set(seen_cursors or ())
        for page_number in range(self._max_pages):
            data = self.execute_query(
                query,
                {"first": self._page_size, "after": after, **variables},
            )
            connection: Any = data
            for part in path:
                if not isinstance(connection, dict) or part not in connection:
                    raise ShopifyError("invalid_response", "Shopify connection response was incomplete")
                connection = connection[part]
            if not isinstance(connection, dict):
                raise ShopifyError("invalid_response", "Shopify connection response was invalid")
            edges = connection.get("edges")
            page_info = connection.get("pageInfo")
            if not isinstance(edges, list) or not isinstance(page_info, dict):
                raise ShopifyError("invalid_response", "Shopify connection page was invalid")
            page_cursors = [_cursor(edge.get("cursor")) for edge in edges if isinstance(edge, dict)]
            if len(page_cursors) != len(edges) or len(set(page_cursors)) != len(page_cursors):
                raise ShopifyError("pagination_nonprogress", "Shopify repeated or omitted a connection cursor")
            if edges and page_info.get("endCursor") != page_cursors[-1]:
                raise ShopifyError("pagination_nonprogress", "Shopify connection end cursor did not match its final edge")
            for edge in edges:
                if not isinstance(edge, dict) or not isinstance(edge.get("node"), dict):
                    raise ShopifyError("invalid_response", "Shopify returned an invalid connection edge")
                cursor = _cursor(edge.get("cursor"))
                if cursor in cursors:
                    raise ShopifyError("pagination_nonprogress", "Shopify repeated a connection cursor")
                cursors.add(cursor)
                node = edge["node"]
                if entity_type:
                    yield ShopifyRecord(entity_type, _gid(node.get("id"), entity_type), node, parent_id)
                else:
                    yield node
            if not page_info.get("hasNextPage"):
                return
            next_cursor = _cursor(page_info.get("endCursor"))
            if next_cursor in cursors or next_cursor == after:
                raise ShopifyError("pagination_nonprogress", "Shopify pagination did not advance")
            after = next_cursor
        raise ShopifyError("page_limit", "Shopify pagination exceeded the configured page limit")


class _RetryableHTTP(ShopifyError):
    def __init__(self, code: str, message: str, delay: float):
        super().__init__(code, message, retryable=True)
        self.delay = delay


def _edge_cursors(connection: Mapping[str, Any]) -> set[str]:
    edges = connection.get("edges")
    if not isinstance(edges, list):
        raise ShopifyError("invalid_response", "Shopify connection edges were invalid")
    cursors = [_cursor(edge.get("cursor")) for edge in edges if isinstance(edge, dict)]
    if len(cursors) != len(edges) or len(cursors) != len(set(cursors)):
        raise ShopifyError("pagination_nonprogress", "Shopify repeated or omitted a connection cursor")
    page_info = connection.get("pageInfo")
    if not isinstance(page_info, dict):
        raise ShopifyError("invalid_response", "Shopify connection page info was invalid")
    if edges and page_info.get("endCursor") != cursors[-1]:
        raise ShopifyError("pagination_nonprogress", "Shopify connection end cursor did not match its final edge")
    return set(cursors)


def _edge_nodes(connection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    _edge_cursors(connection)
    edges = connection["edges"]
    if any(not isinstance(edge, dict) or not isinstance(edge.get("node"), dict) for edge in edges):
        raise ShopifyError("invalid_response", "Shopify connection edge was invalid")
    return [edge["node"] for edge in edges]


def _gid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("gid://shopify/") or len(value) > 512:
        raise ShopifyError("invalid_response", f"Shopify returned an invalid {label} identity")
    return value


def _cursor(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ShopifyError("pagination_nonprogress", "Shopify pagination returned an invalid cursor")
    return value


def _graphql_error_code(errors: Any) -> str:
    if isinstance(errors, list):
        codes = {
            str(error.get("extensions", {}).get("code", "")).upper()
            for error in errors
            if isinstance(error, dict) and isinstance(error.get("extensions"), dict)
        }
        if "THROTTLED" in codes:
            return "throttled"
        if codes & {"ACCESS_DENIED", "FORBIDDEN"}:
            return "insufficient_permissions"
    return "graphql_error"


def _graphql_retry_delay(errors: Any, extensions: Any) -> float | None:
    if _graphql_error_code(errors) != "throttled":
        return None
    try:
        cost = extensions["cost"]
        status = cost["throttleStatus"]
        requested = float(cost.get("requestedQueryCost", 0))
        available = float(status["currentlyAvailable"])
        restore_rate = float(status["restoreRate"])
        if not all(math.isfinite(value) for value in (requested, available, restore_rate)) or restore_rate <= 0:
            return None
        return max(0.0, (requested - available) / restore_rate)
    except (KeyError, TypeError, ValueError):
        return None


def _retry_after(value: str | None, bound: float) -> float:
    try:
        delay = float(value or 0)
    except (TypeError, ValueError):
        delay = 0.0
    if not math.isfinite(delay):
        delay = 0.0
    return max(0.0, min(delay, bound))
