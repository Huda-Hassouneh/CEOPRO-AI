"""Outbound discovery fetches reuse one verified TLS context instead of rebuilding it per client."""
import ssl

import httpx

from src.market_scraper import network_security


def test_one_context_is_shared_and_still_verifies_certificates_and_hostnames(monkeypatch):
    monkeypatch.setattr(network_security, "_SSL_CONTEXT", None)
    first, second = network_security.shared_ssl_context(), network_security.shared_ssl_context()
    assert first is second
    assert first.verify_mode == ssl.CERT_REQUIRED and first.check_hostname is True


def test_site_readers_pass_the_shared_context_to_their_clients(monkeypatch):
    from src.market_scraper.market_discovery import enrich, intel

    seen = []
    real = httpx.Client

    def spy(*args, **kwargs):
        seen.append(kwargs.get("verify"))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", spy)
    site = intel._Site("https://example.test/")  # noqa: SLF001
    site.client.close()
    monkeypatch.setattr(enrich, "_allowed", lambda client, url: False)
    assert enrich.fetch_site("https://example.test/") == {"blocked": "robots"}
    assert seen and all(v is network_security.shared_ssl_context() for v in seen)
