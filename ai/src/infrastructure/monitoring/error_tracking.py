"""
Error tracking (Sentry), off unless SENTRY_DSN is set.

Every process calls init_error_tracking() once at start-up: the API
(src/ai/main.py) and each background worker. Unhandled exceptions and
logged errors are then reported with the service name, environment and
release.

What is never sent: request bodies, cookies, the Authorization header or
any other credential-bearing header, query strings, and user details
(send_default_pii stays off). Uploaded business data and sign-in tokens
therefore never leave the server.

Settings: SENTRY_DSN, SENTRY_ENVIRONMENT (default "production"),
SENTRY_RELEASE (default: Render's RENDER_GIT_COMMIT), and
SENTRY_TRACES_SAMPLE_RATE (performance tracing, default 0 = off).
"""

import logging
import os

logger = logging.getLogger("KEEL_ERROR_TRACKING")

# Request headers that are safe and useful for debugging; everything else is dropped.
_SAFE_HEADERS = {"user-agent", "content-type", "accept", "accept-language", "x-app-language", "content-length"}


def scrub_event(event, _hint=None):
    """Strips anything that could carry credentials or customer data."""
    request = event.get("request")
    if isinstance(request, dict):
        for key in ("data", "cookies", "query_string", "env"):
            request.pop(key, None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {k: v for k, v in headers.items() if k.lower() in _SAFE_HEADERS}
        url = request.get("url")
        if isinstance(url, str) and "?" in url:
            request["url"] = url.split("?", 1)[0]
    event.pop("user", None)
    return event


def init_error_tracking(service: str) -> bool:
    """Starts Sentry for this process when SENTRY_DSN is set. Returns whether it did."""
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; error tracking is off.")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("SENTRY_RELEASE") or os.getenv("RENDER_GIT_COMMIT") or None,
        send_default_pii=False,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0")),
        before_send=scrub_event,
        before_send_transaction=scrub_event,
    )
    sentry_sdk.set_tag("service", service)
    logger.info("error tracking on for %s", service)
    return True
