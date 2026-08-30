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
