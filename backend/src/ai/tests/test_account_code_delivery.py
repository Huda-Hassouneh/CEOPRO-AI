"""Account-code emails report what really happened.

Exercises the real notifications.send_email path with smtplib replaced, so a
timeout, a refused SMTP login and a provider rejection each travel the same
code as production: the API answers 503 EMAIL_DELIVERY_FAILED (never "sent"),
cancels the undelivered code, and logs only the error type.
"""
import logging
import smtplib
import socket
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.ai.core import auth_throttle, notifications
from src.ai.main import app

client = TestClient(app)
EMAIL = "jane@example.com"
CODE = "482913"
SMTP_SECRET = "smtp-secret-value"


def _conn():
    conn = MagicMock()
    conn.close = MagicMock()
    return conn


@pytest.fixture
def smtp_configured(monkeypatch):
    monkeypatch.setattr(notifications, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(notifications, "SMTP_USERNAME", "relay-login")
    monkeypatch.setattr(notifications, "SMTP_PASSWORD", SMTP_SECRET)
    monkeypatch.setattr(notifications, "SMTP_USE_TLS", True)


def _smtp(*, connect=None, login=None, sendmail=None):
    """A stand-in for smtplib.SMTP whose steps can fail like a real relay."""
    server = MagicMock()
    server.login.side_effect = login
    server.sendmail.side_effect = sendmail
    factory = MagicMock(side_effect=connect)
    if connect is None:
        factory.return_value.__enter__.return_value = server
    return factory, server


def _post(path, smtp_factory):
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._send_account_code", return_value=CODE) as issued, \
         patch("src.ai.routers.auth._cancel_active_codes") as cancelled, \
         patch("src.ai.core.notifications.smtplib.SMTP", smtp_factory), \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False):
        return client.post(path, json={"email": EMAIL}), issued, cancelled


FAILURES = {
    "timeout": dict(connect=socket.timeout("timed out")),
    "connection_refused": dict(connect=ConnectionRefusedError("refused")),
    "authentication_failure": dict(login=smtplib.SMTPAuthenticationError(535, f"bad login for {SMTP_SECRET}".encode())),
    "provider_rejected_recipient": dict(sendmail=smtplib.SMTPRecipientsRefused({EMAIL: (550, b"rejected")})),
    "provider_rejected_sender": dict(sendmail=smtplib.SMTPSenderRefused(553, b"sender not authorised", "no-reply@keel.ai")),
    "provider_rejected_data": dict(sendmail=smtplib.SMTPDataError(554, b"message refused")),
}


@pytest.mark.parametrize("path, token_type", [
    ("/auth/password/forgot", "PASSWORD_RESET"),
    ("/auth/email/resend-verification", "EMAIL_VERIFICATION"),
])
@pytest.mark.parametrize("failure", sorted(FAILURES))
def test_a_failed_send_is_reported_truthfully_and_the_code_is_cancelled(smtp_configured, caplog, path, token_type, failure):
    factory, _ = _smtp(**FAILURES[failure])
    with caplog.at_level(logging.DEBUG):
        response, issued, cancelled = _post(path, factory)

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "EMAIL_DELIVERY_FAILED"
    assert "sent" not in body["detail"].lower() and "try again" in body["detail"].lower()
    assert response.headers["Retry-After"] == "60"
    issued.assert_called_once()
    cancelled.assert_called_once()
    assert cancelled.call_args.args[1:] == (token_type, EMAIL)
    # Nothing sensitive leaks into the response or the logs.
    leaked = response.text + caplog.text
    for secret in (CODE, SMTP_SECRET, "relay-login", "bad login", "rejected", "refused"):
        assert secret not in response.text
    assert CODE not in caplog.text and SMTP_SECRET not in caplog.text and EMAIL not in leaked
    assert "Account code email not delivered" in caplog.text


@pytest.mark.parametrize("path", ["/auth/password/forgot", "/auth/email/resend-verification"])
def test_unconfigured_email_is_a_delivery_failure_not_a_sent_code(monkeypatch, path):
    monkeypatch.setattr(notifications, "SMTP_HOST", None)
    factory, _ = _smtp()
    response, _, cancelled = _post(path, factory)
    assert response.status_code == 503 and response.json()["code"] == "EMAIL_DELIVERY_FAILED"
    factory.assert_not_called()
    cancelled.assert_called_once()


@pytest.mark.parametrize("path", ["/auth/password/forgot", "/auth/email/resend-verification"])
def test_sent_only_when_the_provider_accepted_the_message(smtp_configured, path):
    factory, server = _smtp()
    response, issued, cancelled = _post(path, factory)
    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert CODE not in response.text
    server.login.assert_called_once()
    server.sendmail.assert_called_once()
    assert server.sendmail.call_args.args[1] == [EMAIL]
    cancelled.assert_not_called()


def test_a_retry_after_a_failure_can_succeed(smtp_configured):
    failing, _ = _smtp(connect=socket.timeout("timed out"))
    first, _, _ = _post("/auth/password/forgot", failing)
    working, _ = _smtp()
    second, _, _ = _post("/auth/password/forgot", working)
    assert (first.status_code, second.status_code) == (503, 200)


def test_the_per_email_send_throttle_still_applies_before_any_lookup():
    from fastapi import HTTPException

    def refuse(*_a):
        raise HTTPException(429, "Too many attempts. Please wait and try again.")

    with patch.object(auth_throttle, "ensure_allowed", side_effect=refuse), \
         patch("src.ai.routers.auth.db.auth_lookup_connection") as lookup:
        response = client.post("/auth/password/forgot", json={"email": EMAIL})
    assert response.status_code == 429
    lookup.assert_not_called()


def test_the_per_account_database_send_budget_is_reported_not_hidden():
    from fastapi import HTTPException

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._send_account_code",
               side_effect=HTTPException(429, "Too many codes requested. Please try again later.")), \
         patch("src.ai.routers.auth.notifications.send_password_reset_email") as send, \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False):
        response = client.post("/auth/password/forgot", json={"email": EMAIL})
    assert response.status_code == 429
    send.assert_not_called()
