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
from src.infrastructure.public_urls import frontend_origin
import logging
import os
import smtplib
from typing import Optional
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


def email_language(language: Optional[str]) -> str:
    """'ar' for an Arabic reader, otherwise 'en' (the two languages KEEL is written in)."""
    return "ar" if str(language or "").strip().lower().startswith("ar") else "en"


def _duration(minutes: int, language: str) -> str:
    """How long a code or link stays valid, in words, with Arabic counted nouns agreeing with the number."""
    minutes = max(1, int(minutes))
    if minutes % (24 * 60) == 0:
        count, unit = minutes // (24 * 60), ("day", "days", "يوم واحد", "يومان", "أيام", "يومًا")
    elif minutes % 60 == 0:
        count, unit = minutes // 60, ("hour", "hours", "ساعة واحدة", "ساعتان", "ساعات", "ساعة")
    else:
        count, unit = minutes, ("minute", "minutes", "دقيقة واحدة", "دقيقتان", "دقائق", "دقيقة")
    if language != "ar":
        return f"{count} {unit[0] if count == 1 else unit[1]}"
    if count == 1:
        return unit[2]
    if count == 2:
        return unit[3]
    return f"{count} {unit[4] if 3 <= count % 100 <= 10 else unit[5]}"


def _account_code_email(kind: str, code: str, language: str, minutes: int) -> tuple:
    valid = _duration(minutes, language)
    if language == "ar":
        if kind == "reset":
            return ("رمز إعادة تعيين كلمة المرور في KEEL",
                    f"رمز إعادة تعيين كلمة المرور الخاص بك هو: {code}\n\n"
                    f"مدة صلاحية هذا الرمز {valid}. إذا لم تطلب إعادة تعيين كلمة المرور، يمكنك تجاهل هذه الرسالة.")
        return ("تأكيد عنوان بريدك الإلكتروني في KEEL",
                f"رمز تأكيد بريدك الإلكتروني هو: {code}\n\n"
                f"مدة صلاحية هذا الرمز {valid}. إذا لم تنشئ حسابًا في KEEL، يمكنك تجاهل هذه الرسالة.")
    if kind == "reset":
        return ("Your KEEL password reset code",
                f"Your password reset code is: {code}\n\n"
                f"This code is valid for {valid}. If you didn't request a password reset, you can ignore this email.")
    return ("Verify your KEEL email address",
            f"Your email verification code is: {code}\n\n"
            f"This code is valid for {valid}. If you didn't create a KEEL account, you can ignore this email.")


def send_password_reset_email(to_address: str, code: str, language: Optional[str] = None,
                              minutes: Optional[int] = None) -> bool:
    from src.ai.core.security import PASSWORD_RESET_CODE_EXPIRE_MINUTES
    subject, body = _account_code_email("reset", code, email_language(language),
                                        minutes or PASSWORD_RESET_CODE_EXPIRE_MINUTES)
    return send_email(to_address, subject, body)


def send_email_verification_email(to_address: str, code: str, language: Optional[str] = None,
                                  minutes: Optional[int] = None) -> bool:
    from src.ai.core.security import EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES
    subject, body = _account_code_email("verify", code, email_language(language),
                                        minutes or EMAIL_VERIFICATION_CODE_EXPIRE_MINUTES)
    return send_email(to_address, subject, body)


def send_team_invitation_email(to_address: str, business_name: str, invite_token: str,
                               language: Optional[str] = None, minutes: Optional[int] = None) -> bool:
    from src.ai.core.security import TEAM_INVITATION_EXPIRE_MINUTES
    frontend_base_url = frontend_origin()
    # A company name is the owner's own text: collapse line breaks so it can never reach a mail header
    # (the stdlib would refuse the whole message) or start a header-looking line in the body.
    name = " ".join(str(business_name).split())
    link = f"{frontend_base_url}/invitation/{invite_token}"
    lang = email_language(language)
    valid = _duration(minutes or TEAM_INVITATION_EXPIRE_MINUTES, lang)
    if lang == "ar":
        return send_email(to_address, f"دعوة للانضمام إلى {name} على KEEL",
                          f"تمت دعوتك للانضمام إلى {name} على KEEL. اقبل الدعوة من هنا: {link}\n\n"
                          f"مدة صلاحية هذه الدعوة {valid}.")
    return send_email(
        to_address, f"You've been invited to join {name} on KEEL",
        f"You've been invited to join {name} on KEEL. Accept your invitation here: {link}\n\n"
        f"This invitation is valid for {valid}.",
    )
