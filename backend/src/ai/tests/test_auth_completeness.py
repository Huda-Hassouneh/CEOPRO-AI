"""
Unit tests for the new auth endpoints in routers/auth.py (signup, logout,
password reset, email verification, team invitations) - offline, same
convention as test_auth.py: DB calls mocked (the router's own helper
functions, not raw SQL - matching how test_auth.py already mocks
_fetch_login_identity/_fetch_user_memberships rather than cursor-level SQL).
"""
import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.core.security import create_access_token  # noqa: E402
from src.ai.main import app  # noqa: E402

client = TestClient(app)


def _fake_conn():
    conn = MagicMock()
    conn.close = MagicMock()
    return conn


class _CounterStore:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, _seconds):
        return key in self.values

    def ttl(self, _key):
        from src.ai.core import auth_throttle
        return auth_throttle.WINDOW_SECONDS

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)


def _auth_header():
    token, _ = create_access_token(
        tenant_id="00000000-0000-4000-8000-000000000001",
        user_id="00000000-0000-4000-8000-000000000002",
    )
    return {"Authorization": f"Bearer {token}"}


# --- signup -----------------------------------------------------------

def test_signup_rejects_an_existing_or_pending_email():
    from src.ai.core import auth_throttle, pending_registration

    with patch.object(pending_registration, "_call", return_value={"status": "conflict"}), \
         patch.object(pending_registration.notifications, "send_email_verification_email") as send, \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False), \
         patch.object(auth_throttle, "reset"):
        response = client.post("/auth/signup", json={
            "email": "jane@example.com", "password": "Str0ng!Passw0rd", "full_name": "Jane",
            "business_name": "Jane's Shop", "country_code": "jo", "primary_currency": "jod",
        })
    assert response.status_code == 409
    send.assert_not_called()


def test_signup_stages_pending_registration_without_creating_a_session():
    from src.ai.core import auth_throttle, pending_registration

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch("src.ai.routers.auth._insert_company") as insert_company, \
         patch("src.ai.routers.auth._start_free_trial") as start_trial, \
         patch.object(pending_registration, "_call", return_value={"status": "pending"}) as register, \
         patch.object(pending_registration.notifications, "send_email_verification_email", return_value=True), \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False), \
         patch.object(auth_throttle, "reset"):
        response = client.post("/auth/signup", json={
            "email": "new@example.com", "password": "Str0ng!Passw0rd",
            "full_name": "New Owner", "business_name": "New Shop",
            "country_code": "jo", "primary_currency": "jod",
        })

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending_verification"
    assert body["delivery"] == "sent"
    assert not {"access_token", "user_id", "tenant_id"} & body.keys()
    payload = register.call_args.args[1]
    assert payload["country_code"] == "JO"
    assert payload["currency"] == "JOD"
    insert_company.assert_not_called()
    start_trial.assert_not_called()


def test_signup_reports_pending_state_when_verification_delivery_is_unavailable():
    from src.ai.core import auth_throttle, pending_registration

    with patch.object(pending_registration, "_call", return_value={"status": "pending"}), \
         patch.object(pending_registration.notifications, "send_email_verification_email", return_value=False), \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False), \
         patch.object(auth_throttle, "reset"):
        response = client.post("/auth/signup", json={
            "email": "delivery@example.com", "password": "Str0ng!Passw0rd",
            "full_name": "Owner", "business_name": "Shop",
            "country_code": "jo", "primary_currency": "jod",
        })

    assert response.status_code == 202
    assert response.json()["delivery"] == "unavailable"
    assert "access_token" not in response.json()


def test_signup_uppercases_country_code_and_currency():
    from src.ai.core import auth_throttle, pending_registration

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch.object(pending_registration, "_call", return_value={"status": "pending"}) as register, \
         patch.object(pending_registration.notifications, "send_email_verification_email", return_value=True), \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False), \
         patch.object(auth_throttle, "reset"):
        response = client.post("/auth/signup", json={
            "email": "new2@example.com", "password": "Str0ng!Passw0rd", "full_name": "Owner",
            "business_name": "Shop", "country_code": "jo", "primary_currency": "jod",
        })

    assert response.status_code == 202
    payload = register.call_args.args[1]
    assert payload["country_code"] == "JO"
    assert payload["currency"] == "JOD"


# --- logout -------------------------------------------------------------

def test_logout_requires_auth():
    assert client.post("/auth/logout").status_code == 401


def test_logout_revokes_an_authenticated_caller():
    with patch("src.ai.core.security.assert_active_principal"), \
         patch("src.ai.core.security.is_token_revoked", return_value=False), \
         patch("src.ai.core.security.revoke_token", return_value=True) as revoke:
        response = client.post("/auth/logout", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {"ok": True, "revoked": True}
    revoke.assert_called_once()


# --- password reset -------------------------------------------------------

def test_forgot_password_sends_a_code_for_a_registered_email():
    from src.ai.core import auth_throttle

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._send_account_code", return_value="123456") as send_code, \
         patch("src.ai.routers.auth.notifications.send_password_reset_email") as mock_send, \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False):
        response = client.post("/auth/password/forgot", json={"email": "jane@example.com"})

    assert response.status_code == 200
    send_code.assert_called_once()
    assert send_code.call_args.args[1:4] == ("jane@example.com", "u1", "PASSWORD_RESET")
    mock_send.assert_called_once_with("jane@example.com", "123456")


def test_forgot_password_never_reveals_whether_the_email_exists():
    """Same generic response, and no token/email attempt at all, for an
    unregistered email - never lets a caller distinguish the two."""
    from src.ai.core import auth_throttle

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch("src.ai.routers.auth._send_account_code") as send_unknown, \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False):
        known = client.post("/auth/password/forgot", json={"email": "unknown@example.com"})

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._send_account_code", return_value="123456") as send_registered, \
         patch("src.ai.routers.auth.notifications.send_password_reset_email"), \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False):
        registered = client.post("/auth/password/forgot", json={"email": "jane@example.com"})

    assert known.json() == registered.json()
    send_unknown.assert_not_called()
    send_registered.assert_called_once()


def test_verify_reset_code_rejects_an_invalid_code(monkeypatch):
    from src.ai.core import auth_throttle

    monkeypatch.setattr(auth_throttle, "ensure_allowed", lambda *a: None)
    monkeypatch.setattr(auth_throttle, "record_failure", lambda *a: False)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_code", return_value=None):
        response = client.post("/auth/password/verify-code", json={"email": "jane@example.com", "code": "000000"})
    assert response.status_code == 400


def test_verify_reset_code_accepts_a_valid_account_code(monkeypatch):
    from src.ai.core import auth_throttle

    monkeypatch.setattr(auth_throttle, "ensure_allowed", lambda *a: None)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_code", return_value={"token_id": "t1", "user_id": "u1"}):
        response = client.post("/auth/password/verify-code", json={"email": "jane@example.com", "code": "123456"})
    assert response.status_code == 200
    assert response.json() == {"valid": True}


def test_reset_password_updates_the_password_and_consumes_the_code(monkeypatch):
    from src.ai.core import auth_throttle

    conn = _fake_conn()
    monkeypatch.setattr(auth_throttle, "ensure_allowed", lambda *a: None)
    monkeypatch.setattr(auth_throttle, "reset", lambda *a: None)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_active_code", return_value={"token_id": "t1", "user_id": "u1"}), \
         patch("src.ai.routers.auth._consume_token") as mock_consume:
        response = client.post(
            "/auth/password/reset",
            json={"email": "jane@example.com", "code": "123456", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 200
    mock_consume.assert_called_once_with(conn, "t1")
    statements = [call.args[0] for call in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
    assert any("auth_reset_password" in statement for statement in statements)
    assert any("auth_mark_email_verified" in statement for statement in statements)


def test_reset_password_rejects_an_expired_or_invalid_code(monkeypatch):
    from src.ai.core import auth_throttle

    monkeypatch.setattr(auth_throttle, "ensure_allowed", lambda *a: None)
    monkeypatch.setattr(auth_throttle, "record_failure", lambda *a: False)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_code", return_value=None):
        response = client.post(
            "/auth/password/reset", json={"email": "jane@example.com", "code": "000000", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 400


# --- email verification ----------------------------------------------------

def test_verify_email_marks_verified_and_consumes_the_token():
    conn = _fake_conn()
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._fetch_active_code", return_value={"token_id": "t1", "user_id": "u1"}), \
         patch("src.ai.routers.auth._consume_token") as mock_consume:
        response = client.post("/auth/email/verify", json={"email": "jane@example.com", "code": "123456"})
    assert response.status_code == 200
    assert response.json()["email_verified"] is True
    mock_consume.assert_called_once()


def test_resend_verification_never_reveals_whether_the_email_exists():
    from src.ai.core import auth_throttle

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch.object(auth_throttle, "ensure_allowed"), \
         patch.object(auth_throttle, "record_failure", return_value=False):
        response = client.post("/auth/email/resend-verification", json={"email": "unknown@example.com"})
    assert response.status_code == 200


# --- team invitations -------------------------------------------------------

def test_get_invitation_returns_404_for_an_invalid_token():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_token", return_value=None):
        response = client.get("/auth/invitations/bad-token")
    assert response.status_code == 404


def test_get_invitation_returns_real_invite_details_for_a_valid_token():
    conn = _fake_conn()
    fetch_results = iter([("Jane's Shop",), ("Staff Member",)])
    conn.cursor.return_value.__enter__.return_value.fetchone.side_effect = lambda: next(fetch_results)

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={
             "email": "invitee@example.com", "tenant_id": "t1", "role_key": "staff",
         }):
        response = client.get("/auth/invitations/good-token")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "invitee@example.com"
    assert body["business_name"] == "Jane's Shop"
    assert body["role_name"] == "Staff Member"


def test_accept_invitation_requires_full_name_and_password_for_a_brand_new_user():
    conn = _fake_conn()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ({"error": "credentials_required"},)
    with patch("src.ai.routers.auth._fetch_active_token", return_value={
             "token_id": "tok1", "email": "new@example.com", "tenant_id": "t1", "role_key": "staff",
         }), \
         patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._seat_limit", return_value=5):
        response = client.post("/auth/invitations/good-token/accept", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "Full name and password are required for a new account."
    conn.commit.assert_called_once()


def test_accept_invitation_joins_an_existing_user_without_needing_a_password():
    conn = _fake_conn()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ({
        "user_id": "00000000-0000-4000-8000-000000000002",
        "email": "existing@example.com",
        "full_name": "Existing User",
        "business_name": "Shop",
        "role_key": "staff",
        "preferred_language": "en",
    },)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={
             "token_id": "tok1", "email": "existing@example.com", "tenant_id": "t1", "role_key": "staff",
         }), \
         patch("src.ai.routers.auth._seat_limit", return_value=5), \
         patch("src.ai.routers.auth._session", side_effect=lambda tenant_id, user_id, role_key, *args, **kwargs: {
             "user_id": user_id, "role_key": role_key,
         }):
        response = client.post("/auth/invitations/good-token/accept", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "00000000-0000-4000-8000-000000000002"
    assert body["role_key"] == "staff"
    assert conn.commit.call_count == 1


def test_accept_invitation_creates_an_account_when_none_exists():
    conn = _fake_conn()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ({
        "user_id": "00000000-0000-4000-8000-000000000003",
        "email": "brandnew@example.com",
        "full_name": "Brand New",
        "business_name": "Shop",
        "role_key": "staff",
        "preferred_language": "en",
    },)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={
             "token_id": "tok1", "email": "brandnew@example.com", "tenant_id": "t1", "role_key": "staff",
         }), \
         patch("src.ai.routers.auth._seat_limit", return_value=5), \
         patch("src.ai.routers.auth._session", side_effect=lambda tenant_id, user_id, role_key, *args, **kwargs: {
             "user_id": user_id, "role_key": role_key,
             "full_name": "Brand New",
         }):
        response = client.post(
            "/auth/invitations/good-token/accept",
            json={"full_name": "Brand New", "password": "Str0ng!Passw0rd"},
        )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Brand New"
    conn.commit.assert_called_once()



# --- Brute-force protection (codes bound to the account, attempt limits) ---

def test_a_valid_code_for_another_account_is_rejected(monkeypatch):
    """The code is looked up by hash; it must also belong to the email
    submitted - otherwise any guess that hits ANY account's outstanding
    code would reset that account's password."""
    from src.ai.core import auth_throttle

    monkeypatch.setattr(auth_throttle, "ensure_allowed", lambda *a: None)
    monkeypatch.setattr(auth_throttle, "record_failure", lambda *a: False)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_code", return_value=None) as fetch_code, \
         patch("src.ai.routers.auth._consume_token") as mock_consume:
        response = client.post(
            "/auth/password/reset", json={"email": "eve@example.com", "code": "123456", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 400
    assert fetch_code.call_args.args[1:] == ("PASSWORD_RESET", "eve@example.com", "123456")
    mock_consume.assert_not_called()


def test_too_many_wrong_codes_cancels_outstanding_codes_and_blocks_further_guesses(monkeypatch):
    from src.ai.core import auth_throttle
    from fastapi import HTTPException

    attempts = 0

    def record_failure(*_args):
        nonlocal attempts
        attempts += 1
        return attempts >= auth_throttle.CODE_MAX_FAILURES

    def ensure_allowed(scope, _email):
        if scope == "code" and attempts >= auth_throttle.CODE_MAX_FAILURES:
            raise HTTPException(429, "Too many incorrect codes.")

    monkeypatch.setattr(auth_throttle, "ensure_allowed", ensure_allowed)
    monkeypatch.setattr(auth_throttle, "record_failure", record_failure)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._fetch_active_code", return_value=None), \
         patch("src.ai.routers.auth._cancel_active_codes") as mock_cancel:
        statuses = [
            client.post("/auth/password/verify-code", json={"email": "jane@example.com", "code": f"{i:06d}"}).status_code
            for i in range(auth_throttle.CODE_MAX_FAILURES + 2)
        ]
    assert statuses[: auth_throttle.CODE_MAX_FAILURES - 1] == [400] * (auth_throttle.CODE_MAX_FAILURES - 1)
    assert statuses[auth_throttle.CODE_MAX_FAILURES - 1:] == [429] * 3
    mock_cancel.assert_called_once()


def test_requesting_a_new_code_clears_the_wrong_code_count_but_is_itself_limited(monkeypatch):
    from src.ai.core import auth_throttle

    store = _CounterStore()
    monkeypatch.setattr(auth_throttle, "_redis", lambda: store)

    def send_code(_conn, email, *_args):
        auth_throttle.reset("code", email)
        return "123456"

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._send_account_code", side_effect=send_code), \
         patch("src.ai.routers.auth.notifications.send_password_reset_email"):
        auth_throttle.record_failure("code", "jane@example.com")
        assert client.post("/auth/password/forgot", json={"email": "jane@example.com"}).status_code == 200
        assert auth_throttle._redis().get(auth_throttle._key("code", "jane@example.com")) is None
        statuses = [client.post("/auth/password/forgot", json={"email": "Jane@Example.com "}).status_code
                    for _ in range(auth_throttle.CODE_SENDS_PER_WINDOW)]
    assert statuses[-1] == 429 and statuses[:-1] == [200] * (auth_throttle.CODE_SENDS_PER_WINDOW - 1)


def test_login_is_throttled_per_email_after_repeated_wrong_passwords_and_a_429_reveals_nothing(monkeypatch):
    from src.ai.core import auth_throttle

    store = _CounterStore()
    monkeypatch.setattr(auth_throttle, "_redis", lambda: store)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=None):
        statuses = [client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"}).status_code
                    for _ in range(auth_throttle.LOGIN_MAX_FAILURES + 1)]
        other = client.post("/auth/login", json={"email": "someone-else@example.com", "password": "x"}).status_code
    assert statuses[:-1] == [401] * auth_throttle.LOGIN_MAX_FAILURES and statuses[-1] == 429
    assert other == 401  # per email, not global


def test_auth_throttle_fails_open_when_redis_is_unavailable(monkeypatch):
    from src.ai.core import auth_throttle

    def _down():
        raise ConnectionError("redis down")
    monkeypatch.setattr(auth_throttle, "_redis", _down)
    auth_throttle.ensure_allowed("login", "a@example.com")
    assert auth_throttle.record_failure("login", "a@example.com") is False
