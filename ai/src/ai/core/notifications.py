"""
KEEL - Outbound Email Notifications.

The real gap this closes: password-reset codes, email-verification codes,
and team-invitation links all need to reach a real inbox, but no email-
sending capability existed anywhere in this repo before this file - not
even a placeholder. Deciding which transactional-email vendor to use
(SendGrid, AWS SES, Postmark, Mailgun...) is a real product/infra decision
this track doesn't make unilaterally, so this module is built the same way
every other optional external dependency in this codebase already is
(GOOGLE_CUSTOM_SEARCH_API_KEY, LOCAL_LLM_BASE_URL, SEARXNG_INSTANCE_URL):
a real, working implementation behind a plain SMTP interface (works with
literally any provider - every major transactional-email vendor exposes an
SMTP endpoint alongside its own API), configured via env vars, that
degrades HONESTLY - never silently, never fabricating a "sent" response -
when unconfigured.

Unconfigured behavior (no SMTP_HOST set): nothing is sent and the call
returns False. The log records only that delivery isn't configured, the
subject and a masked recipient - never the body, because the body carries
a live password-reset or verification code. Only for local development,
EMAIL_LOG_UNSENT_BODIES=true also logs the body so the signup/reset/
verify/invite flows can be completed from the server log without a
mailbox; it must stay unset anywhere real accounts exist.
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger("CEOPRO_AI_NOTIFICATIONS")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() != "false"
EMAIL_FROM_ADDRESS = os.getenv("EMAIL_FROM_ADDRESS", "no-reply@keel.ai")


def _log_unsent_bodies() -> bool:
    return os.getenv("EMAIL_LOG_UNSENT_BODIES", "").lower() in ("1", "true", "yes")


def mask_address(address: str) -> str:
    """'rania@zaytouna.jo' -> 'r***@zaytouna.jo' (enough to tell mails apart in a log)."""
    local, _, domain = (address or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def is_configured() -> bool:
    return bool(SMTP_HOST)


def send_email(to_address: str, subject: str, body: str) -> bool:
    """
    Returns True if a real send was attempted and succeeded, False if
    unconfigured (logged instead) - never raises for the unconfigured
    case, since a missing email provider must never break the underlying
    auth flow (a real reset/verification/invitation TOKEN is always
    created and valid regardless of whether the notification email itself
    could be delivered - see routers/auth.py's own callers, none of which
    treat this return value as fatal). A real SMTP failure (bad
    credentials, unreachable host) DOES raise - that's a real
    configuration problem worth surfacing loudly, not the same as "no
    provider chosen yet".
    """
    if not is_configured():
        if _log_unsent_bodies():
            logger.info("SMTP_HOST not set - email not sent (EMAIL_LOG_UNSENT_BODIES on, local development). "
                        "to=%s subject=%r body=%s", to_address, subject, body)
        else:
            logger.warning("Email not sent: no email service is configured (SMTP_HOST). to=%s subject=%r",
                           mask_address(to_address), subject)
        return False

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = EMAIL_FROM_ADDRESS
    message["To"] = to_address

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        if SMTP_USE_TLS:
            server.starttls()
        if SMTP_USERNAME and SMTP_PASSWORD:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM_ADDRESS, [to_address], message.as_string())
    return True


def send_password_reset_email(to_address: str, code: str) -> bool:
    return send_email(
        to_address, "Your KEEL password reset code",
        f"Your password reset code is: {code}\n\nThis code expires soon. If you didn't request this, you can ignore this email.",
    )


def send_email_verification_email(to_address: str, code: str) -> bool:
    return send_email(
        to_address, "Verify your KEEL email address",
        f"Your email verification code is: {code}",
    )


def send_team_invitation_email(to_address: str, business_name: str, invite_token: str) -> bool:
    frontend_base_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
    return send_email(
        to_address, f"You've been invited to join {business_name} on KEEL",
        f"You've been invited to join {business_name} on KEEL. "
        f"Accept your invitation here: {frontend_base_url}/invitation/{invite_token}",
    )
