"""Runtime SSRF controls for source URLs, DNS answers, and redirects."""

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeTargetError(ValueError):
    pass


def resolve_public_addresses(url: str, resolver=socket.getaddrinfo) -> set[str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise UnsafeTargetError("target must be a credential-free HTTP(S) URL")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise UnsafeTargetError("local targets are prohibited")
    try:
        answers = resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeTargetError(f"target DNS resolution failed: {hostname}") from exc
    addresses = {answer[4][0].split("%", 1)[0] for answer in answers}
    if not addresses:
        raise UnsafeTargetError("target DNS returned no addresses")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise UnsafeTargetError(f"target resolves to prohibited address: {address}")
    return addresses


def validate_same_origin(url: str, approved_host: str) -> None:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if host != approved_host.lower().rstrip("."):
        raise UnsafeTargetError("redirect or request left the approved source host")


def assert_connector_target(url: str, resolver=socket.getaddrinfo) -> None:
    """A company's own API or database must be reachable on the public
    internet: internal and cloud-metadata addresses are refused so a
    connection can't be used to reach this platform's own network.
    Self-hosted installs that connect to systems on their private network
    set CONNECTORS_ALLOW_PRIVATE_HOSTS=true."""
    import os

    if os.getenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", "").lower() in ("1", "true", "yes"):
        return
    resolve_public_addresses(url, resolver=resolver)
