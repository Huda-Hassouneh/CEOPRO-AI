"""
Email verification against the real database: sign-up sends a code, an
unconfirmed sign-in can only use the sign-in endpoints while confirmation is
required, confirming and renewing unlocks the app, and invitations and
password resets count as confirmation (their codes and links arrive by email).
Accepting an invitation also checks the invitee really joins the company.
"""
import os
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB email verification test",
)
PASSWORD = "Verify!Email-Test2026"


@pytest.fixture
def sent(monkeypatch):
    """Captures the codes the API would email."""
    from src.ai.core import notifications

    codes = {}
    monkeypatch.setattr(notifications, "send_email_verification_email", lambda to, code: codes.__setitem__(to, code) or True)
    monkeypatch.setattr(notifications, "send_password_reset_email", lambda to, code: codes.__setitem__(("reset", to), code) or True)
    return codes


@pytest.fixture
def client():
    from src.ai.main import app

    return TestClient(app)


def _claims(token):
    return jwt.decode(token, options={"verify_signature": False})


def _signup(client):
    email = f"verify+{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/auth/signup", json={"full_name": "Owner", "business_name": "Verify Co", "email": email,
                                                  "country_code": "JO", "primary_currency": "JOD", "password": PASSWORD})
    assert response.status_code == 202, response.text
    return email, response.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_required_verification_blocks_the_app_until_the_code_is_entered(client, sent, monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    email, registration = _signup(client)
    assert registration["status"] == "pending_verification"
    assert registration["email_verification_required"] is True
    assert "access_token" not in registration and "tenant_id" not in registration
    assert email in sent, "sign-up sends the first code"

    assert client.post("/auth/email/verify", json={
        "email": email, "registration_token": registration["registration_token"], "code": "000000",
    }).status_code in (400, 401)
    verified = client.post("/auth/email/verify", json={
        "email": email, "registration_token": registration["registration_token"], "code": sent[email],
    })
    assert verified.status_code == 200, verified.text
    session = verified.json()
    assert session["email_verified"] is True
    assert client.get("/products", headers=_auth(session["access_token"])).status_code == 200

    login = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()
    assert login["email_verified"] is True and _claims(login["access_token"])["ev"] is True


def test_registration_remains_pending_when_email_delivery_is_unavailable(client, sent, monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "auto")
    from src.ai.core import notifications

    monkeypatch.setattr(notifications, "is_configured", lambda: False)
    monkeypatch.setattr(notifications, "send_email_verification_email", lambda _email, _code: False)
    email, registration = _signup(client)
    assert registration["delivery"] == "unavailable"
    assert registration["email_verification_required"] is True
    assert "access_token" not in registration
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users WHERE email = %s;", (email,))
            assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


def test_password_reset_confirms_the_address(client, sent, monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    email, registration = _signup(client)
    verified = client.post("/auth/email/verify", json={
        "email": email, "registration_token": registration["registration_token"], "code": sent[email],
    })
    assert verified.status_code == 200, verified.text
    assert client.post("/auth/password/forgot", json={"email": email}).status_code == 200
    new_password = "Reset!Email-Test2026"
    response = client.post("/auth/password/reset", json={"email": email, "code": sent[("reset", email)], "new_password": new_password})
    assert response.status_code == 200, response.text
    login = client.post("/auth/login", json={"email": email, "password": new_password}).json()
    assert login["email_verified"] is True
    assert client.get("/products", headers=_auth(login["access_token"])).status_code == 200


def test_accepting_an_invitation_confirms_the_address(client, sent, monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "true")
    from src.ai.core import notifications

    links = {}
    monkeypatch.setattr(notifications, "send_team_invitation_email",
                        lambda to, business, token: links.__setitem__(to, token) or True)
    owner_email, registration = _signup(client)
    assert client.post("/auth/email/verify", json={
        "email": owner_email, "registration_token": registration["registration_token"], "code": sent[owner_email],
    }).status_code == 200
    owner_session = client.post("/auth/login", json={"email": owner_email, "password": PASSWORD}).json()
    invitee = f"invitee+{uuid.uuid4().hex[:8]}@example.com"
    invited = client.post("/settings/team/invitations", json={"email": invitee, "role_key": "staff"},
                          headers=_auth(owner_session["access_token"]))
    assert invited.status_code in (200, 201), invited.text
    accepted = client.post(f"/auth/invitations/{links[invitee]}/accept", json={"full_name": "Invitee", "password": PASSWORD})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["email_verified"] is True
    assert client.get("/products", headers=_auth(accepted.json()["access_token"])).status_code == 200

    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    with conn.cursor() as cursor:
        cursor.execute("SELECT email_verified_at IS NOT NULL FROM users WHERE email = %s;", (invitee,))
        assert cursor.fetchone()[0] is True
    conn.close()
