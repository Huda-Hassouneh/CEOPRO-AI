"""Runtime SSRF controls for source URLs, DNS answers, and redirects."""

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeTargetError(ValueError):
    pass


_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SIX_TO_FOUR = ipaddress.ip_network("2002::/16")
_TEREDO = ipaddress.ip_network("2001::/32")


def is_public_address(value) -> bool:
    """True only for an address on the public internet. Python's is_global alone is not enough: an
    IPv6 address can carry an IPv4 one (IPv4-mapped, NAT64 64:ff9b::/96, 6to4) that a gateway turns
    back into 127.0.0.1 or 10.x, so the embedded address is judged too. Teredo is refused outright."""
    address = ipaddress.ip_address(str(value).split("%", 1)[0])
    if address.version == 6:
        if address.ipv4_mapped is not None:
            return is_public_address(address.ipv4_mapped)
        if address in _NAT64:
            return is_public_address(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
        if address in _SIX_TO_FOUR:
            return is_public_address(ipaddress.IPv4Address((int(address) >> 80) & 0xFFFFFFFF))
        if address in _TEREDO:
            return False
    return address.is_global


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
        if not is_public_address(value):
            raise UnsafeTargetError(f"target resolves to prohibited address: {value}")
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


def pinned_address(url: str, resolver=socket.getaddrinfo) -> str:
    """The public IP to connect to for `url`, chosen once. Connecting to this address (not to the
    name again) closes the window where a DNS answer changes between the check and the connection
    (DNS rebinding). Self-hosted installs that allow private hosts get the name back unchanged."""
    import os

    if os.getenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", "").lower() in ("1", "true", "yes"):
        return urlsplit(url).hostname
    return sorted(resolve_public_addresses(url, resolver=resolver))[0]


# Headers a connector must not set: they would change where the request goes or how it is framed.
_FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer",
                      "expect", "forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip"}
_HEADER_NAME = __import__("re").compile(r"^[A-Za-z0-9-]{1,64}$")


def validate_header_name(name: str) -> str:
    if not _HEADER_NAME.match(name or "") or name.lower() in _FORBIDDEN_HEADERS or name.lower().startswith("proxy-"):
        raise UnsafeTargetError(f"header not allowed: {name!r}")
    return name


MAX_RESPONSE_BYTES = 20 * 1024 * 1024


def pin_request(url: str, resolver=socket.getaddrinfo) -> "tuple[str, dict, dict]":
    """(target_url, extra_headers, extensions) for an httpx request to `url` that connects to the
    one public address checked for it, while the certificate check, SNI and Host header still use
    the real name. Raises UnsafeTargetError for anything that is not a public address."""
    parsed = urlsplit(url)
    ip = pinned_address(url, resolver=resolver)
    if ip == parsed.hostname:  # private hosts allowed (self-hosted): nothing to pin
        return url, {}, {}
    host_ip = f"[{ip}]" if ":" in ip else ip
    port = f":{parsed.port}" if parsed.port else ""
    target = parsed._replace(netloc=f"{host_ip}{port}").geturl()
    extensions = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
    return target, {"Host": parsed.netloc.rsplit("@", 1)[-1]}, extensions


def fetch_public_json(url: str, params: dict, headers: dict, timeout: float, max_bytes: int = MAX_RESPONSE_BYTES):
    """GET `url` and parse the JSON body, connecting only to the one public address checked for it
    (certificate and Host still use the real name), never following a redirect, and reading at most
    `max_bytes` so a hostile endpoint can't exhaust memory."""
    import json

    import httpx

    target, extra_headers, extensions = pin_request(url)
    send_headers = {**headers, **extra_headers}
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", target, params=params, headers=send_headers, extensions=extensions) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise UnsafeTargetError("the response is larger than the allowed size")
    return json.loads(bytes(body))
