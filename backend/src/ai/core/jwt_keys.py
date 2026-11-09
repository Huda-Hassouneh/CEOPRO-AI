"""
KEEL - session-token signing keys, with an overlap window for rotation.

New tokens are signed only with JWT_SECRET. Verification tries JWT_SECRET,
then JWT_SECRET_PREVIOUS when it is set, so rotating the secret does not sign
anyone out: put the old value in JWT_SECRET_PREVIOUS and the new one in
JWT_SECRET. A renewal (POST /auth/refresh) re-signs with the current key, and
no sign-in outlives SESSION_MAX_HOURS, so JWT_SECRET_PREVIOUS can be removed
once that long has passed (docs/SECURITY_CREDENTIAL_ROTATION.md).

No import-time side effects: core/security.py (which refuses to start without
JWT_SECRET) and core/rate_limit.py (which does not) both use it.
"""

import os
from typing import Optional, Tuple

import jwt

ALGORITHM = "HS256"


def signing_key() -> str:
    return os.getenv("JWT_SECRET") or ""


def verification_keys() -> Tuple[str, ...]:
    """Current key first, then the previous one (if set and different)."""
    current = signing_key()
    # Used exactly as given (like JWT_SECRET): it must equal the old secret byte for byte.
    previous = os.getenv("JWT_SECRET_PREVIOUS") or ""
    keys = [current] if current else []
    if previous.strip() and previous != current:
        keys.append(previous)
    return tuple(keys)


def decode(token: str, keys: Optional[Tuple[str, ...]] = None, **options) -> dict:
    return decode_with_key(token, keys, **options)[0]


def decode_with_key(token: str, keys: Optional[Tuple[str, ...]] = None, **options) -> Tuple[dict, bool]:
    """Verify an HS256 token with each key in turn.

    Only a wrong signature moves on to the next key: a token signed with a
    valid key but expired, missing a required claim, or malformed is refused
    straight away, exactly as with a single key. Returns (claims, current):
    current is False when only a previous key matched.
    """
    keys = verification_keys() if keys is None else keys
    if not keys:
        raise jwt.InvalidSignatureError("No session signing key is configured")
    for index, key in enumerate(keys):
        try:
            return jwt.decode(token, key, algorithms=[ALGORITHM], **options), index == 0
        except jwt.InvalidSignatureError:
            if index == len(keys) - 1:
                raise
    raise jwt.InvalidSignatureError("Signature verification failed")  # unreachable
