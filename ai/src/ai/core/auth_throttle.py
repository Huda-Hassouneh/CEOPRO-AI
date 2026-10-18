"""
KEEL - brute-force protection for the unauthenticated auth endpoints.

Counts failed attempts per (scope, email) in Redis over a fixed window:
- "login": wrong passwords - LOGIN_MAX_FAILURES per window, then 429 until
  the window expires (a correct password resets the count).
- "code":  wrong password-reset / email-verification codes - a 6-digit code
  has only 1,000,000 values, so CODE_MAX_FAILURES per window, after which
  the caller is told to request a new code (and the auth router cancels the
  account's outstanding codes, so guessing can't simply resume later).
- "send":  requests for a new code - CODE_SENDS_PER_WINDOW per window. A new
  code clears the "code" counter (so a person who mistyped can carry on), so
  at most CODE_SENDS_PER_WINDOW x CODE_MAX_FAILURES guesses fit in a window.

Keyed by the submitted email (lower-cased), whether or not that account
exists, so the 429 itself never reveals which emails are registered.

Fails open: if Redis is unreachable, sign-in keeps working (logged as a
warning) - an outage of a protection layer must not lock every customer out.
"""
import logging
import os

from fastapi import HTTPException

from src.ai.core.redis_client import get_redis_client

logger = logging.getLogger("CEOPRO_AI_AUTH_THROTTLE")

WINDOW_SECONDS = int(os.getenv("AUTH_THROTTLE_WINDOW_SECONDS", "900"))
LOGIN_MAX_FAILURES = int(os.getenv("AUTH_LOGIN_MAX_FAILURES", "10"))
CODE_MAX_FAILURES = int(os.getenv("AUTH_CODE_MAX_FAILURES", "5"))
# Requests for a new code (each one also clears the "code" counter, so it
# needs its own cap or wrong-code limits could be reset at will).
CODE_SENDS_PER_WINDOW = int(os.getenv("AUTH_CODE_SENDS_PER_WINDOW", "5"))
_LIMITS = {"login": LOGIN_MAX_FAILURES, "code": CODE_MAX_FAILURES, "send": CODE_SENDS_PER_WINDOW}

_client = None


def _redis():
    global _client
    if _client is None:
        _client = get_redis_client(socket_connect_timeout=1, socket_timeout=1)
    return _client


def _key(scope: str, email: str) -> str:
    return f"auth_fail:{scope}:{(email or '').strip().lower()}"


def _too_many(scope: str, retry_after: int) -> HTTPException:
    minutes = max(1, -(-retry_after // 60))
    detail = {
        "code": "Too many incorrect codes. Request a new code to try again.",
        "send": f"Too many codes requested. Please try again in about {minutes} minutes.",
    }.get(scope, f"Too many sign-in attempts. Please try again in about {minutes} minutes.")
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(retry_after)})


def ensure_allowed(scope: str, email: str) -> None:
    """Raises 429 when this email already used up its failures in the window."""
    try:
        client = _redis()
        failures = int(client.get(_key(scope, email)) or 0)
        if failures >= _LIMITS[scope]:
            ttl = client.ttl(_key(scope, email))
            raise _too_many(scope, ttl if ttl and ttl > 0 else WINDOW_SECONDS)
    except HTTPException:
        raise
    except Exception as exc:  # Redis down: fail open
        logger.warning("auth throttle unavailable (%s); allowing the attempt", exc)


def record_failure(scope: str, email: str) -> bool:
    """Counts one failure; returns True when this failure reached the limit."""
    try:
        client = _redis()
        key = _key(scope, email)
        failures = client.incr(key)
        if failures == 1:
            client.expire(key, WINDOW_SECONDS)
        return failures >= _LIMITS[scope]
    except Exception as exc:
        logger.warning("auth throttle unavailable (%s); failure not counted", exc)
        return False


def reset(scope: str, email: str) -> None:
    try:
        _redis().delete(_key(scope, email))
    except Exception as exc:
        logger.warning("auth throttle unavailable (%s); counter not reset", exc)
