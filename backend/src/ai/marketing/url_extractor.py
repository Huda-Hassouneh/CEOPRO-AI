"""
KEEL - Marketing Campaign URL Product-Info Extraction (Phase 1 of the
Automated Marketing System's "Product URL" input mode).

No arbitrary-single-URL product scraper exists anywhere in this repo
today - src/market_scraper is a Scrapy-based crawler built around spiders/
targets/callbacks, not something a synchronous FastAPI request handler can
invoke inline for one ad-hoc URL. Rather than pulling Scrapy into a
request-response cycle, this reuses the two libraries market_scraper's own
JS-widget fallback (spiders/market_source.py) already depends on for
exactly this kind of "pull structured product data out of an HTML page"
job: extruct (schema.org JSON-LD/microdata/OpenGraph parsing) and lxml
(the plain-text/title fallback when a page carries no structured markup
at all) - both already pinned in src/market_scraper/requirements.txt, now
also declared in src/ai/requirements.txt for this service's own use.

httpx is already a hard dependency of this service (src/ai/rag/
llm_client.py) - reused here for the actual HTTP fetch, no new HTTP
library.

This never renders JavaScript (no Playwright here, unlike market_source.py's
own render_javascript path) and never claims to fully "understand" the
page - it pulls out real title/description/price/image_url text when the
page actually exposes it via standard markup, and returns None for
whatever it can't find. The caller (content_generator.py) is expected to
be honest about what starting information a URL-sourced campaign actually
had.
"""
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

import extruct
import httpx
from lxml import html as lxml_html

from src.market_scraper.network_security import is_public_address, pin_request

_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2MB - a product page's HTML, not its assets
_USER_AGENT = "KEEL-Marketing/1.0 (+product-understanding fetch)"

# This endpoint takes an arbitrary, tenant-supplied URL and fetches it
# server-side - a textbook SSRF surface (2026-09-25 security audit finding)
# if left unrestricted: a malicious `url` could target internal
# infrastructure (a private-network service, the cloud metadata endpoint
# at 169.254.169.254, localhost) and this endpoint's differentiated error
# responses (HTTP status vs. fetch failure vs. "no product found") would
# work as a usable oracle for probing it. Only public http(s) hosts are
# allowed; every redirect hop is re-validated the same way (a first-hop
# public URL could still 302 to an internal one).
_MAX_REDIRECTS = 5


class URLExtractionError(Exception):
    """Raised when the URL can't be fetched or contains no usable HTML -
    the caller maps this to a clear 422, never silently falls back to a
    fabricated product description."""


def _assert_url_targets_a_public_host(url: str) -> None:
    """Raises URLExtractionError if `url` isn't a plain http(s) URL
    resolving only to public, routable addresses - never a private/
    loopback/link-local/multicast/reserved/unspecified one. Resolves the
    hostname itself (not just string-matching it) so a DNS name that
    merely points at an internal IP is caught too, not just a literal
    "localhost"/"127.0.0.1" in the URL text."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLExtractionError(f"Unsupported URL scheme '{parsed.scheme}' - only http/https URLs are allowed.")
    hostname = parsed.hostname
    if not hostname:
        raise URLExtractionError("URL has no host to fetch.")

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as err:
        raise URLExtractionError(f"Could not resolve host '{hostname}': {err}") from err

    for family, _type, _proto, _canonname, sockaddr in resolved:
        # is_public_address also judges IPv6 forms that carry an IPv4 address (NAT64, 6to4,
        # IPv4-mapped) and shared/CGNAT ranges, which the old private/loopback checks let through.
        if not is_public_address(sockaddr[0]):
            raise URLExtractionError(f"URL host '{hostname}' resolves to a non-public address and cannot be fetched.")


@dataclass
class ExtractedProductInfo:
    source_url: str
    name: Optional[str]
    description: Optional[str]
    price: Optional[str]
    image_url: Optional[str]

    def as_text(self) -> str:
        """Flattens whatever fields were actually found into the plain
        text block content_generator.py's prompt expects - the same shape
        a raw user-supplied text description already takes, so the LLM
        prompt-building code doesn't need a separate code path per input
        source."""
        parts = []
        if self.name:
            parts.append(f"Product name: {self.name}")
        if self.description:
            parts.append(f"Description: {self.description}")
        if self.price:
            parts.append(f"Listed price: {self.price}")
        return "\n".join(parts)


def _first_product_from_jsonld(items: list) -> Optional[dict]:
    for item in items:
        types = item.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        if any(t == "Product" for t in types):
            return item
    return None


def _first_product_from_microdata(items: list) -> Optional[dict]:
    for item in items:
        if item.get("type", "").rsplit("/", 1)[-1] == "Product":
            return item.get("properties", {})
    return None


def _offer_price(offers) -> Optional[str]:
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice")
        currency = offers.get("priceCurrency")
        if price:
            return f"{price} {currency}".strip() if currency else str(price)
    return None


def _extract_structured(html_text: str, base_url: str) -> Optional[ExtractedProductInfo]:
    try:
        data = extruct.extract(html_text, base_url=base_url, syntaxes=["json-ld", "microdata", "opengraph"], errors="log")
    except Exception:
        return None

    product = _first_product_from_jsonld(data.get("json-ld", []))
    if product:
        return ExtractedProductInfo(
            source_url=base_url,
            name=product.get("name"),
            description=product.get("description"),
            price=_offer_price(product.get("offers")),
            image_url=product.get("image") if isinstance(product.get("image"), str) else None,
        )

    microdata_product = _first_product_from_microdata(data.get("microdata", []))
    if microdata_product:
        return ExtractedProductInfo(
            source_url=base_url,
            name=microdata_product.get("name"),
            description=microdata_product.get("description"),
            price=None,
            image_url=microdata_product.get("image"),
        )

    og = {item.get("property"): item.get("content") for item in data.get("opengraph", []) if item.get("property")}
    if og.get("og:title") or og.get("og:description"):
        return ExtractedProductInfo(
            source_url=base_url,
            name=og.get("og:title"),
            description=og.get("og:description"),
            price=None,
            image_url=og.get("og:image"),
        )

    return None


def _extract_title_fallback(html_text: str, base_url: str) -> ExtractedProductInfo:
    """Used only when the page carries no schema.org/OpenGraph markup at
    all - the plain <title> text is the one thing almost every HTML page
    reliably has, so this is the honest floor rather than returning
    nothing."""
    try:
        tree = lxml_html.fromstring(html_text)
        title = tree.findtext(".//title")
    except Exception:
        title = None
    return ExtractedProductInfo(
        source_url=base_url, name=(title or "").strip() or None, description=None, price=None, image_url=None,
    )


def extract_product_info_from_url(url: str, timeout: float = _REQUEST_TIMEOUT_SECONDS) -> ExtractedProductInfo:
    """
    Fetches `url` and returns whatever product fields it could find
    (structured schema.org/OpenGraph markup first, plain <title> as the
    last resort). Raises URLExtractionError on any network failure,
    non-2xx response, non-HTML content, oversized response, or a URL/
    redirect that doesn't resolve to a public host (SSRF guard - see
    _assert_url_targets_a_public_host's own docstring) - never returns a
    silently empty/fabricated result.

    Redirects are followed manually (follow_redirects=False below), one
    hop at a time, re-validating the target host before each request -
    not httpx's own follow_redirects=True, which would only validate the
    URL this function was originally called with, letting a first-hop
    public URL 302 straight to an internal address unchecked.
    """
    current_url = url
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, verify=True) as client:
            for _hop in range(_MAX_REDIRECTS + 1):
                _assert_url_targets_a_public_host(current_url)
                # Connects to the address that was just checked, so a DNS answer can't change in between.
                target, pin_headers, pin_extensions = pin_request(current_url)
                with client.stream("GET", target, headers={"User-Agent": _USER_AGENT, **pin_headers},
                                   extensions=pin_extensions) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise URLExtractionError("URL redirected without a Location header.")
                        current_url = urljoin(current_url, location)
                        continue

                    if response.status_code >= 400:
                        raise URLExtractionError(f"URL returned HTTP {response.status_code}.")
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type.lower():
                        raise URLExtractionError(f"URL did not return HTML content (got '{content_type}').")

                    chunks = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > _MAX_RESPONSE_BYTES:
                            raise URLExtractionError("Page is too large to fetch for product understanding.")
                        chunks.append(chunk)
                    html_bytes = b"".join(chunks)
                    break
            else:
                raise URLExtractionError("Too many redirects.")
    except httpx.HTTPError as err:
        raise URLExtractionError(f"Could not fetch URL: {err}") from err
    url = current_url

    html_text = html_bytes.decode(response.encoding or "utf-8", errors="replace")

    info = _extract_structured(html_text, url)
    if info is None or not (info.name or info.description):
        info = _extract_title_fallback(html_text, url)

    if not (info.name or info.description):
        raise URLExtractionError("No product name or description could be found on this page.")

    return info
