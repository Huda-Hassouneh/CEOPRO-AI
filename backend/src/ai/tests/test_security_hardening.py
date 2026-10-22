"""
Regression tests for the 2026-10-21 code security pass (docs/SECURITY_PENTEST.md).
Offline: Redis and the database are faked, the network is stubbed.
"""
import os
import time
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.core import security  # noqa: E402
from src.ai.routers import auth, settings  # noqa: E402
from src.market_scraper import network_security as ns  # noqa: E402


def _token(user_id="11111111-1111-1111-1111-111111111111", auth_time=None, **extra):
    now = int(time.time())
    claims = {"tenant_id": "22222222-2222-2222-2222-222222222222", "user_id": user_id, "exp": now + 600,
              "iat": now, "auth_time": auth_time if auth_time is not None else now, "ev": True, **extra}
    return jwt.encode(claims, os.environ["JWT_SECRET"], algorithm="HS256")


# --- sessions end when the password changes -------------------------------------------------

def test_a_session_from_before_a_password_change_is_refused():
    token = _token(auth_time=int(time.time()) - 100)
    security.get_tenant_context(authorization=f"Bearer {token}")  # fine before the change
    security.invalidate_sessions("11111111-1111-1111-1111-111111111111")
    with pytest.raises(HTTPException) as refused:
        security.get_tenant_context(authorization=f"Bearer {token}")
    assert refused.value.status_code == 401


def test_a_session_started_in_the_same_second_as_the_change_is_still_refused():
    token = _token(auth_time=time.time())  # a stolen session, moments before the reset
    security.invalidate_sessions("11111111-1111-1111-1111-111111111111")
    with pytest.raises(HTTPException) as refused:
        security.get_tenant_context(authorization=f"Bearer {token}")
    assert refused.value.status_code == 401


def test_a_sign_in_after_the_change_still_works():
    security.invalidate_sessions("11111111-1111-1111-1111-111111111111")
    token, _ = security.create_access_token("22222222-2222-2222-2222-222222222222", "11111111-1111-1111-1111-111111111111")
    security.get_tenant_context(authorization=f"Bearer {token}")


def test_another_users_sessions_are_not_affected():
    security.invalidate_sessions("33333333-3333-3333-3333-333333333333")
    security.get_tenant_context(authorization=f"Bearer {_token(auth_time=int(time.time()) - 100)}")


def test_the_worker_identity_can_never_be_a_signed_in_session():
    with pytest.raises(HTTPException) as refused:
        security.get_tenant_context(authorization=f"Bearer {_token(user_id=security.SERVICE_ACTOR_USER_ID)}")
    assert refused.value.status_code == 401


# --- only an owner hands out the owner role --------------------------------------------------

def test_an_admin_cannot_touch_the_owner_role():
    with pytest.raises(HTTPException) as refused:
        settings._require_owner_to_touch_owners("admin", "staff", "owner")
    assert refused.value.status_code == 403
    with pytest.raises(HTTPException):
        settings._require_owner_to_touch_owners("admin", "owner")


def test_an_owner_may_and_an_admin_may_manage_other_roles():
    settings._require_owner_to_touch_owners("owner", "owner", "admin")
    settings._require_owner_to_touch_owners("admin", "staff", "manager")


# --- sign-in timing does not reveal which emails exist ---------------------------------------

def test_an_unknown_email_still_costs_a_password_check(monkeypatch):
    checked = []
    monkeypatch.setattr(auth, "verify_password", lambda plain, hashed: checked.append(hashed) or False)
    monkeypatch.setattr(auth.db, "auth_lookup_connection", lambda: MagicMock())
    monkeypatch.setattr(auth, "_fetch_user_by_email", lambda conn, email: None)
    with pytest.raises(HTTPException) as refused:
        auth.login(auth.LoginRequest(email="nobody@example.com", password="Whatever1!"))
    assert refused.value.status_code == 401
    assert checked and checked[0].startswith("$2")  # a real bcrypt hash was verified against


# --- an invitation link is not a sign-in -----------------------------------------------------

def test_accepting_an_invitation_for_an_existing_account_needs_its_password(monkeypatch):
    invitation = {"token_id": "t", "user_id": None, "email": "member@example.com", "tenant_id": "tenant", "role_key": "staff"}
    monkeypatch.setattr(auth.db, "auth_lookup_connection", lambda: MagicMock())
    monkeypatch.setattr(auth, "_fetch_active_token", lambda conn, kind, raw: invitation)
    monkeypatch.setattr(auth, "_fetch_user_by_email",
                        lambda conn, email: ("user-id", auth.hash_password("Right!Passw0rd"), "Member", "en"))
    for body in (auth.AcceptInvitationRequest(), auth.AcceptInvitationRequest(password="Wrong!Passw0rd1")):
        with pytest.raises(HTTPException) as refused:
            auth.accept_invitation("raw-token", body)
        assert refused.value.status_code == 401


# --- addresses that only look public ---------------------------------------------------------

@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "fd00::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1", "64:ff9b::a9fe:a9fe",
    "2002:7f00:1::", "2002:a00:1::", "2001:0:1::1",
])
def test_addresses_that_reach_internal_networks_are_not_public(address):
    assert ns.is_public_address(address) is False


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808"])
def test_real_public_addresses_are_public(address):
    assert ns.is_public_address(address) is True


def test_a_nat64_name_is_refused_end_to_end(monkeypatch):
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", raising=False)
    resolver = lambda host, port, type=None: [(10, 1, 6, "", ("64:ff9b::7f00:1", port, 0, 0))]
    with pytest.raises(ns.UnsafeTargetError):
        ns.assert_connector_target("https://rebind.example/api", resolver=resolver)


def test_the_connection_goes_to_the_address_that_was_checked(monkeypatch):
    monkeypatch.delenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", raising=False)
    resolver = lambda host, port, type=None: [(2, 1, 6, "", ("93.184.216.34", port))]
    assert ns.pinned_address("https://shop.example/api", resolver=resolver) == "93.184.216.34"


@pytest.mark.parametrize("name", ["Host", "host", "Content-Length", "Transfer-Encoding", "X-Forwarded-For",
                                  "Proxy-Authorization", "Bad Name", "X-Key\r\nInjected: 1", ""])
def test_headers_that_change_the_request_are_refused(name):
    with pytest.raises(ns.UnsafeTargetError):
        ns.validate_header_name(name)


@pytest.mark.parametrize("name", ["Authorization", "X-Api-Key", "X-Auth-Token"])
def test_ordinary_credential_headers_are_allowed(name):
    assert ns.validate_header_name(name) == name


# --- request size limit ----------------------------------------------------------------------

def _limited_app():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from src.ai.core.body_limit import BodySizeLimitMiddleware

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        return {"bytes": len(await request.body())}

    return TestClient(app)


def test_an_oversized_declared_body_is_refused_before_it_is_read(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "1000")
    assert _limited_app().post("/echo", content=b"x" * 5000).status_code == 413


def test_a_body_within_the_limit_passes(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "1000")
    response = _limited_app().post("/echo", content=b"x" * 900)
    assert (response.status_code, response.json()) == (200, {"bytes": 900})


def test_a_chunked_body_cannot_get_around_the_limit(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "1000")
    response = _limited_app().post("/echo", content=(b"x" * 400 for _ in range(10)))
    assert response.status_code == 413


def test_uploads_get_the_larger_limit(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "1000")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", str(1024 * 1024))
    response = _limited_app().post("/echo", content=b"x" * 50_000, headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert response.status_code == 200


# --- roles on the REST API match what the assistant lets each role see -----------------------

def _as_role(monkeypatch, role):
    from src.ai.core import permissions

    monkeypatch.setattr(permissions, "_current_role", lambda ctx: role)
    return permissions


def _request(method):
    return MagicMock(method=method)


def test_a_read_only_role_cannot_change_company_data(monkeypatch):
    permissions = _as_role(monkeypatch, "staff")
    permissions.forbid_read_only_writes(_request("GET"), MagicMock())  # looking is fine
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        with pytest.raises(HTTPException) as refused:
            permissions.forbid_read_only_writes(_request(method), MagicMock())
        assert refused.value.status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin", "manager", "accountant"])
def test_other_roles_can_still_change_company_data(monkeypatch, role):
    permissions = _as_role(monkeypatch, role)
    permissions.forbid_read_only_writes(_request("POST"), MagicMock())


@pytest.mark.parametrize("role,needed,allowed", [
    ("staff", ("sales",), False), ("staff", ("sales", "costs"), False),
    ("accountant", ("sales", "costs"), True), ("accountant", ("competitors",), False),
    ("manager", ("sales", "costs", "competitors"), True), ("owner", ("sales", "costs"), True),
    (None, ("sales",), False), ("viewer", ("sales",), False),
])
def test_data_endpoints_follow_the_role_table(monkeypatch, role, needed, allowed):
    permissions = _as_role(monkeypatch, role)
    dependency = permissions.require_capabilities(*needed).dependency
    if allowed:
        dependency(MagicMock())
    else:
        with pytest.raises(HTTPException) as refused:
            dependency(MagicMock())
        assert refused.value.status_code == 403
