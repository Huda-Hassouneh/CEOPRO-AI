"""
KEEL - Auth: login, signup, password reset, email verification, team
invitations, logout.

Only POST /auth/login existed before this - the real gap main.py's own
original docstring flagged: "no JWT-issuing service or claim-shape
contract exists anywhere else in this repo today." The frontend already
ships full UI for every endpoint below (SignupPage, ForgotPasswordPage,
VerificationCodePage, ResetPasswordPage, VerifyEmailPage, InvitationPage -
frontend/src/features/auth/) and even a real HTTP adapter contract for
them (authHttpAdapter.js/authContracts.js) - none of it had a real backend
behind it, only a mock adapter (authApiMode defaults to 'mock').

Deliberately NOT built here: POST /auth/google. Real Google OAuth needs a
registered OAuth client (client ID/secret, consent screen, redirect URI) -
an external product/infra decision this track doesn't make unilaterally,
the same reason this repo's other optional third-party integrations
(GOOGLE_CUSTOM_SEARCH_API_KEY, a paid LLM vendor) are config-gated rather
than guessed at.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.ai import db
from src.ai.core import auth_throttle, notifications, usage
from src.ai.core.calendar import default_timezone_for_country
from src.ai.core import security
from src.ai.core.security import (
    EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES,
    PASSWORD_RESET_CODE_EXPIRE_MINUTES,
    TEAM_INVITATION_EXPIRE_MINUTES,
    TenantContext,
    create_access_token,
    ensure_password_policy,
    generate_numeric_code,
    generate_url_safe_token,
    get_tenant_context,
    hash_password,
    hash_token,
    verify_password,
)

logger = logging.getLogger("APEX_AUTH")
router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_CREDENTIALS_DETAIL = "Invalid email or password."
# Same message for "no such email" and "already verified"/"nothing to
# reset" - standard account-enumeration defense, the exact convention
# login already established below for "no such email" vs "wrong password".
_GENERIC_CODE_SENT_DETAIL = "If that email is registered, a code has been sent."


def _fetch_user_by_email(conn, email: str):
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM auth_lookup_user_by_email(%s);", (email,))
        return cursor.fetchone()


def _email_verified(conn, user_id) -> bool:
    with conn.cursor() as cursor:
        cursor.execute("SELECT auth_email_verified(%s);", (str(user_id),))
        return bool(cursor.fetchone()[0])


def _credential_version(conn, user_id) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT auth_credential_version(%s);", (str(user_id),))
        row = cursor.fetchone()
        if row is None or row[0] is None:
            raise HTTPException(401, "This account no longer exists.")
        return int(row[0])


def _verification_fields(email_verified: bool) -> dict:
    return {"email_verified": email_verified, "email_verification_required": security.email_verification_required()}


def _send_account_code(conn, email: str, user_id, token_type: str, expiry: int) -> str:
    """Serialize replacement and retain attempt/send limits even during Redis outages."""
    code = generate_numeric_code()
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0));", ("keel_auth_code:" + str(user_id),))
        cursor.execute("SELECT count(*) FROM auth_tokens WHERE user_id=%s "
                       "AND token_type IN ('PASSWORD_RESET','EMAIL_VERIFICATION') "
                       "AND created_at > now()-make_interval(secs=>%s);", (user_id, auth_throttle.WINDOW_SECONDS))
        if cursor.fetchone()[0] >= auth_throttle.CODE_SENDS_PER_WINDOW:
            raise HTTPException(429, "Too many codes requested. Please try again later.")
    _cancel_active_codes(conn, token_type, email, commit=False)
    _create_token(conn, token_type, code, expiry, commit=False, user_id=user_id)
    conn.commit()
    auth_throttle.reset("code", email)
    return code


def _send_verification_code(conn, email: str, user_id) -> None:
    code = _send_account_code(conn, email, user_id, "EMAIL_VERIFICATION", EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES)
    notifications.send_email_verification_email(email, code)


def _fetch_user_memberships(conn, user_id):
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM auth_lookup_user_memberships(%s);", (user_id,))
        return cursor.fetchall()


class LoginRequest(BaseModel):
    email: str
    password: str
    # Only needed when the account belongs to more than one workspace (see
    # below) - omit it for the common single-workspace case.
    tenant_id: Optional[str] = None


@router.post("/login")
def login(body: LoginRequest) -> dict:
    """
    Real password verification against a real users row (bcrypt, see
    core/security.py::verify_password()) plus real tenant_users membership
    lookup - never a fabricated success. Deliberately the SAME 401 message
    for "no such email" and "wrong password" (never reveals which one it
    was) - standard practice against account enumeration.

    A user belonging to more than one tenant (Final_schema.sql's
    tenant_users is a real many-to-many) can't be resolved to a single
    tenant_id automatically - the response is 409 with the real list of
    workspaces this account belongs to, so a caller can re-request with an
    explicit tenant_id rather than this endpoint guessing which one the
    person meant to log into.
    """
    auth_throttle.ensure_allowed("login", body.email)
    conn = db.auth_lookup_connection()
    try:
        user_row = _fetch_user_by_email(conn, body.email)
        if user_row is None:
            auth_throttle.record_failure("login", body.email)
            raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS_DETAIL)

        user_id, password_hash, full_name, preferred_language = user_row
        if not verify_password(body.password, password_hash):
            auth_throttle.record_failure("login", body.email)
            raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS_DETAIL)
        auth_throttle.reset("login", body.email)

        memberships = _fetch_user_memberships(conn, user_id)
        if not memberships:
            raise HTTPException(
                status_code=403, detail="This account is not associated with any active workspace."
            )

        if body.tenant_id:
            membership = next((m for m in memberships if str(m[0]) == body.tenant_id), None)
            if membership is None:
                raise HTTPException(status_code=403, detail="You do not have access to that workspace.")
        elif len(memberships) == 1:
            membership = memberships[0]
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "This account belongs to multiple workspaces - specify tenant_id.",
                    "workspaces": [
                        {"tenant_id": str(tid), "role_key": role_key, "business_name": business_name}
                        for tid, role_key, business_name in memberships
                    ],
                },
            )

        tenant_id, role_key, business_name = membership
        email_verified = _email_verified(conn, user_id)
        access_token, expires_in = create_access_token(tenant_id=str(tenant_id), user_id=str(user_id),
                                                       email_verified=email_verified, credential_version=_credential_version(conn, user_id))

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "role_key": role_key,
            "business_name": business_name,
            "full_name": full_name,
            "email": body.email.strip().lower(),
            "preferred_language": preferred_language,
            **_verification_fields(email_verified),
        }
    finally:
        conn.close()


class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str
    business_name: str
    # No defaults guessed for either - see this endpoint's own docstring
    # for why currency/country are never invented on a real signup.
    country_code: str
    primary_currency: str


def _insert_company(cursor, tenant_id: str, business_name: str, country_code: str, currency: str, is_demo: bool) -> None:
    cursor.execute(
        """
        INSERT INTO companies (tenant_id, business_name, country_code, primary_currency,
                               supported_currencies, timezone, is_demo)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
        """,
        (
            tenant_id, business_name, country_code.upper(), currency.upper(),
            # The schema defaults are Jordan's (ARRAY['JOD'], 'Asia/Amman') -
            # a tenant in Casablanca or Paris must not inherit them.
            [currency.upper()], default_timezone_for_country(country_code), is_demo,
        ),
    )


def is_demo_email(email: str) -> bool:
    """Owners on the reserved ".example" domain (RFC 2606) can only be
    demonstration accounts; their workspace is labelled as sample data."""
    return (email or "").strip().lower().endswith(".example")


def _start_free_trial(tenant_id: str, user_id: str) -> None:
    """A new company starts on the plan's free trial: once per company, and
    once per person (someone who already started a trial for another company
    doesn't get a second one). A failure or a refused trial never blocks
    sign-up: the company has no plan until it subscribes from Billing."""
    from src.ai.billing import store as billing_store

    try:
        sys_conn = db.system_connection()
    except Exception:  # noqa: BLE001
        logger.exception("Could not open a system connection to start the trial (tenant=%s)", tenant_id)
        return
    try:
        billing_store.start_trial(sys_conn, tenant_id, started_by_user_id=user_id)
        sys_conn.commit()
    except Exception:  # noqa: BLE001
        sys_conn.rollback()
        logger.exception("Could not start the free trial (tenant=%s)", tenant_id)
    finally:
        sys_conn.close()


@router.post("/signup", status_code=202)
def signup(body: SignupRequest) -> dict:
    """Stage a registration; permanent users/companies/memberships require the emailed code."""
    from src.ai.core import pending_registration
    return pending_registration.register(body)


# --- Workspaces: one login, several companies ----------------------------

MAX_OWNED_WORKSPACES = 10


def _session(tenant_id: str, user_id: str, role_key: str, business_name: str, full_name, language, email=None,
             auth_time=None) -> dict:
    lookup = db.auth_lookup_connection()
    try:
        email_verified = _email_verified(lookup, user_id)
        version = _credential_version(lookup, user_id)
    finally:
        lookup.close()
    access_token, expires_in = create_access_token(tenant_id=tenant_id, user_id=user_id, auth_time=auth_time,
                                                   email_verified=email_verified, credential_version=version)
    return {
        "access_token": access_token, "token_type": "bearer", "expires_in": expires_in,
        "tenant_id": tenant_id, "user_id": user_id, "role_key": role_key, "business_name": business_name,
        "full_name": full_name, "preferred_language": language, "email": email,
        **_verification_fields(email_verified),
    }


def _user_profile(conn, user_id: str):
    with conn.cursor() as cursor:
        cursor.execute("SELECT email, full_name, preferred_language FROM users WHERE user_id = %s;", (user_id,))
        return cursor.fetchone()


@router.get("/workspaces")
def list_workspaces(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Every company this login belongs to, for the workspace switcher."""
    conn = db.auth_lookup_connection()
    try:
        memberships = _fetch_user_memberships(conn, ctx.user_id)
    finally:
        conn.close()
    return {"current_tenant_id": ctx.tenant_id, "workspaces": [
        {"tenant_id": str(tid), "role_key": role_key, "business_name": name} for tid, role_key, name in memberships]}


class SwitchWorkspaceRequest(BaseModel):
    tenant_id: str


@router.post("/workspaces/switch")
def switch_workspace(body: SwitchWorkspaceRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """A session for another company this login is an active member of."""
    conn = db.auth_lookup_connection()
    try:
        memberships = _fetch_user_memberships(conn, ctx.user_id)
    finally:
        conn.close()
    membership = next((m for m in memberships if str(m[0]) == body.tenant_id), None)
    if membership is None:
        raise HTTPException(status_code=403, detail="You do not have access to that workspace.")
    conn = db.app_role_connection(body.tenant_id, ctx.user_id)
    try:
        email, full_name, language = _user_profile(conn, ctx.user_id)
        conn.commit()
    finally:
        conn.close()
    # Same sign-in, another company: keeps the sign-in's start time, so
    # switching can't extend a session past SESSION_MAX_HOURS.
    session = _session(body.tenant_id, ctx.user_id, membership[1], membership[2], full_name, language, email,
                       auth_time=getattr(ctx, "auth_time", None))
    security.revoke_token(getattr(ctx, "token_id", None), getattr(ctx, "token_expires_at", None))
    return session


class CreateWorkspaceRequest(BaseModel):
    business_name: str
    country_code: str
    primary_currency: str


@router.post("/workspaces", status_code=201)
def create_workspace(body: CreateWorkspaceRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """A new company owned by the signed-in person - its own data, plan
    trial and setup, fully separate from their other companies. Returns a
    session for the new company."""
    business_name = (body.business_name or "").strip()
    if not business_name or len(business_name) > 200:
        raise HTTPException(status_code=422, detail="A business name of up to 200 characters is required.")
    if len(body.country_code.strip()) != 2 or len(body.primary_currency.strip()) != 3:
        raise HTTPException(status_code=422, detail="Choose a country and a currency.")
    lookup = db.auth_lookup_connection()
    try:
        memberships = _fetch_user_memberships(lookup, ctx.user_id)
    finally:
        lookup.close()
    if sum(1 for m in memberships if m[1] == "owner") >= MAX_OWNED_WORKSPACES:
        raise HTTPException(status_code=409, detail="You've reached the maximum number of companies for one login.")

    tenant_id = str(uuid.uuid4())
    conn = db.app_role_connection(tenant_id, ctx.user_id)
    try:
        email, full_name, language = _user_profile(conn, ctx.user_id) or (None, None, None)
        with conn.cursor() as cursor:
            _insert_company(cursor, tenant_id, business_name, body.country_code.strip(), body.primary_currency.strip(), is_demo_email(email or ""))
            cursor.execute(
                "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');",
                (tenant_id, ctx.user_id),
            )
        conn.commit()
    except psycopg2.errors.CheckViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="One or more fields are invalid. Please check your details and try again.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _start_free_trial(tenant_id, ctx.user_id)
    return _session(tenant_id, ctx.user_id, "owner", business_name, full_name, language or "en", email)


@router.post("/logout")
def logout(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Signs this session out: the token stops working immediately, not
    just when it expires (core/security.py::revoke_token)."""
    revoked = security.revoke_token(getattr(ctx, "token_id", None), getattr(ctx, "token_expires_at", None))
    return {"ok": True, "revoked": revoked}


@router.post("/refresh")
def refresh(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """A new access token for a session that is still valid, so someone using
    the app isn't signed out mid-work. Refused once the sign-in is older than
    SESSION_MAX_HOURS, or when the user is no longer an active member of the
    company. The old token is left to expire on its own (at most
    JWT_EXPIRE_MINUTES), so other open tabs aren't signed out by this one's
    renewal; signing out still revokes immediately."""
    if security.session_age_seconds(ctx) > security.SESSION_MAX_HOURS * 3600:
        raise HTTPException(status_code=401, detail="This sign-in has expired. Please sign in again.")
    conn = db.auth_lookup_connection()
    try:
        memberships = _fetch_user_memberships(conn, ctx.user_id)
        email_verified = _email_verified(conn, ctx.user_id)
        version = _credential_version(conn, ctx.user_id)
    finally:
        conn.close()
    if not any(str(m[0]) == str(ctx.tenant_id) for m in memberships):
        raise HTTPException(status_code=401, detail="You no longer have access to this workspace.")
    # Re-reads the email state, so renewing right after confirming the
    # address gives a token that works everywhere.
    access_token, expires_in = create_access_token(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, auth_time=getattr(ctx, "auth_time", None),
        email_verified=email_verified, credential_version=version)
    return {"access_token": access_token, "token_type": "bearer", "expires_in": expires_in,
            **_verification_fields(email_verified)}


# --- Password reset -----------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: str


def _create_token(conn, token_type: str, raw_token: str, expire_minutes: int, *, commit=True, **fields) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    columns = ["token_type", "token_hash", "expires_at"] + list(fields.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    values = [token_type, hash_token(raw_token), expires_at] + list(fields.values())
    with conn.cursor() as cursor:
        cursor.execute(f"INSERT INTO auth_tokens ({', '.join(columns)}) VALUES ({placeholders});", values)
    if commit:
        conn.commit()


def _fetch_active_token(conn, token_type: str, raw_token: str):
    """Returns the full auth_tokens row for an unused, unexpired token of
    the given type, or None - auth_tokens carries no RLS (see its own
    migration's docstring), so this plain query works on any connection,
    including the unauthenticated db.auth_lookup_connection()."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT token_id, user_id, email, tenant_id, role_key, expires_at
            FROM auth_tokens
            WHERE token_type = %s AND token_hash = %s AND used_at IS NULL AND expires_at > NOW() FOR UPDATE;
            """,
            (token_type, hash_token(raw_token)),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    token_id, user_id, email, tenant_id, role_key, expires_at = row
    if expires_at < datetime.now(timezone.utc):
        return None
    return {
        "token_id": token_id, "user_id": user_id, "email": email,
        "tenant_id": tenant_id, "role_key": role_key,
    }


def _fetch_active_code(conn, token_type: str, email: str, code: str):
    """Resolve the one active user/type row before comparing the low-entropy code."""
    user_row = _fetch_user_by_email(conn, email)
    if user_row is None:
        return None
    with conn.cursor() as cursor:
        cursor.execute("SELECT token_id,user_id,token_hash,expires_at,failed_attempts FROM auth_tokens "
                       "WHERE token_type=%s AND user_id=%s AND used_at IS NULL FOR UPDATE;",
                       (token_type, user_row[0]))
        row = cursor.fetchone()
        if row is None or row[3] <= datetime.now(timezone.utc) or row[4] >= auth_throttle.CODE_MAX_FAILURES:
            return None
        if row[2] != hash_token(code):
            cursor.execute("UPDATE auth_tokens SET failed_attempts=failed_attempts+1 WHERE token_id=%s;", (row[0],))
            conn.commit()  # Preserve the failed attempt even if the endpoint raises 400.
            return None
    return {"token_id": row[0], "user_id": row[1]}


def _cancel_active_codes(conn, token_type: str, email: str, *, commit=True) -> None:
    user_row = _fetch_user_by_email(conn, email)
    if user_row is None:
        return
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE auth_tokens SET used_at = NOW() WHERE token_type = %s AND user_id = %s AND used_at IS NULL;",
            (token_type, user_row[0]),
        )
    if commit:
        conn.commit()


def _active_code_or_reject(conn, token_type: str, email: str, code: str):
    """The shared check for every code-submitting endpoint: per-email
    attempt limit, then the email-bound lookup. Too many wrong codes cancels
    the account's outstanding codes (a new one must be requested)."""
    auth_throttle.ensure_allowed("code", email)
    token = _fetch_active_code(conn, token_type, email, code)
    if token is None:
        if auth_throttle.record_failure("code", email):
            _cancel_active_codes(conn, token_type, email)
            raise HTTPException(status_code=429, detail="Too many incorrect codes. Request a new code to try again.")
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    return token


def _consume_token(conn, token_id) -> None:
    with conn.cursor() as cursor:
        cursor.execute("UPDATE auth_tokens SET used_at = NOW() WHERE token_id = %s AND used_at IS NULL AND expires_at>NOW() RETURNING token_id;", (token_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=400, detail="This token was already used or has expired.")
    conn.commit()


@router.post("/password/forgot")
def forgot_password(body: ForgotPasswordRequest) -> dict:
    """
    Always returns the same generic response whether or not the email is
    registered - the same account-enumeration defense POST /auth/login's
    own docstring already documents for "no such email" vs "wrong
    password". The real code is only ever handed to notifications.
    send_password_reset_email() (logged, not returned in this response) -
    see that module's own docstring for how to read it in local
    development without a real SMTP provider configured.
    """
    auth_throttle.ensure_allowed("send", body.email)
    auth_throttle.record_failure("send", body.email)  # counts requests, not failures
    conn = db.auth_lookup_connection()
    try:
        user_row = _fetch_user_by_email(conn, body.email)
        if user_row is not None:
            user_id = user_row[0]
            code = _send_account_code(conn, body.email, user_id, "PASSWORD_RESET", PASSWORD_RESET_CODE_EXPIRE_MINUTES)
            notifications.send_password_reset_email(body.email, code)
    except HTTPException as exc:
        conn.rollback()
        if exc.status_code != 429:
            raise
        # Durable send budget is deliberately silent: preserve unknown-email parity.
    finally:
        conn.close()
    return {"detail": _GENERIC_CODE_SENT_DETAIL}


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


@router.post("/password/verify-code")
def verify_reset_code(body: VerifyCodeRequest) -> dict:
    """Checks the code without consuming it - POST /auth/password/reset
    re-validates and actually consumes it. Lets the UI confirm a code is
    right before asking for a new password, without spending the code's
    one real use on that confirmation step."""
    conn = db.auth_lookup_connection()
    try:
        _active_code_or_reject(conn, "PASSWORD_RESET", body.email, body.code)
    finally:
        conn.close()
    return {"valid": True}


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


@router.post("/password/reset")
def reset_password(body: ResetPasswordRequest) -> dict:
    ensure_password_policy(body.new_password)
    conn = db.auth_lookup_connection()
    try:
        token = _active_code_or_reject(conn, "PASSWORD_RESET", body.email, body.code)
        new_hash = hash_password(body.new_password)
        with conn.cursor() as cursor:
            cursor.execute("SELECT auth_reset_password(%s, %s);", (token["user_id"], new_hash))
            # The code arrived by email, so the address works.
            cursor.execute("SELECT auth_mark_email_verified(%s);", (token["user_id"],))
        _consume_token(conn, token["token_id"])
        auth_throttle.reset("code", body.email)
        auth_throttle.reset("login", body.email)  # a fresh password starts with a clean slate
    finally:
        conn.close()
    return {"ok": True}


# --- Email verification --------------------------------------------------

class ResendVerificationRequest(BaseModel):
    email: str
    registration_token: Optional[str] = None


@router.post("/email/resend-verification")
def resend_email_verification(body: ResendVerificationRequest) -> dict:
    """Same generic response regardless of whether the email exists or is
    already verified - never confirms account existence to an
    unauthenticated caller."""
    if body.registration_token:
        from src.ai.core import pending_registration
        return pending_registration.resend(body.email, body.registration_token)
    auth_throttle.ensure_allowed("send", body.email)
    auth_throttle.record_failure("send", body.email)  # counts requests, not failures
    conn = db.auth_lookup_connection()
    try:
        user_row = _fetch_user_by_email(conn, body.email)
        if user_row is not None:
            _send_verification_code(conn, body.email, user_row[0])
    except HTTPException as exc:
        conn.rollback()
        if exc.status_code != 429:
            raise
        # Do not reveal account existence through the database fallback budget.
    finally:
        conn.close()
    return {"detail": _GENERIC_CODE_SENT_DETAIL}


class VerifyEmailRequest(BaseModel):
    email: str
    code: str
    registration_token: Optional[str] = None


@router.post("/email/verify")
def verify_email(body: VerifyEmailRequest) -> dict:
    if body.registration_token:
        from src.ai.core import pending_registration
        result = pending_registration.verify(body.email, body.registration_token, body.code)
        if result.get("created"):
            _start_free_trial(result["tenant_id"], result["user_id"])
            return {"ok": True, "email_verified": True, **_session(
                result["tenant_id"], result["user_id"], "owner", result["business_name"],
                result["full_name"], "en", result["email"])}
        return {"ok": True, "email_verified": True, "already_verified": True}
    conn = db.auth_lookup_connection()
    try:
        token = _active_code_or_reject(conn, "EMAIL_VERIFICATION", body.email, body.code)
        with conn.cursor() as cursor:
            cursor.execute("SELECT auth_mark_email_verified(%s);", (token["user_id"],))
        _consume_token(conn, token["token_id"])
        auth_throttle.reset("code", body.email)
    finally:
        conn.close()
    return {"ok": True, "email_verified": True}


# --- Team invitations -----------------------------------------------------
# Creating an invitation (an authenticated, tenant-scoped, owner/admin-only
# action) lives in routers/settings.py's team endpoints, not here - this
# router only covers the public, pre-authentication half: viewing and
# accepting an invitation by its token, which by definition can't require
# the invited person to already be logged in.

@router.get("/invitations/{token}")
def get_invitation(token: str) -> dict:
    conn = db.auth_lookup_connection()
    try:
        invitation = _fetch_active_token(conn, "TEAM_INVITATION", token)
        if invitation is None:
            raise HTTPException(status_code=404, detail="This invitation is invalid or has expired.")
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT business_name FROM companies WHERE tenant_id = %s;", (invitation["tenant_id"],),
            )
            company_row = cursor.fetchone()
            cursor.execute(
                "SELECT role_name FROM system_roles WHERE role_key = %s;", (invitation["role_key"],),
            )
            role_row = cursor.fetchone()
    finally:
        conn.close()
    return {
        "email": invitation["email"],
        "business_name": company_row[0] if company_row else None,
        "role_name": role_row[0] if role_row else invitation["role_key"],
    }


class AcceptInvitationRequest(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None


def _seat_limit(tenant_id: str):
    """The company's seat limit (None = unlimited), read on the billing
    service's connection: the invitee isn't a member yet. A company without
    access gets no new members."""
    sys_conn = db.system_connection()
    try:
        plan = usage.get_plan(sys_conn, tenant_id)
        sys_conn.commit()
    finally:
        sys_conn.close()
    if plan["status"] not in usage.ACCESS_GRANTING_STATUSES:
        raise usage.PlanLimitReached("SUBSCRIPTION_INACTIVE", usage.TEAM_SEATS).as_http()
    feature = plan["features"].get(usage.TEAM_SEATS)
    return feature["limit"] if feature else 0


@router.post("/invitations/{token}/accept")
def accept_invitation(token: str, body: AcceptInvitationRequest) -> dict:
    """Single transaction binds invitation, identity, live seat allowance and consumption."""
    conn = db.auth_lookup_connection()
    try:
        invitation = _fetch_active_token(conn, "TEAM_INVITATION", token)
        if invitation is None:
            raise HTTPException(404, "This invitation is invalid or has expired.")
        tenant_id = str(invitation["tenant_id"])
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0));",
                           ("keel_billing_tenant:" + tenant_id,))
        # Existing entitlement authority reads under the same commercial lock used by Task 6.
        seat_limit = _seat_limit(tenant_id)
        password_hash = None
        if body.password:
            ensure_password_policy(body.password)
            password_hash = hash_password(body.password)
        with conn.cursor() as cursor:
            cursor.execute("SELECT keel_accept_team_invitation(%s,%s,%s,%s);",
                (hash_token(token), (body.full_name or "").strip(), password_hash, seat_limit))
            result = cursor.fetchone()[0]
        conn.commit()
    except psycopg2.errors.RaiseException as exc:
        conn.rollback()
        if "seat_capacity" in str(exc):
            raise usage.PlanLimitReached("CAPACITY_REACHED", usage.TEAM_SEATS).as_http() from None
        raise HTTPException(409, "The invitation could not be accepted. Please try again.") from None
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(409, "This account changed while accepting the invitation. Please try again.") from None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if result.get("error"):
        raise HTTPException(422 if result["error"] == "credentials_required" else 404,
                            "Full name and password are required for a new account." if result["error"] == "credentials_required"
                            else "This invitation is invalid or has expired.")
    return _session(tenant_id, result["user_id"], result["role_key"], result["business_name"],
                    result["full_name"], result.get("preferred_language", "en"), result["email"])
