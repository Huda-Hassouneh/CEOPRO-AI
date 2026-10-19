"""A company's connection to its own API or database must point at a
public address - never this platform's own network or a cloud metadata
endpoint - unless a self-hosted install explicitly allows private hosts."""
import socket

import pytest

from src.market_scraper.network_security import UnsafeTargetError, assert_connector_target


def _resolver(address):
    return lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254", "172.17.0.1"])
def test_private_and_metadata_addresses_are_refused(monkeypatch, address):
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", raising=False)
    with pytest.raises(UnsafeTargetError):
        assert_connector_target("https://pos.vendor.test/api", resolver=_resolver(address))


def test_localhost_names_are_refused_without_dns(monkeypatch):
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", raising=False)
    for url in ("http://localhost:5432", "https://db.local", "https://x@pos.vendor.test"):
        with pytest.raises(UnsafeTargetError):
            assert_connector_target(url, resolver=_resolver("8.8.8.8"))


def test_public_address_is_accepted(monkeypatch):
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", raising=False)
    assert_connector_target("https://pos.vendor.test/api", resolver=_resolver("8.8.8.8"))


def test_self_hosted_installs_can_allow_private_hosts(monkeypatch):
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", "true")
    assert_connector_target("http://10.0.0.5:5432", resolver=_resolver("10.0.0.5"))
