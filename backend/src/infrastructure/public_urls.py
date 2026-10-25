"""Trusted frontend origin shared by payment returns, OAuth and email links."""
import os
import ipaddress
from urllib.parse import urlsplit


def frontend_origin() -> str:
    configured = (os.getenv("PUBLIC_FRONTEND_ORIGIN") or "").strip()
    if not configured:
        values = {(os.getenv(key) or "").strip().rstrip("/")
                  for key in ("FRONTEND_BASE_URL", "APP_BASE_URL", "FRONTEND_URL")}
        values.discard("")
        if len(values) > 1:
            raise ValueError("Frontend origin settings disagree; configure PUBLIC_FRONTEND_ORIGIN.")
        configured = next(iter(values), "")
    if not configured:
        raise ValueError("The public frontend origin is not configured.")
    try:
        value = urlsplit(configured)
        port = value.port
        loopback = value.hostname == "localhost"
        if value.hostname and not loopback:
            try:
                loopback = ipaddress.ip_address(value.hostname).is_loopback
            except ValueError:
                pass
        if (not value.hostname or value.username or value.password or value.query or value.fragment
                or value.path not in ("", "/") or value.scheme not in ("http", "https")
                or (value.scheme == "http" and not loopback) or port == 0):
            raise ValueError()
    except ValueError:
        raise ValueError("The public frontend origin must be HTTPS, or HTTP on loopback, with no path or credentials.") from None
    return configured.rstrip("/")
