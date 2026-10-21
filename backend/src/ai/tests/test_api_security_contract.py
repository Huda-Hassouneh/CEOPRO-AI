"""
P0 security-contract tests for src/ai/main.py (see QA_TEST_STRATEGY.md).

Offline: DB access is mocked. These tests guard the single gate every
endpoint relies on - the Bearer JWT -> tenant context - and are written so a
newly added route is covered automatically.
"""
import os
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
import re

from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
_SECRET = os.environ["JWT_SECRET"]

# Routes that are intentionally reachable without a Bearer token: liveness,
# the sign-in / password / e-mail-verification / invitation flows, the signed
# one-use Shopify OAuth callback, and the public plan list. The callback
# authenticates Shopify and binds its result to the initiating user's
# authenticated one-use state. Anything else showing up unauthenticated is a
# defect.
_PUBLIC = {
    ("GET", "/health"),
    ("GET", "/health/ready"),
    ("POST", "/auth/login"),
    ("POST", "/auth/signup"),
    ("POST", "/auth/password/forgot"),
    ("POST", "/auth/password/verify-code"),
    ("POST", "/auth/password/reset"),
    ("POST", "/auth/email/resend-verification"),
    ("POST", "/auth/email/verify"),
    ("GET", "/auth/invitations/{token}"),
    ("POST", "/auth/invitations/{token}/accept"),
    ("GET", "/platform/invitations/{token}"),
    ("POST", "/platform/invitations/{token}/accept"),
    ("GET", "/onboarding/shopify/callback"),
    ("GET", "/billing/plans"),
}

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _all_operations():
    """Every (METHOD, path-template) from the OpenAPI schema. FastAPI includes
    routers lazily, so app.routes cannot be walked; the schema always lists
    every operation, so a newly added route is covered automatically."""
    return sorted(
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method.upper() in _METHODS
    )


def _routes():
    return [op for op in _all_operations() if op not in _PUBLIC]


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def _tok(claims=None, secret=_SECRET, alg="HS256"):
    claims = {"tenant_id": "t1", "user_id": "u1", "ev": True} if claims is None else dict(claims)
    claims.setdefault("exp", int(time.time()) + 3600)  # a token with no expiry is rejected (see test below)
    return jwt.encode(claims, secret, algorithm=alg)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("method,path", sorted(_routes()))
def test_every_non_public_route_rejects_unauthenticated_requests(method, path):
    response = client.request(method, _concrete(path))
    assert response.status_code == 401, f"{method} {path} is reachable without a token"


@pytest.mark.parametrize("method,path", sorted(_routes()))
def test_every_non_public_route_rejects_a_forged_token(method, path):
    response = client.request(method, _concrete(path), headers=_bearer(_tok(secret="x" * 40)))
    assert response.status_code == 401, f"{method} {path} accepted a token signed with the wrong secret"


def test_public_routes_are_exactly_the_documented_set(monkeypatch):
    from fastapi import HTTPException
    from src.ai.platform import service

    def reject_invalid_invitation_token(token, payload=None):
        raise HTTPException(status_code=404, detail="Invitation not found.")

    monkeypatch.setattr(service, "invitation", reject_invalid_invitation_token)
    open_routes = {
        (method, path)
        for method, path in _all_operations()
        if client.request(method, _concrete(path)).status_code != 401
    }
    assert open_routes == _PUBLIC


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "bearer lowercase-scheme"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer a.b.c"},
    ],
)
def test_malformed_authorization_headers_are_401(headers):
    assert client.get("/dashboard/metrics", headers=headers).status_code == 401


def test_expired_token_is_rejected():
    token = _tok({"tenant_id": "t1", "user_id": "u1", "exp": int(time.time()) - 60})
    assert client.get("/dashboard/metrics", headers=_bearer(token)).status_code == 401


def test_token_without_an_expiry_is_rejected():
    token = jwt.encode({"tenant_id": "t1", "user_id": "u1", "ev": True}, _SECRET, algorithm="HS256")
    assert client.get("/dashboard/metrics", headers=_bearer(token)).status_code == 401


def test_alg_none_token_is_rejected():
    token = jwt.encode({"tenant_id": "t1", "user_id": "u1"}, key=None, algorithm="none")
    assert client.get("/dashboard/metrics", headers=_bearer(token)).status_code == 401


def test_other_hmac_algorithm_is_rejected():
    token = _tok(alg="HS512")
    assert client.get("/dashboard/metrics", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"tenant_id": "t1"},
        {"user_id": "u1"},
        {"tenant_id": "", "user_id": "u1"},
        {"tenant_id": "t1", "user_id": ""},
        {"tenant_id": None, "user_id": None},
    ],
)
def test_token_missing_tenant_or_user_claim_is_rejected(claims):
    assert client.get("/dashboard/metrics", headers=_bearer(_tok(claims))).status_code == 401


def test_tenant_comes_only_from_the_token_never_from_request_params():
    """A client must not be able to switch tenant via query string or header."""
    conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=conn) as app_conn, patch(
        "src.ai.routers.dashboard.dashboard_metrics.get_dashboard_metrics", return_value={}
    ):
        response = client.get(
            "/dashboard/metrics?tenant_id=attacker&user_id=attacker",
            headers={**_bearer(_tok({"tenant_id": "victim-safe", "user_id": "u9", "ev": True})), "X-Tenant-Id": "attacker"},
        )
    assert response.status_code == 200
    app_conn.assert_called_once_with("victim-safe", "u9")


def test_connection_is_closed_even_when_the_pipeline_fails():
    conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=conn), patch(
        "src.ai.routers.dashboard.dashboard_metrics.get_dashboard_metrics", side_effect=RuntimeError("boom")
    ):
        response = client.get("/dashboard/metrics", headers=_bearer(_tok()))
    assert response.status_code == 500
    conn.rollback.assert_called()
    conn.close.assert_called_once()


def test_error_response_does_not_leak_internals():
    conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=conn), patch(
        "src.ai.routers.dashboard.dashboard_metrics.get_dashboard_metrics", side_effect=RuntimeError("password=hunter2 host=10.0.0.5")
    ):
        response = client.get("/dashboard/metrics", headers=_bearer(_tok()))
    assert "hunter2" not in response.text and "10.0.0.5" not in response.text
