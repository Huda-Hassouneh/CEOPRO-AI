"""
Unit tests for src/ai/marketing/url_extractor.py. The HTTP fetch
(httpx.Client.stream) and DNS resolution (socket.getaddrinfo) are mocked -
what's under test is this module's own extruct/lxml parsing, its error
handling, and its SSRF guard (2026-09-25 security audit finding: this
endpoint fetches an arbitrary tenant-supplied URL server-side - a real
SSRF surface if unrestricted), not real network behavior.
"""
import socket
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.ai.marketing.url_extractor import URLExtractionError, extract_product_info_from_url

_JSONLD_PRODUCT_PAGE = b"""
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org/", "@type": "Product", "name": "Widget 3000",
 "description": "A very tidy desk widget.",
 "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "JOD"}}
</script>
</head><body></body></html>
"""

_PLAIN_PAGE = b"<html><head><title>Just a Title</title></head><body>No structured data here.</body></html>"

_EMPTY_PAGE = b"<html><head></head><body></body></html>"

# A real, globally-routable public IP (Cloudflare's public resolver) -
# not private/loopback/link-local/multicast/reserved (note: Python's own
# ipaddress module treats the RFC 5737 TEST-NET documentation ranges as
# is_private=True, so those can't stand in for "public" here) - always
# passes _assert_url_targets_a_public_host's checks regardless of this
# sandbox's own real DNS/network state, since DNS resolution is mocked.
_PUBLIC_IP = "1.1.1.1"
_PRIVATE_IP = "10.0.0.5"
_METADATA_IP = "169.254.169.254"


def _fake_addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def _fake_response(status_code=200, content_type="text/html; charset=utf-8", body=b"", location=None):
    response = MagicMock()
    response.status_code = status_code
    response.is_redirect = 300 <= status_code < 400
    headers = {"content-type": content_type}
    if location:
        headers["location"] = location
    response.headers = headers
    response.iter_bytes.return_value = iter([body])
    response.encoding = "utf-8"
    return response


@contextmanager
def _response_cm(response):
    yield response


def _patched_client(*responses):
    """Patches httpx.Client so `with httpx.Client(...) as client: client.stream(...)`
    returns each of `responses` in sequence, one per call - lets a test
    simulate a redirect chain (one response per hop)."""
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    iterator = iter(responses)
    client.stream.side_effect = lambda *a, **kw: _response_cm(next(iterator))
    return patch("src.ai.marketing.url_extractor.httpx.Client", return_value=client)


def _patched_dns(ip: str = _PUBLIC_IP):
    return patch("src.ai.marketing.url_extractor.socket.getaddrinfo", return_value=_fake_addrinfo(ip))


def test_extracts_json_ld_product_fields():
    with _patched_dns(), _patched_client(_fake_response(body=_JSONLD_PRODUCT_PAGE)):
        info = extract_product_info_from_url("https://example.com/widget")

    assert info.name == "Widget 3000"
    assert info.description == "A very tidy desk widget."
    assert info.price == "19.99 JOD"
    assert "Widget 3000" in info.as_text()
    assert "19.99 JOD" in info.as_text()


def test_falls_back_to_title_when_no_structured_data():
    with _patched_dns(), _patched_client(_fake_response(body=_PLAIN_PAGE)):
        info = extract_product_info_from_url("https://example.com/plain")

    assert info.name == "Just a Title"
    assert info.description is None


def test_raises_when_nothing_usable_is_found():
    with _patched_dns(), _patched_client(_fake_response(body=_EMPTY_PAGE)):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://example.com/empty")


def test_raises_on_non_2xx_status():
    with _patched_dns(), _patched_client(_fake_response(status_code=404)):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://example.com/missing")


def test_raises_on_non_html_content_type():
    with _patched_dns(), _patched_client(_fake_response(content_type="application/pdf", body=b"%PDF-1.4")):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://example.com/file.pdf")


def test_raises_on_oversized_response():
    huge_body = b"a" * (3 * 1024 * 1024)
    with _patched_dns(), _patched_client(_fake_response(body=huge_body)):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://example.com/huge")


def test_raises_on_network_failure():
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.stream.side_effect = httpx.ConnectError("connection refused")
    with _patched_dns(), patch("src.ai.marketing.url_extractor.httpx.Client", return_value=client):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://example.com/down")


def test_follows_a_redirect_to_another_public_host():
    """A redirect chain to another PUBLIC host must still work - the SSRF
    guard rejects private targets, not redirects in general."""
    with _patched_dns(), _patched_client(
        _fake_response(status_code=302, location="https://example.org/real-page"),
        _fake_response(body=_JSONLD_PRODUCT_PAGE),
    ):
        info = extract_product_info_from_url("https://example.com/redirect-me")

    assert info.name == "Widget 3000"


# --- SSRF guard (2026-09-25 security audit finding) ---

def test_rejects_a_url_with_a_non_http_scheme():
    with pytest.raises(URLExtractionError):
        extract_product_info_from_url("file:///etc/passwd")


def test_rejects_a_url_resolving_to_a_private_address():
    with _patched_dns(_PRIVATE_IP):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://internal.example.com/admin")


def test_rejects_a_url_resolving_to_the_cloud_metadata_link_local_address():
    with _patched_dns(_METADATA_IP):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://metadata.example.com/latest/meta-data")


def test_rejects_a_redirect_that_targets_a_private_address():
    """The classic SSRF bypass this guard exists for: a first-hop PUBLIC
    URL that only reveals its real (private) target via a 302 - each hop
    must be re-validated, not just the URL the caller originally passed."""
    dns_sequence = iter([_fake_addrinfo(_PUBLIC_IP), _fake_addrinfo(_PRIVATE_IP)])
    with patch("src.ai.marketing.url_extractor.socket.getaddrinfo", side_effect=lambda *a, **kw: next(dns_sequence)), \
         _patched_client(_fake_response(status_code=302, location="https://internal.example.com/secret")):
        with pytest.raises(URLExtractionError):
            extract_product_info_from_url("https://example.com/redirect-to-internal")
