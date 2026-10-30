"""
Codes in unsent emails never reach the log unless local development asks
for it, and scripts/set_password.py lets an account owner set a password
without email - checked against the real database.
"""
import logging
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.core import notifications

LIVE_DB = pytest.mark.skipif(
    not os.getenv("AI_TEST_DATABASE_URL") or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB password test",
)


@pytest.fixture
def unconfigured_email(monkeypatch):
    monkeypatch.setattr(notifications, "SMTP_HOST", None)


def test_an_unsent_email_does_not_log_its_code(unconfigured_email, monkeypatch, caplog):
    monkeypatch.delenv("EMAIL_LOG_UNSENT_BODIES", raising=False)
    with caplog.at_level(logging.DEBUG, logger="CEOPRO_AI_NOTIFICATIONS"):
        assert notifications.send_password_reset_email("rania@zaytouna.jo", "834201") is False
    logged = caplog.text
    assert "834201" not in logged and "rania@" not in logged
    assert "r***@zaytouna.jo" in logged and "no email service is configured" in logged


def test_local_development_can_opt_in_to_logging_the_body(unconfigured_email, monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_LOG_UNSENT_BODIES", "true")
    with caplog.at_level(logging.INFO, logger="CEOPRO_AI_NOTIFICATIONS"):
        notifications.send_password_reset_email("dev@example.com", "834201")
    assert "834201" in caplog.text


def test_mask_address():
    assert notifications.mask_address("rania@zaytouna.jo") == "r***@zaytouna.jo"
    assert notifications.mask_address("not-an-email") == "***"
    assert notifications.mask_address("") == "***"


@LIVE_DB
def test_set_password_lets_an_existing_owner_sign_in_with_the_new_password():
    from scripts import set_password
    from src.ai.main import app

    client = TestClient(app)
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    email = f"owner+{uuid.uuid4().hex[:8]}@example.test"
    conn = psycopg2.connect(os.environ["AI_TEST_DATABASE_URL"])
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO companies (tenant_id,business_name,country_code,primary_currency) VALUES (%s,'Owner Co','JO','JOD')",
                (tenant_id,),
            )
            cursor.execute(
                "INSERT INTO users (user_id,email,password_hash,full_name,email_verified_at) VALUES (%s,%s,'unused-test-hash','Owner',NOW())",
                (user_id, email),
            )
            cursor.execute(
                "INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,'owner')",
                (tenant_id, user_id),
            )
            cursor.execute(
                "INSERT INTO tenant_plan_assignments (tenant_id,plan_key,status,source) VALUES (%s,'starter','active','manual')",
                (tenant_id,),
            )
        conn.commit()
    finally:
        conn.close()

    assert set_password.set_password(email, "New!Password-2026", mark_verified=True) is True
    assert client.post("/auth/login", json={"email": email, "password": "New!Password-2026"}).status_code == 200
    assert client.post("/auth/login", json={"email": email, "password": "Old!Password-2026"}).status_code == 401
    assert set_password.set_password(f"nobody+{uuid.uuid4().hex[:8]}@example.com", "New!Password-2026") is False


@LIVE_DB
def test_pending_signup_is_not_a_password_reset_target():
    from scripts import set_password
    from src.ai.main import app

    email = f"pending+{uuid.uuid4().hex[:8]}@example.test"
    response = TestClient(app).post("/auth/signup", json={
        "full_name": "Pending", "business_name": "Pending Co", "email": email,
        "country_code": "JO", "primary_currency": "JOD", "password": "Old!Password-2026",
    })
    assert response.status_code == 202
    assert set_password.set_password(email, "New!Password-2026") is False


def test_the_script_rejects_weak_or_mismatched_passwords_and_never_prints_them(monkeypatch, capsys):
    from scripts import set_password

    changed = []
    monkeypatch.setattr(set_password, "set_password", lambda *a, **k: changed.append(a) or True)
    answers = iter(["short"])
    monkeypatch.setattr(set_password.getpass, "getpass", lambda prompt="": next(answers))
    assert set_password.main(["--email", "a@example.com"]) == 2
    answers = iter(["Strong!Pass-2026", "Different!Pass-2026"])
    assert set_password.main(["--email", "a@example.com"]) == 2
    answers = iter(["Strong!Pass-2026", "Strong!Pass-2026"])
    assert set_password.main(["--email", "a@example.com"]) == 0
    out = capsys.readouterr()
    assert "Strong!Pass-2026" not in out.out + out.err
    assert len(changed) == 1
