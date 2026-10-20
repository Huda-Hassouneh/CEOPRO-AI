"""
KEEL - Shared auth utilities for the FastAPI service.

Moved out of main.py during the production-hardening pass that split that
file into routers/ - TenantContext/get_tenant_context is unchanged in
behavior (still decodes the same Bearer JWT, same tenant_id/user_id claim
shape every router already depends on), just relocated so every router
module can import it without importing main.py itself (which would create
a circular import once main.py includes those same routers).

create_access_token()/hash_password()/verify_password() are new - the real
gap main.py's own original docstring flagged explicitly: "no JWT-issuing
service or claim-shape contract exists anywhere else in this repo today."
This is that service. The token this issues decodes with the exact same
get_tenant_context() below (same JWT_SECRET, same HS256, same tenant_id/
user_id claim names) - nothing about how a caller uses the resulting token
changes.
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Header, HTTPException, Request

# Same JWT_SECRET every existing endpoint's get_tenant_context() already
# requires - reused here, not a second secret to manage/rotate separately.
# Read at import time (matches every other required-env-var convention in
# this service, e.g. db.py's _admin_database_url()) - a deployment missing
# it fails at startup, not on the first real login attempt.
_JWT_SECRET = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is not set.")

# How long one access token lasts. The app renews it while someone is using
# it (POST /auth/refresh), so this is effectively the idle timeout: a tab left
# unused this long signs out. Kept short so a leaked token is useful only
# briefly.
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "120"))
# The longest one sign-in can be kept alive by renewals before the user has
# to enter their password again.
SESSION_MAX_HOURS = int(os.getenv("SESSION_MAX_HOURS", "168"))

# Whether a confirmed email address is needed to use the app: "auto" (the
# default) requires it once email delivery is configured (SMTP_HOST), so
# nobody is locked out of an environment that can't send the code; "true"
# and "false" force it either way.
EMAIL_VERIFICATION_REASON = "email-verification-required"


def email_verification_required() -> bool:
    setting = os.getenv("REQUIRE_EMAIL_VERIFICATION", "auto").strip().lower()
    if setting in ("true", "1", "yes"):
        return True
    if setting in ("false", "0", "no"):
        return False
    from src.ai.core import notifications

    return notifications.is_configured()


class TenantContext:
    def __init__(self, tenant_id: str, user_id: str):
        self.tenant_id = tenant_id
        self.user_id = user_id


def get_tenant_context(request: Request = None, authorization: Optional[str] = Header(default=None)) -> TenantContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")

    token = authorization[len("Bearer "):]
    try:
        # exp is mandatory: a signed token with no expiry would never stop working.
        claims = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    tenant_id = claims.get("tenant_id")
    user_id = claims.get("user_id")
    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Token is missing tenant_id/user_id claims.")
    token_id = claims.get("jti") or ("legacy:" + hashlib.sha256(token.encode()).hexdigest())
    if is_token_revoked(token_id):
        raise HTTPException(status_code=401, detail="This session has been signed out.")

    # Until the address is confirmed, only the sign-in endpoints (verify,
    # renew, sign out, switch company) work. Older tokens carry no "ev"
    # claim and count as unconfirmed; renewing one reads the real state.
    if (claims.get("ev") is not True and request is not None and not request.url.path.startswith("/auth/")
            and email_verification_required()):
        raise HTTPException(status_code=403, detail="Please confirm your email address to continue.",
                            headers={"X-Auth-Reason": EMAIL_VERIFICATION_REASON})

    credential_version = claims.get("cv", 0)
    if isinstance(credential_version, bool) or not isinstance(credential_version, int) or credential_version < 0:
        raise HTTPException(status_code=401, detail="Invalid session version.")
    assert_active_principal(tenant_id, user_id, credential_version)
    ctx = TenantContext(tenant_id=tenant_id, user_id=user_id)
    if request is not None:
        # Lets main.py's write middleware drop this company's cached views.
        request.state.tenant_id = tenant_id
    ctx.token_id = token_id
    ctx.token_expires_at = claims.get("exp")
    # When this sign-in started; renewals keep it. Older tokens didn't carry
    # it, so count from when they were issued.
    ctx.auth_time = claims.get("auth_time") or (claims.get("exp", 0) - JWT_EXPIRE_MINUTES * 60)
    return ctx


def assert_active_principal(tenant_id: str, user_id: str, credential_version: int = 0) -> None:
    """Revalidate human membership and platform suspension for every protected request."""
    from src.ai import db
    conn = None
    try:
        conn = db.auth_lookup_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT keel_active_principal(%s, %s), auth_credential_version(%s);", (user_id, tenant_id, user_id))
            row = cursor.fetchone()
        if not row or row[0] is not True:
            raise HTTPException(status_code=403, detail="This account or workspace is no longer active.")
        if row[1] != credential_version:
            raise HTTPException(status_code=401, detail="Your password changed. Please sign in again.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Account verification is temporarily unavailable.") from None
    finally:
        if conn is not None:
            conn.close()


# --- Sign-out ---------------------------------------------------------------
# Tokens are stateless, so signing out records the token's id (jti) as
# revoked until the token would have expired anyway. Redis holds the list;
# protected operations fail closed when Redis cannot confirm revocation.

_REVOKED_PREFIX = "apex:revoked-token:"
_security_logger = logging.getLogger("CEOPRO_AI_SECURITY")


def _revocation_store():
    from src.ai.core.redis_client import get_redis_client

    return get_redis_client(socket_connect_timeout=0.5, socket_timeout=0.5)


def _durable_revocation(token_id: str, expires_at=None) -> bool:
    """Existing Python identity owns the receipt; Redis is never an allow authority."""
    from src.ai import db
    conn = db.auth_lookup_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT keel_token_revocation(%s,%s,%s);", (
                "record" if expires_at is not None else "check",
                hashlib.sha256(token_id.encode()).hexdigest(), expires_at))
            row = cursor.fetchone()
        conn.commit()
        if not row or not isinstance(row[0], bool):
            raise RuntimeError("Revocation receipt was not verified")
        return row[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def revoke_token(token_id: str, expires_at_epoch) -> bool:
    if not token_id:
        return False
    ttl = int(expires_at_epoch - datetime.now(timezone.utc).timestamp()) if expires_at_epoch else JWT_EXPIRE_MINUTES * 60
    try:
        _durable_revocation(token_id, datetime.now(timezone.utc) + timedelta(seconds=max(ttl, 1)))
        if _revocation_store().set(_REVOKED_PREFIX + token_id, "1", ex=max(ttl, 1)) is not True:
            raise RuntimeError("Revocation write was not acknowledged")
        return True
    except Exception as err:  # noqa: BLE001 - see the comment above
        _security_logger.warning("Token revocation write unavailable")
        raise HTTPException(status_code=503, detail="Sign-out could not be confirmed. Please try again.",
                            headers={"Retry-After": "5", "X-Auth-Reason": "revocation-unavailable"}) from None


def is_token_revoked(token_id: str) -> bool:
    try:
        result = _revocation_store().exists(_REVOKED_PREFIX + token_id)
        if not isinstance(result, (int, bool)) or result not in (0, 1):
            raise RuntimeError("Revocation read was not verified")
        return bool(result) or _durable_revocation(token_id)
    except Exception:  # noqa: BLE001 - an unknown revocation decision is not permission
        _security_logger.warning("Token revocation service unavailable")
        raise HTTPException(status_code=503, detail="Session verification is temporarily unavailable. Please try again.",
                            headers={"Retry-After": "5", "X-Auth-Reason": "revocation-unavailable"}) from None


def create_access_token(tenant_id: str, user_id: str, auth_time: "Optional[int]" = None,
                        email_verified: bool = False, credential_version: int = 0) -> "tuple[str, int]":
    """
    Returns (token, expires_in_seconds). Claims: tenant_id/user_id (what
    get_tenant_context() reads), exp (PyJWT rejects the token after it),
    jti (lets sign-out revoke it) and auth_time - when this sign-in started,
    carried over by renewals so a session can't be kept alive forever
    (SESSION_MAX_HOURS). ev says whether the email address is confirmed, and
    evr whether confirmation was required when the token was issued (the
    app sends unconfirmed people to the verification screen from it).
    """
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=JWT_EXPIRE_MINUTES)
    token = jwt.encode(
        {"tenant_id": str(tenant_id), "user_id": str(user_id), "exp": now + expires_delta,
         "iat": now, "auth_time": int(auth_time if auth_time is not None else now.timestamp()),
         "jti": secrets.token_hex(16), "cv": int(credential_version), "ev": bool(email_verified), "evr": email_verification_required()},
        _JWT_SECRET, algorithm="HS256",
    )
    return token, int(expires_delta.total_seconds())


def session_age_seconds(ctx: "TenantContext") -> float:
    return datetime.now(timezone.utc).timestamp() - float(getattr(ctx, "auth_time", 0) or 0)


PASSWORD_MIN_LENGTH = 8
# bcrypt only uses the first 72 bytes of its input; anything longer would be
# silently truncated, so cap it rather than accept a password whose tail
# doesn't actually count.
PASSWORD_MAX_BYTES = 72


def ensure_password_policy(plain_password: str) -> None:
    """Server-side enforcement of the same rules the frontend shows
    (frontend/src/features/auth/validation/authValidation.js:
    AUTH_PASSWORD_REQUIREMENTS) - min 8 chars, upper, lower, digit, special.
    Previously only the browser checked these, so a direct API call could
    set a one-character password (found in live acceptance testing).
    Raises a 422 with one readable message."""
    password = plain_password or ""
    problems = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"at least {PASSWORD_MIN_LENGTH} characters")
    if not any(c.isupper() for c in password):
        problems.append("an uppercase letter")
    if not any(c.islower() for c in password):
        problems.append("a lowercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("a number")
    if not any(not c.isalnum() for c in password):
        problems.append("a special character")
    if problems:
        raise HTTPException(status_code=422, detail="Password must contain " + ", ".join(problems) + ".")
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise HTTPException(status_code=422, detail=f"Password must be at most {PASSWORD_MAX_BYTES} bytes long.")


def hash_password(plain_password: str) -> str:
    """bcrypt - a real, slow-by-design KDF, not a fast general-purpose hash
    (sha256 etc. are deliberately wrong for passwords - too fast to resist
    offline brute-forcing). Output is a self-contained string (algorithm +
    cost + salt + hash) - matches users.password_hash's TEXT column, no
    separate salt column needed."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # A malformed/legacy hash (e.g. seed_demo_data.py's literal
        # 'seed_data_placeholder_hash', which isn't a real bcrypt hash at
        # all) must fail closed as "wrong password", never raise past
        # login and surface a 500 for what is, from the caller's
        # perspective, just a login that didn't succeed.
        return False


# How long a password-reset/email-verification code or a team-invitation
# link stays valid, in minutes - short for the two codes a user is expected
# to act on within the same browser session (a leaked, long-lived reset
# code is a real account-takeover risk); long for an invitation, which
# realistically sits in someone's inbox for days before they get to it.
PASSWORD_RESET_CODE_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_CODE_EXPIRE_MINUTES", "30"))
EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES = int(os.getenv("EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES", "60"))
TEAM_INVITATION_EXPIRE_MINUTES = int(os.getenv("TEAM_INVITATION_EXPIRE_MINUTES", str(14 * 24 * 60)))  # 14 days


def generate_numeric_code(length: int = 6) -> str:
    """A short, human-typeable code for the two flows a real person reads
    out of their own inbox and types back in (password reset, email
    verification) - secrets.randbelow (not `random`) for a real
    cryptographically secure code, zero-padded so it's always exactly
    `length` digits (a leading-zero code must not silently become shorter)."""
    return str(secrets.randbelow(10 ** length)).zfill(length)


def generate_url_safe_token(nbytes: int = 32) -> str:
    """A long, unguessable token for the one flow that's a clicked link, not
    a typed code (team invitations) - too long to type, exactly the point:
    a link only has to survive being clicked, never read aloud or copied by
    hand."""
    return secrets.token_urlsafe(nbytes)


def hash_token(raw_token: str) -> str:
    """SHA-256 is the right tool here, deliberately not bcrypt: bcrypt's
    slowness defends against guessing a short, low-entropy secret (a
    password) by brute force - these tokens are already long, high-entropy,
    cryptographically random strings (generate_numeric_code()'s 10^6 space
    combined with a short expiry + this being an equality lookup, or
    generate_url_safe_token()'s 256 bits), so there is nothing to
    brute-force offline even from a leaked hash. What this needs is just:
    never store the raw, checkable-against-the-database value verbatim -
    a fast, deterministic hash for an exact-match lookup is the correct,
    simpler tool, matching auth_tokens.token_hash's plain CHAR(64) column
    (a bcrypt hash's own salt would make it non-deterministic, and
    therefore useless for a WHERE token_hash = %s lookup)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
