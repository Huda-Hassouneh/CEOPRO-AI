"""Email-bound pending registration using the existing Python identity and trial services."""
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from psycopg2 import Error as DatabaseError
from psycopg2.extras import Json

from src.ai import db
from src.ai.core import auth_throttle, notifications, security
from src.ai.core.calendar import default_timezone_for_country

logger = logging.getLogger(__name__)


def _call(action, payload):
    conn = None
    try:
        conn = db.auth_lookup_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT keel_pending_registration(%s, %s);", (action, Json(payload)))
            result = cursor.fetchone()[0]
        # Failed-code counters are committed too; raising before commit would erase attempts.
        conn.commit()
        return result
    except DatabaseError as exc:
        if conn is not None:
            conn.rollback()
        status = 409 if exc.pgcode == "23505" else 422 if exc.pgcode in {"23514", "22001"} else 503
        raise HTTPException(status, "Registration could not be completed. Check your details or try again later.") from None
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def _limits():
    return {"max_attempts": auth_throttle.CODE_MAX_FAILURES,
            "max_sends": auth_throttle.CODE_SENDS_PER_WINDOW,
            "send_window_seconds": auth_throttle.WINDOW_SECONDS}


def _deliver(email, code):
    try:
        return bool(notifications.send_email_verification_email(email, code))
    except Exception:  # Durable pending state remains retryable; no identity was created.
        logger.warning("Pending registration email delivery failed")
        return False


def register(body):
    email = body.email.strip().lower()
    if len(email) > 255 or not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email):
        raise HTTPException(422, "Enter a valid email address.")
    name, business = body.full_name.strip(), body.business_name.strip()
    if not name or len(name) > 150 or not business or len(business) > 200:
        raise HTTPException(422, "Full name and business name are required and must fit their field limits.")
    country, currency = body.country_code.strip().upper(), body.primary_currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise HTTPException(422, "Choose a country and currency.")
    security.ensure_password_policy(body.password)
    auth_throttle.ensure_allowed("send", email)
    auth_throttle.record_failure("send", email)
    token, code = security.generate_url_safe_token(), security.generate_numeric_code()
    result = _call("register", {"email": email, "full_name": name, "business_name": business,
        "country_code": country, "currency": currency, "timezone": default_timezone_for_country(country),
        "password_hash": security.hash_password(body.password), "request_hash": security.hash_token(token),
        "code_hash": security.hash_token(code), "expires_at": (datetime.now(timezone.utc) + timedelta(
            minutes=security.EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES)).isoformat(), **_limits()})
    if result["status"] != "pending":
        raise HTTPException(409, "This address already has an account or pending registration. Sign in or use your original verification tab.")
    return {"status": "pending_verification", "email": email, "registration_token": token,
            "email_verification_required": True, "delivery": "sent" if _deliver(email, code) else "unavailable"}


def resend(email, token):
    email = email.strip().lower()
    code = security.generate_numeric_code()
    result = _call("resend", {"email": email, "request_hash": security.hash_token(token),
                             "code_hash": security.hash_token(code), **_limits()})
    if result["status"] == "limited":
        raise HTTPException(429, "Too many codes requested. Try again later.")
    delivered = result["status"] == "pending" and _deliver(email, code)
    return {"detail": "If this registration is valid, a code has been sent.",
            "delivery": "sent" if delivered else "unavailable"}


def verify(email, token, code):
    result = _call("verify", {"email": email.strip().lower(), "request_hash": security.hash_token(token),
                            "code_hash": security.hash_token(code), **_limits()})
    if result["status"] == "limited":
        raise HTTPException(429, "Too many incorrect codes. Start a new registration after this one expires.")
    if result["status"] == "conflict":
        raise HTTPException(409, "An account now exists for this address. Sign in to continue.")
    if result["status"] not in ("created", "verified"):
        raise HTTPException(400, "Invalid or expired verification code.")
    return result
