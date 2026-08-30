import socket

import pytest

from src.market_scraper.network_security import (
    UnsafeTargetError,
    resolve_public_addresses,
    validate_same_origin,
)


def resolver_for(*addresses):
    def resolve(host, port, type):
        assert type == socket.SOCK_STREAM
        return [(socket.AF_INET6 if ":" in address else socket.AF_INET, type, 6, "", (address, port)) for address in addresses]
    return resolve


def test_public_dns_answers_are_accepted():
    assert resolve_public_addresses(
        "https://shop.example/product", resolver_for("93.184.216.34")
    ) == {"93.184.216.34"}


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "fe80::1"])
def test_private_link_local_and_loopback_dns_answers_are_rejected(address):
    with pytest.raises(UnsafeTargetError, match="prohibited"):
        resolve_public_addresses("https://shop.example", resolver_for(address))


def test_cross_origin_redirect_is_rejected():
    with pytest.raises(UnsafeTargetError, match="approved"):
        validate_same_origin("https://other.example/product", "shop.example")
    validate_same_origin("https://shop.example/next", "shop.example")
