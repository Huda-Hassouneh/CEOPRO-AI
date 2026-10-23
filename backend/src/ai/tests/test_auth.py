"""
Unit tests for POST /auth/login (routers/auth.py) - offline, same
convention as test_main.py (DB calls mocked, real password/JWT logic
exercised for real).
"""
import os
from unittest.mock import MagicMock, patch

import jwt
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.core.security import hash_password  # noqa: E402
from src.ai.main import app  # noqa: E402

client = TestClient(app)
# See test_main.py's identical comment - only needed for the one test
# below that verifies the global exception handler's real behavior.
error_client = TestClient(app, raise_server_exceptions=False)
_SECRET = os.environ["JWT_SECRET"]

_REAL_HASH = hash_password("correct horse battery staple")


def _fake_conn():
    conn = MagicMock()
    conn.close = MagicMock()
    return conn


def test_login_rejects_missing_fields():
    response = client.post("/auth/login", json={"email": "a@b.com"})
    assert response.status_code == 422


def test_login_rejects_unknown_email():
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=None):
        response = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_login_rejects_wrong_password():
    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row):
        response = client.post("/auth/login", json={"email": "jane@example.com", "password": "wrong-password"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_login_never_reveals_whether_the_email_existed():
    """Same message for 'no such account' and 'wrong password' - never
    lets a caller distinguish the two (account enumeration)."""
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=None):
        unknown_email = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})

    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row):
        wrong_password = client.post("/auth/login", json={"email": "jane@example.com", "password": "wrong"})

    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json() == wrong_password.json()


def test_login_rejects_account_with_no_workspace():
    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=[]):
        response = client.post(
            "/auth/login", json={"email": "jane@example.com", "password": "correct horse battery staple"},
        )

    assert response.status_code == 403
    assert "not associated with any active workspace" in response.json()["detail"]


def test_login_issues_a_real_working_token_for_a_single_workspace_account():
    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    memberships = [("t1", "owner", "Jane's Shop")]
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=memberships):
        response = client.post(
            "/auth/login", json={"email": "jane@example.com", "password": "correct horse battery staple"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["tenant_id"] == "t1"
    assert body["user_id"] == "u1"
    assert body["role_key"] == "owner"
    assert body["business_name"] == "Jane's Shop"
    assert body["expires_in"] > 0

    # The issued token must actually decode with the same claim shape
    # every other endpoint's get_tenant_context() already requires - real
    # end-to-end proof, not just a response-shape assertion.
    claims = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
    assert claims["tenant_id"] == "t1"
    assert claims["user_id"] == "u1"
    assert "exp" in claims


def test_login_requires_tenant_id_for_a_multi_workspace_account():
    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    memberships = [("t1", "owner", "Jane's Shop"), ("t2", "staff", "Side Hustle Co")]
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=memberships):
        response = client.post(
            "/auth/login", json={"email": "jane@example.com", "password": "correct horse battery staple"},
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert len(detail["workspaces"]) == 2
    assert {"tenant_id": "t1", "role_key": "owner", "business_name": "Jane's Shop"} in detail["workspaces"]


def test_login_accepts_an_explicit_tenant_id_for_a_multi_workspace_account():
    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    memberships = [("t1", "owner", "Jane's Shop"), ("t2", "staff", "Side Hustle Co")]
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=memberships):
        response = client.post(
            "/auth/login",
            json={"email": "jane@example.com", "password": "correct horse battery staple", "tenant_id": "t2"},
        )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "t2"
    assert response.json()["role_key"] == "staff"


def test_login_rejects_a_tenant_id_the_account_does_not_belong_to():
    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    memberships = [("t1", "owner", "Jane's Shop")]
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=memberships):
        response = client.post(
            "/auth/login",
            json={"email": "jane@example.com", "password": "correct horse battery staple", "tenant_id": "not-theirs"},
        )

    assert response.status_code == 403


def test_login_rejects_a_malformed_legacy_hash_as_wrong_password_not_a_500():
    """seed_demo_data.py's literal 'seed_data_placeholder_hash' isn't a
    real bcrypt hash - must fail closed as a login failure, never surface
    a 500 for what is, from the caller's perspective, a login attempt
    that didn't succeed."""
    user_row = ("u1", "seed_data_placeholder_hash", "Demo User", "en", 0)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row):
        response = client.post("/auth/login", json={"email": "demo@example.com", "password": "anything"})

    assert response.status_code == 401


def test_login_closes_the_connection_even_on_failure():
    """An unexpected failure still returns the service's generic,
    consistent 500 shape (core/exceptions.py's global handler) - and the
    connection is still closed via login()'s own finally, not left open."""
    conn = _fake_conn()
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=conn), \
         patch("src.ai.routers.auth._fetch_login_identity", side_effect=RuntimeError("db exploded")):
        response = error_client.post("/auth/login", json={"email": "jane@example.com", "password": "x"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    conn.close.assert_called_once()


# --- Session renewal (POST /auth/refresh) -------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from src.ai.core import security  # noqa: E402


_TENANT_ID = "00000000-0000-4000-8000-000000000001"
_USER_ID = "00000000-0000-4000-8000-000000000002"


def _token_with(auth_time_offset_hours=0, exp_minutes=60, **extra):
    now = datetime.now(timezone.utc)
    claims = {"tenant_id": _TENANT_ID, "user_id": _USER_ID, "exp": now + timedelta(minutes=exp_minutes), "jti": "old-jti",
              "auth_time": int((now - timedelta(hours=auth_time_offset_hours)).timestamp())}
    claims.update(extra)
    return jwt.encode(claims, _SECRET, algorithm="HS256")


def _refresh(token, memberships=((_TENANT_ID, "owner", "Shop"),), revoked=False):
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=list(memberships)), \
         patch("src.ai.routers.auth._email_verified", return_value=True), \
         patch("src.ai.routers.auth._credential_version", return_value=0), \
         patch("src.ai.core.security.assert_active_principal"), \
         patch("src.ai.core.security.is_token_revoked", return_value=revoked):
        return client.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})


def test_refresh_requires_a_token():
    assert client.post("/auth/refresh").status_code == 401


def test_refresh_issues_a_new_token_that_keeps_the_sign_in_time():
    old = _token_with(auth_time_offset_hours=3)
    response = _refresh(old)
    assert response.status_code == 200
    body = response.json()
    new_claims = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
    old_claims = jwt.decode(old, _SECRET, algorithms=["HS256"])
    assert new_claims["tenant_id"] == _TENANT_ID and new_claims["user_id"] == _USER_ID
    assert new_claims["auth_time"] == old_claims["auth_time"]
    assert new_claims["jti"] != "old-jti"
    assert new_claims["exp"] > old_claims["exp"]
    assert body["expires_in"] == security.JWT_EXPIRE_MINUTES * 60


def test_refresh_is_refused_once_the_sign_in_is_too_old():
    response = _refresh(_token_with(auth_time_offset_hours=security.SESSION_MAX_HOURS + 1))
    assert response.status_code == 401


def test_refresh_is_refused_for_someone_removed_from_the_company():
    response = _refresh(
        _token_with(),
        memberships=[("00000000-0000-4000-8000-000000000003", "owner", "Elsewhere")],
    )
    assert response.status_code == 401


def test_refresh_is_refused_for_an_expired_or_signed_out_token():
    assert _refresh(_token_with(exp_minutes=-1)).status_code == 401
    assert _refresh(_token_with(), revoked=True).status_code == 401


def test_tokens_from_before_auth_time_existed_count_from_when_they_were_issued():
    now = datetime.now(timezone.utc)
    legacy = jwt.encode({"tenant_id": _TENANT_ID, "user_id": _USER_ID, "exp": now + timedelta(minutes=30), "jti": "x"},
                        _SECRET, algorithm="HS256")
    response = _refresh(legacy)
    assert response.status_code == 200
    issued = jwt.decode(response.json()["access_token"], _SECRET, algorithms=["HS256"])["auth_time"]
    assert abs(issued - (now.timestamp() + 30 * 60 - security.JWT_EXPIRE_MINUTES * 60)) < 5


def test_login_tokens_carry_their_sign_in_time():
    user_row = ("u1", _REAL_HASH, "Jane Doe", "en", 0)
    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.auth._fetch_login_identity", return_value=user_row), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=[("t1", "owner", "Shop")]):
        body = client.post("/auth/login", json={"email": "jane@example.com", "password": "correct horse battery staple"}).json()
    claims = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
    assert abs(claims["auth_time"] - datetime.now(timezone.utc).timestamp()) < 5
