"""
Unit tests for the new auth endpoints in routers/auth.py (signup, logout,
password reset, email verification, team invitations) - offline, same
convention as test_auth.py: DB calls mocked (the router's own helper
functions, not raw SQL - matching how test_auth.py already mocks
_fetch_user_by_email/_fetch_user_memberships rather than cursor-level SQL).
"""
import os
from unittest.mock import MagicMock, patch

import jwt
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.core.security import create_access_token, hash_password  # noqa: E402
from src.ai.main import app  # noqa: E402

client = TestClient(app)
_SECRET = os.environ["JWT_SECRET"]


def _fake_conn():
    conn = MagicMock()
    conn.close = MagicMock()
    return conn


def _auth_header():
    token, _ = create_access_token(tenant_id="t1", user_id="u1")
    return {"Authorization": f"Bearer {token}"}


# --- signup -----------------------------------------------------------

def test_signup_rejects_an_email_that_already_exists():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("existing-id", "hash", "Jane", "en")):
        response = client.post("/auth/signup", json={
            "email": "jane@example.com", "password": "Str0ng!Passw0rd", "full_name": "Jane",
            "business_name": "Jane's Shop", "country_code": "jo", "primary_currency": "jod",
        })
    assert response.status_code == 409


def test_signup_creates_a_new_tenant_and_returns_a_real_working_token():
    conn = _fake_conn()
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch("src.ai.routers.auth.db.app_role_connection", return_value=conn):
        response = client.post("/auth/signup", json={
            "email": "new@example.com", "password": "Str0ng!Passw0rd",
            "full_name": "New Owner", "business_name": "New Shop",
            "country_code": "jo", "primary_currency": "jod",
        })

    assert response.status_code == 200
    body = response.json()
    assert body["role_key"] == "owner"
    assert body["business_name"] == "New Shop"
    assert body["token_type"] == "bearer"

    claims = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
    assert claims["tenant_id"] == body["tenant_id"]
    assert claims["user_id"] == body["user_id"]
    conn.commit.assert_called_once()


def test_signup_uppercases_country_code_and_currency():
    conn = _fake_conn()
    captured = {}

    def _capture_execute(query, params=None):
        if "INSERT INTO companies" in query:
            captured["params"] = params

    conn.cursor.return_value.__enter__.return_value.execute.side_effect = _capture_execute

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch("src.ai.routers.auth.db.app_role_connection", return_value=conn):
        client.post("/auth/signup", json={
            "email": "new2@example.com", "password": "Str0ng!Passw0rd", "full_name": "Owner",
            "business_name": "Shop", "country_code": "jo", "primary_currency": "jod",
        })

    assert captured["params"][2] == "JO"
    assert captured["params"][3] == "JOD"


def test_signup_returns_409_on_a_real_concurrent_duplicate_race(monkeypatch):
    import psycopg2
    conn = _fake_conn()
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = psycopg2.errors.UniqueViolation("dup")

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch("src.ai.routers.auth.db.app_role_connection", return_value=conn):
        response = client.post("/auth/signup", json={
            "email": "race@example.com", "password": "Str0ng!Passw0rd", "full_name": "Owner",
            "business_name": "Shop", "country_code": "jo", "primary_currency": "jod",
        })

    assert response.status_code == 409
    conn.rollback.assert_called_once()


# --- logout -------------------------------------------------------------

def test_logout_requires_auth():
    assert client.post("/auth/logout").status_code == 401


def test_logout_returns_ok_for_a_real_authenticated_caller():
    response = client.post("/auth/logout", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {"ok": True, "revoked": True}


# --- password reset -------------------------------------------------------

def test_forgot_password_creates_a_token_for_a_real_email():
    calls = []
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._create_token", side_effect=lambda *a, **k: calls.append((a, k))), \
         patch("src.ai.routers.auth.notifications.send_password_reset_email") as mock_send:
        response = client.post("/auth/password/forgot", json={"email": "jane@example.com"})

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0][1] == "PASSWORD_RESET"
    mock_send.assert_called_once()


def test_forgot_password_never_reveals_whether_the_email_exists():
    """Same generic response, and no token/email attempt at all, for an
    unregistered email - never lets a caller distinguish the two."""
    calls = []
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch("src.ai.routers.auth._create_token", side_effect=lambda *a, **k: calls.append(1)):
        known = client.post("/auth/password/forgot", json={"email": "unknown@example.com"})

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._create_token", side_effect=lambda *a, **k: None), \
         patch("src.ai.routers.auth.notifications.send_password_reset_email"):
        registered = client.post("/auth/password/forgot", json={"email": "jane@example.com"})

    assert known.json() == registered.json()
    assert calls == []


def test_verify_reset_code_rejects_an_invalid_code():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_token", return_value=None):
        response = client.post("/auth/password/verify-code", json={"email": "jane@example.com", "code": "000000"})
    assert response.status_code == 400


def test_verify_reset_code_accepts_a_real_valid_code():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={"token_id": "t1", "user_id": "u1"}):
        response = client.post("/auth/password/verify-code", json={"email": "jane@example.com", "code": "123456"})
    assert response.status_code == 200
    assert response.json() == {"valid": True}


def test_reset_password_updates_the_password_and_consumes_the_token():
    conn = _fake_conn()
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={"token_id": "t1", "user_id": "u1"}), \
         patch("src.ai.routers.auth._consume_token") as mock_consume:
        response = client.post(
            "/auth/password/reset",
            json={"email": "jane@example.com", "code": "123456", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 200
    mock_consume.assert_called_once_with(conn, "t1")
    conn.commit.assert_called_once()


def test_reset_password_rejects_an_expired_or_invalid_code():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_token", return_value=None):
        response = client.post(
            "/auth/password/reset", json={"email": "jane@example.com", "code": "000000", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 400


# --- email verification ----------------------------------------------------

def test_verify_email_marks_verified_and_consumes_the_token():
    conn = _fake_conn()
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={"token_id": "t1", "user_id": "u1"}), \
         patch("src.ai.routers.auth._consume_token") as mock_consume:
        response = client.post("/auth/email/verify", json={"email": "jane@example.com", "code": "123456"})
    assert response.status_code == 200
    assert response.json()["email_verified"] is True
    mock_consume.assert_called_once()


def test_resend_verification_never_reveals_whether_the_email_exists():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None):
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
         }), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None):
        response = client.get("/auth/invitations/good-token")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "invitee@example.com"
    assert body["business_name"] == "Jane's Shop"
    assert body["role_name"] == "Staff Member"
    assert body["account_exists"] is False


def test_accept_invitation_requires_full_name_and_password_for_a_brand_new_user():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={
             "token_id": "tok1", "email": "new@example.com", "tenant_id": "t1", "role_key": "staff",
         }), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None):
        response = client.post("/auth/invitations/good-token/accept", json={})
    assert response.status_code == 400


def test_accept_invitation_joins_an_existing_user_only_with_their_password():
    conn = _fake_conn()
    from src.ai.core.security import hash_password
    stored_hash = hash_password("Str0ng!Passw0rd")
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={
             "token_id": "tok1", "email": "existing@example.com", "tenant_id": "t1", "role_key": "staff",
         }), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", stored_hash, "Existing User", "en")), \
         patch("src.ai.routers.auth.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.auth._seat_limit", return_value=5), \
         patch("src.ai.routers.auth._consume_token") as mock_consume:
        no_password = client.post("/auth/invitations/good-token/accept", json={})
        wrong_password = client.post("/auth/invitations/good-token/accept", json={"password": "Wrong!Passw0rd1"})
        mock_consume.assert_not_called()  # the link alone, or a wrong password, joins nobody
        response = client.post("/auth/invitations/good-token/accept", json={"password": "Str0ng!Passw0rd"})

    assert (no_password.status_code, wrong_password.status_code) == (401, 401)
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "u1"
    assert body["role_key"] == "staff"
    mock_consume.assert_called_once()


def test_accept_invitation_creates_a_real_new_account_when_none_exists():
    conn = _fake_conn()
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={
             "token_id": "tok1", "email": "brandnew@example.com", "tenant_id": "t1", "role_key": "staff",
         }), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None), \
         patch("src.ai.routers.auth.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.auth._seat_limit", return_value=5), \
         patch("src.ai.routers.auth._consume_token"):
        response = client.post(
            "/auth/invitations/good-token/accept",
            json={"full_name": "Brand New", "password": "Str0ng!Passw0rd"},
        )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Brand New"
    conn.commit.assert_called_once()



# --- Brute-force protection (codes bound to the account, attempt limits) ---

def test_a_valid_code_for_another_account_is_rejected():
    """The code is looked up by hash; it must also belong to the email
    submitted - otherwise any guess that hits ANY account's outstanding
    code would reset that account's password."""
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("attacker-id", "hash", "Eve", "en")), \
         patch("src.ai.routers.auth._fetch_active_token", return_value={"token_id": "t1", "user_id": "victim-id"}), \
         patch("src.ai.routers.auth._consume_token") as mock_consume:
        response = client.post(
            "/auth/password/reset", json={"email": "eve@example.com", "code": "123456", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 400
    mock_consume.assert_not_called()


def test_too_many_wrong_codes_cancels_outstanding_codes_and_blocks_further_guesses():
    from src.ai.core import auth_throttle
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._fetch_active_token", return_value=None), \
         patch("src.ai.routers.auth._cancel_active_codes") as mock_cancel:
        statuses = [
            client.post("/auth/password/verify-code", json={"email": "jane@example.com", "code": f"{i:06d}"}).status_code
            for i in range(auth_throttle.CODE_MAX_FAILURES + 2)
        ]
    assert statuses[: auth_throttle.CODE_MAX_FAILURES - 1] == [400] * (auth_throttle.CODE_MAX_FAILURES - 1)
    assert statuses[auth_throttle.CODE_MAX_FAILURES - 1:] == [429] * 3
    mock_cancel.assert_called_once()


def test_requesting_a_new_code_clears_the_wrong_code_count_but_is_itself_limited():
    from src.ai.core import auth_throttle
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=("u1", "hash", "Jane", "en")), \
         patch("src.ai.routers.auth._create_token"), patch("src.ai.routers.auth._cancel_active_codes"), \
         patch("src.ai.routers.auth.notifications.send_password_reset_email"):
        auth_throttle.record_failure("code", "jane@example.com")
        assert client.post("/auth/password/forgot", json={"email": "jane@example.com"}).status_code == 200
        assert auth_throttle._redis().get(auth_throttle._key("code", "jane@example.com")) is None
        statuses = [client.post("/auth/password/forgot", json={"email": "Jane@Example.com "}).status_code
                    for _ in range(auth_throttle.CODE_SENDS_PER_WINDOW)]
    assert statuses[-1] == 429 and statuses[:-1] == [200] * (auth_throttle.CODE_SENDS_PER_WINDOW - 1)


def test_login_is_throttled_per_email_after_repeated_wrong_passwords_and_a_429_reveals_nothing():
    from src.ai.core import auth_throttle
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_by_email", return_value=None):
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
