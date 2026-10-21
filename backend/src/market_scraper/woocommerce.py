"""Read-only WooCommerce REST API v3 adapter.

This module verifies a store and fetches provider records without mapping them
to KEEL canonical entities or advancing a sync checkpoint. Callers must keep
the store credential in the existing vault and must not treat fetched records
as promoted business data.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpcore
import httpx

from src.market_scraper.network_security import UnsafeTargetError


DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PAGE_SIZE = 10  # WooCommerce REST API default; no undocumented max assumed.
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_API_ROOT = "/wp-json/wc/v3"


class WooCommerceError(RuntimeError):
    """Sanitized provider error safe to record in operational status."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class WooRecord:
    """Unmodified provider payload plus its provider-scoped identity."""

    entity_type: str
    provider_id: int
    payload: Mapping[str, Any]
    parent_provider_id: int | None = None


Resolver = Callable[..., list[tuple[Any, ...]]]


def canonical_store_url(value: str) -> str:
    """Validate and normalize a public HTTPS shop origin/path.

    Consumer keys are never accepted in the URL. A shop may be installed below
    a path prefix, which is retained when forming the REST API root.
    """
    if not isinstance(value, str) or len(value) > 2048:
        raise UnsafeTargetError("store URL is invalid")
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError as exc:
        raise UnsafeTargetError("store URL is invalid") from exc
    if (
        parts.scheme.lower() != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise UnsafeTargetError("store URL must be HTTPS without credentials, query, or fragment")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise UnsafeTargetError("store URL must resolve to a public host")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise UnsafeTargetError("store URL must resolve to a public host")
    netloc = f"[{host}]" if ":" in host else host
    if port and port != 443:
        netloc = f"{netloc}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit(("https", netloc, path, "", ""))


def _resolve_public_addresses(url: str, resolver: Resolver) -> tuple[str, ...]:
    host = urlsplit(url).hostname
    if not host:
        raise UnsafeTargetError("store URL is invalid")
    try:
        literal = ipaddress.ip_address(host)
        addresses = {str(literal)}
    except ValueError:
        try:
            answers = resolver(host, urlsplit(url).port or 443, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise WooCommerceError("dns_error", "WooCommerce store DNS lookup failed", retryable=True) from exc
        addresses = {answer[4][0].split("%", 1)[0] for answer in answers}
    if not addresses:
        raise WooCommerceError("dns_error", "WooCommerce store DNS lookup returned no addresses", retryable=True)
    normalized: set[str] = set()
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeTargetError("store DNS returned an invalid address") from exc
        if not parsed.is_global:
            raise UnsafeTargetError("store DNS resolved to a prohibited address")
        normalized.add(str(parsed))
    return tuple(sorted(normalized, key=lambda item: (ipaddress.ip_address(item).version, item)))


class _PinnedBackend(httpcore.NetworkBackend):
    """Pin TCP to a previously validated address while TLS uses the URL host."""

    def __init__(self, address: str):
        self._address = address
        self._backend = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return self._backend.connect_tcp(
            self._address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.UnsupportedProtocol("Unix sockets are not supported for WooCommerce stores")

    def sleep(self, seconds):
        return self._backend.sleep(seconds)


def _pinned_transport(address: str) -> httpx.HTTPTransport:
    # HTTPX has no public DNS-pinning hook. Build its documented httpcore pool
    # with a per-request NetworkBackend. The origin URL remains unchanged, so
    # Host, certificate validation and TLS SNI use the provider hostname.
    transport = httpx.HTTPTransport(trust_env=False, http2=False, retries=0)
    old_pool = transport._pool  # type: ignore[attr-defined]
    transport._pool = httpcore.ConnectionPool(  # type: ignore[attr-defined]
        ssl_context=old_pool._ssl_context,
        max_connections=1,
        max_keepalive_connections=0,
        keepalive_expiry=None,
        http1=True,
        http2=False,
        retries=0,
        network_backend=_PinnedBackend(address),
    )
    old_pool.close()
    return transport


class WooCommerceClient:
    """Small read-only client for documented WooCommerce REST API v3 resources."""

    def __init__(
        self,
        store_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        resolver: Resolver = socket.getaddrinfo,
        transport_factory: Callable[[str], httpx.BaseTransport] = _pinned_transport,
    ):
        self.store_url = canonical_store_url(store_url)
        if not consumer_key or not consumer_secret:
            raise ValueError("WooCommerce REST credentials are required")
        if not 1 <= page_size <= 100 or max_pages < 1 or max_response_bytes < 1024:
            raise ValueError("WooCommerce request bounds are invalid")
        self._auth = httpx.BasicAuth(consumer_key, consumer_secret)
        self._timeout = timeout
        self._page_size = page_size
        self._max_pages = max_pages
        self._max_response_bytes = max_response_bytes
        self._resolver = resolver
        self._transport_factory = transport_factory
        self._api_root = self.store_url + _API_ROOT

    def _get_json(self, url: str) -> tuple[Any, httpx.Headers]:
        self._validate_api_url(url)
        addresses = _resolve_public_addresses(url, self._resolver)
        try:
            with httpx.Client(
                transport=self._transport_factory(addresses[0]),
                auth=self._auth,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept": "application/json", "User-Agent": "KEEL-WooCommerce/1"},
            ) as client:
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        raise WooCommerceError("redirect_rejected", "WooCommerce redirected the request")
                    if response.status_code in {401, 403}:
                        raise WooCommerceError("authentication_failed", "WooCommerce rejected the REST credentials")
                    if response.status_code == 429:
                        raise WooCommerceError("rate_limited", "WooCommerce rate limited the request", retryable=True)
                    if response.status_code >= 500:
                        raise WooCommerceError("provider_unavailable", "WooCommerce is temporarily unavailable", retryable=True)
                    if response.status_code >= 400:
                        raise WooCommerceError("provider_rejected", f"WooCommerce rejected the request (HTTP {response.status_code})")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > self._max_response_bytes:
                            raise WooCommerceError("response_too_large", "WooCommerce response exceeded the configured limit")
                    headers = response.headers
            try:
                return json.loads(data), headers
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise WooCommerceError("invalid_response", "WooCommerce returned invalid JSON") from exc
        except WooCommerceError:
            raise
        except httpx.TimeoutException as exc:
            raise WooCommerceError("timeout", "WooCommerce request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise WooCommerceError("connection_error", "WooCommerce request failed", retryable=True) from exc

    def _validate_api_url(self, url: str) -> None:
        base = urlsplit(self._api_root)
        candidate = urlsplit(url)
        if (
            candidate.scheme != "https"
            or (candidate.hostname or "").lower().rstrip(".") != (base.hostname or "").lower().rstrip(".")
            or candidate.port != base.port
            or not candidate.path.startswith(base.path + "/")
            or candidate.username is not None
            or candidate.password is not None
            or candidate.fragment
        ):
            raise UnsafeTargetError("WooCommerce pagination left the approved API origin")
        query_names = {name.lower() for name in parse_qs(candidate.query, keep_blank_values=True)}
        if {"consumer_key", "consumer_secret"} & query_names:
            raise UnsafeTargetError("WooCommerce pagination attempted query-string credentials")

    def verify_connection(self) -> Mapping[str, Any]:
        """Verify REST access by making an actual bounded products request."""
        data, _ = self._get_json(f"{self._api_root}/products?per_page=1&page=1")
        if not isinstance(data, list):
            raise WooCommerceError("invalid_response", "WooCommerce products response was not a list")
        return {"verified": True, "api": "wc/v3", "products_accessible": True}

    def _pages(self, url: str) -> Iterator[list[Mapping[str, Any]]]:
        next_url: str | None = url
        visited: set[str] = set()
        page_hashes: set[str] = set()
        pages = 0
        while next_url:
            self._validate_api_url(next_url)
            if next_url in visited:
                raise WooCommerceError("pagination_loop", "WooCommerce pagination repeated a page")
            visited.add(next_url)
            pages += 1
            if pages > self._max_pages:
                raise WooCommerceError("page_limit", "WooCommerce pagination exceeded the configured page limit")
            data, headers = self._get_json(next_url)
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise WooCommerceError("invalid_response", "WooCommerce resource response was not a list of objects")
            page_hash = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            if data and page_hash in page_hashes:
                raise WooCommerceError("pagination_nonprogress", "WooCommerce repeated a page of records")
            page_hashes.add(page_hash)
            yield data
            link_next = _next_link(headers.get("Link", ""))
            if link_next:
                self._validate_api_url(link_next)
                next_url = link_next
                continue
            total_pages = _positive_int(headers.get("X-WP-TotalPages"))
            if total_pages is not None and pages < total_pages:
                parsed = urlsplit(next_url)
                query = parse_qs(parsed.query, keep_blank_values=True)
                query["page"] = [str(pages + 1)]
                next_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))
            elif total_pages is None and len(data) >= self._page_size:
                parsed = urlsplit(next_url)
                query = parse_qs(parsed.query, keep_blank_values=True)
                query["page"] = [str(pages + 1)]
                next_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))
            else:
                next_url = None

    def iter_products(self) -> Iterator[WooRecord]:
        """Yield raw products and child variations; no canonical matching occurs."""
        product_url = f"{self._api_root}/products?per_page={self._page_size}&page=1"
        for page in self._pages(product_url):
            for product in page:
                provider_id = _provider_id(product)
                yield WooRecord("product", provider_id, product)
                variation_ids = product.get("variations") or []
                if product.get("type") != "variable" or not isinstance(variation_ids, list):
                    continue
                expected_ids: set[int] = set()
                for variation_id in variation_ids:
                    if isinstance(variation_id, bool) or not isinstance(variation_id, int) or variation_id < 1:
                        raise WooCommerceError("invalid_response", "WooCommerce returned an invalid variation identity")
                    expected_ids.add(variation_id)
                if expected_ids:
                    variations_url = f"{self._api_root}/products/{provider_id}/variations?per_page={self._page_size}&page=1"
                    for variation_page in self._pages(variations_url):
                        for variation in variation_page:
                            variation_id = _provider_id(variation)
                            if variation_id in expected_ids:
                                yield WooRecord("variation", variation_id, variation, provider_id)

    def iter_orders(self) -> Iterator[WooRecord]:
        """Yield provider order payloads without status/refund normalization."""
        order_url = f"{self._api_root}/orders?per_page={self._page_size}&page=1"
        for page in self._pages(order_url):
            for order in page:
                yield WooRecord("order", _provider_id(order), order)


def _provider_id(record: Mapping[str, Any]) -> int:
    value = record.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WooCommerceError("invalid_response", "WooCommerce resource identity was invalid")
    return value


def _positive_int(value: str | None) -> int | None:
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed and parsed > 0 else None


def _next_link(value: str) -> str | None:
    # RFC 8288 Link header parsing for the provider's documented rel="next".
    for match in re.finditer(r'<([^>]+)>\s*;\s*rel\s*=\s*(?:"next"|next)(?:\s*[,;]|$)', value, re.IGNORECASE):
        return match.group(1)
    return None


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verify WooCommerce's documented base64 HMAC-SHA256 raw-body signature."""
    if not isinstance(raw_body, bytes) or not signature or not secret:
        return False
    expected = base64.b64encode(hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()).decode("ascii")
    try:
        decoded_expected = base64.b64decode(expected, validate=True)
        decoded_supplied = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError):
        return False
    return hmac.compare_digest(decoded_expected, decoded_supplied)
