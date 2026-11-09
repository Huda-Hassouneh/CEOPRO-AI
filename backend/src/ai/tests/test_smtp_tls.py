"""Offline SMTP transport checks: real SSL contexts, no network or email."""
import logging
import smtplib
import ssl
from email import message_from_string
from unittest.mock import MagicMock, call

import pytest

from src.ai.core import notifications, pending_registration


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setattr(notifications, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(notifications, "SMTP_PORT", 2525)
    monkeypatch.setattr(notifications, "SMTP_USERNAME", "synthetic-smtp-login")
    monkeypatch.setattr(notifications, "SMTP_PASSWORD", "synthetic-smtp-password")
    monkeypatch.setattr(notifications, "SMTP_USE_TLS", True)
    monkeypatch.setattr(notifications, "EMAIL_FROM_ADDRESS", "keel@example.test")
    monkeypatch.setenv("EMAIL_LOG_UNSENT_BODIES", "false")
    constructor = MagicMock()
    server = constructor.return_value.__enter__.return_value
    monkeypatch.setattr(notifications.smtplib, "SMTP", constructor)
    return constructor, server


def assert_no_sensitive_logs(caplog):
    for secret in ("synthetic-smtp-password", "smtp-verification-649281",
                   "smtp-reset-315928", "smtp-invitation-token", "private-message-body"):
        assert secret not in caplog.text


def test_smtp_passes_validating_context_before_authentication_and_delivery(smtp, caplog):
    constructor, server = smtp
    with caplog.at_level(logging.DEBUG):
        assert notifications.send_email("judge@example.test", "KEEL", "private-message-body") is True
    constructor.assert_called_once_with("smtp.example.test", 2525, timeout=10)
    server.starttls.assert_called_once()
    context = server.starttls.call_args.kwargs["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()["x509_ca"] > 0
    server.login.assert_called_once_with("synthetic-smtp-login", "synthetic-smtp-password")
    server.sendmail.assert_called_once()
    sender, recipients, serialized = server.sendmail.call_args.args
    assert sender == "keel@example.test" and recipients == ["judge@example.test"]
    message = message_from_string(serialized)
    assert message["From"] == sender and message["To"] == recipients[0]
    assert message["Subject"] == "KEEL" and message.get_payload(decode=True) == b"private-message-body"
    assert server.method_calls == [call.starttls(context=context),
                                   call.login("synthetic-smtp-login", "synthetic-smtp-password"),
                                   call.sendmail(sender, recipients, serialized)]
    constructor.return_value.__exit__.assert_called_once_with(None, None, None)
    assert_no_sensitive_logs(caplog)


@pytest.mark.parametrize("error", [
    ssl.SSLCertVerificationError(1, "untrusted certificate"),
    ssl.SSLCertVerificationError(1, "hostname mismatch"),
    smtplib.SMTPNotSupportedError("STARTTLS unavailable"),
    smtplib.SMTPResponseException(454, b"TLS temporarily unavailable"),
    ssl.SSLError("TLS handshake failed"),
])
def test_smtp_tls_failure_propagates_without_auth_send_or_plaintext_retry(smtp, caplog, error):
    constructor, server = smtp
    server.starttls.side_effect = error
    with caplog.at_level(logging.DEBUG), pytest.raises(type(error)) as raised:
        notifications.send_email_verification_email("judge@example.test", "smtp-verification-649281")
    assert raised.value is error
    constructor.assert_called_once()  # No new plaintext connection or retry.
    server.starttls.assert_called_once()
    server.login.assert_not_called()
    server.sendmail.assert_not_called()
    assert constructor.return_value.__exit__.call_args.args[1] is error
    assert_no_sensitive_logs(caplog)


def test_smtp_auth_failure_propagates_without_delivery_or_sensitive_logging(smtp, caplog):
    _, server = smtp
    server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication refused")
    with caplog.at_level(logging.DEBUG), pytest.raises(smtplib.SMTPAuthenticationError):
        notifications.send_password_reset_email("judge@example.test", "smtp-reset-315928")
    server.starttls.assert_called_once()
    server.sendmail.assert_not_called()
    assert_no_sensitive_logs(caplog)


@pytest.mark.parametrize("kind", ["verification", "reset", "invitation"])
def test_smtp_existing_keel_messages_deliver_without_sensitive_logging(smtp, caplog, monkeypatch, kind):
    _, server = smtp
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://keel.example.test")
    with caplog.at_level(logging.DEBUG):
        if kind == "verification":
            sent = notifications.send_email_verification_email("judge@example.test", "smtp-verification-649281")
        elif kind == "reset":
            sent = notifications.send_password_reset_email("judge@example.test", "smtp-reset-315928")
        else:
            sent = notifications.send_team_invitation_email("judge@example.test", "KEEL", "smtp-invitation-token")
    assert sent is True
    server.starttls.assert_called_once()
    server.sendmail.assert_called_once()
    message = message_from_string(server.sendmail.call_args.args[2])
    assert "KEEL" in message["Subject"]
    if kind == "invitation":
        assert "https://keel.example.test/invitation/smtp-invitation-token" in message.get_payload(decode=True).decode()
    assert_no_sensitive_logs(caplog)


def test_smtp_explicit_local_no_tls_setting_is_unchanged(smtp, monkeypatch):
    _, server = smtp
    monkeypatch.setattr(notifications, "SMTP_USE_TLS", False)
    assert notifications.send_email("local@example.test", "KEEL", "private-message-body") is True
    server.starttls.assert_not_called()
    server.login.assert_called_once()
    server.sendmail.assert_called_once()


def test_smtp_pending_registration_reports_failed_tls_delivery_without_code_logging(smtp, caplog):
    _, server = smtp
    server.starttls.side_effect = ssl.SSLCertVerificationError(1, "untrusted certificate")
    with caplog.at_level(logging.DEBUG):
        assert pending_registration._deliver("judge@example.test", "smtp-verification-649281") is False
    server.login.assert_not_called()
    server.sendmail.assert_not_called()
    assert "Pending registration email delivery failed" in caplog.text
    assert_no_sensitive_logs(caplog)
