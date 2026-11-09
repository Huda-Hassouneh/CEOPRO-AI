"""
Zero-downtime JWT_SECRET rotation (core/jwt_keys.py, docs/SECURITY_CREDENTIAL_ROTATION.md).

During the overlap JWT_SECRET is the new key and JWT_SECRET_PREVIOUS the old one:
tokens signed with the old key keep working until they expire but are never renewed, nothing is ever
signed with the old key, and a token signed with any other key is refused. The
exp requirement, sign-out revocation and credential_version checks are the same
for both keys. Offline: conftest.py fakes Redis and the principal lookup.
"""
import os
import re
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.core import config_check, jwt_keys, security  # noqa: E402
from src.ai.core.rate_limit import RateLimitMiddleware  # noqa: E402

CURRENT = os.environ["JWT_SECRET"]  # what security.py signs with (read at import)
PREVIOUS = "the-old-jwt-secret-being-rotated-out-0123456789abcdef"
OTHER = "an-attacker-chosen-key-that-was-never-configured-0123456789"
TENANT = "22222222-2222-2222-2222-222222222222"
USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def overlap(monkeypatch):
    """The state after the rotation deploy: new key current, old key previous."""
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", PREVIOUS)
    monkeypatch.setattr(security, "_JWT_VERIFICATION_KEYS", jwt_keys.verification_keys())
    assert security._JWT_VERIFICATION_KEYS == (CURRENT, PREVIOUS)


def _token(key, exp_in=600, **extra):
    now = int(time.time())
    claims = {"tenant_id": TENANT, "user_id": USER, "exp": now + (exp_in or 0), "iat": now, "auth_time": now,
              "jti": "jti-" + str(time.time_ns()), "cv": 0, "ev": True, **extra}
    if exp_in is None:
        claims.pop("exp")
    return jwt.encode(claims, key, algorithm="HS256")


def _authorize(token):
    return security.get_tenant_context(authorization=f"Bearer {token}")


def _refused(token, status=401):
    with pytest.raises(HTTPException) as refused:
        _authorize(token)
    assert refused.value.status_code == status
    return refused.value


# --- which keys are accepted --------------------------------------------------------------------

def test_without_a_previous_key_only_the_current_key_is_accepted(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    monkeypatch.setattr(security, "_JWT_VERIFICATION_KEYS", jwt_keys.verification_keys())
    assert security._JWT_VERIFICATION_KEYS == (CURRENT,)
    assert _authorize(_token(CURRENT)).user_id == USER
    _refused(_token(PREVIOUS))


def test_a_token_signed_with_the_previous_key_stays_valid_during_the_overlap(overlap):
    ctx = _authorize(_token(PREVIOUS))
    assert (ctx.tenant_id, ctx.user_id) == (TENANT, USER)
    assert _authorize(_token(CURRENT)).user_id == USER


@pytest.mark.parametrize("key", [OTHER, CURRENT + "x", PREVIOUS[:-1], " " + PREVIOUS])
def test_a_token_signed_with_any_other_key_is_refused(overlap, key):
    token = jwt.encode({"tenant_id": TENANT, "user_id": USER, "exp": int(time.time()) + 600}, key, algorithm="HS256")
    _refused(token)


def test_an_unsigned_or_other_algorithm_token_is_refused(overlap):
    unsigned = jwt.encode({"tenant_id": TENANT, "user_id": USER, "exp": int(time.time()) + 600}, None, algorithm="none")
    _refused(unsigned)
    hs512 = jwt.encode({"tenant_id": TENANT, "user_id": USER, "exp": int(time.time()) + 600}, PREVIOUS, algorithm="HS512")
    _refused(hs512)


def test_a_blank_or_repeated_previous_key_adds_nothing(monkeypatch):
    for value in ("", "   ", CURRENT):
        monkeypatch.setenv("JWT_SECRET_PREVIOUS", value)
        assert jwt_keys.verification_keys() == (CURRENT,)


# --- the existing checks apply to old-key tokens unchanged -------------------------------------

def test_an_expired_old_key_token_is_refused(overlap):
    _refused(_token(PREVIOUS, exp_in=-5))


def test_an_old_key_token_without_exp_is_refused(overlap):
    _refused(_token(PREVIOUS, exp_in=None))
    _refused(_token(CURRENT, exp_in=None))


def test_a_signed_out_old_key_token_is_refused(overlap):
    token = _token(PREVIOUS)
    ctx = _authorize(token)
    assert security.revoke_token(ctx.token_id, ctx.token_expires_at) is True
    _refused(token)


def test_an_old_key_token_from_before_a_password_change_is_refused(overlap):
    token = _token(PREVIOUS, auth_time=int(time.time()) - 100)
    _authorize(token)
    security.invalidate_sessions(USER)
    _refused(token)


def test_credential_version_is_still_checked_for_old_key_tokens(overlap, monkeypatch):
    seen = []
    monkeypatch.setattr(security, "assert_active_principal", lambda tenant, user, cv: seen.append(cv))
    _authorize(_token(PREVIOUS, cv=3))
    assert seen == [3]
    _refused(_token(PREVIOUS, cv=-1))
    _refused(_token(PREVIOUS, cv="0"))


def test_the_worker_identity_is_refused_with_the_old_key_too(overlap):
    _refused(_token(PREVIOUS, user_id=security.SERVICE_ACTOR_USER_ID))


# --- nothing is signed with the previous key ----------------------------------------------------

def test_new_tokens_are_signed_only_with_the_current_key(overlap):
    token, _ = security.create_access_token(TENANT, USER, email_verified=True)
    assert jwt.decode(token, CURRENT, algorithms=["HS256"])["user_id"] == USER
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, PREVIOUS, algorithms=["HS256"])


def _refresh(token):
    from src.ai.main import app

    with patch("src.ai.routers.auth.db.auth_lookup_connection", return_value=MagicMock()), \
         patch("src.ai.routers.auth._fetch_user_memberships", return_value=[(TENANT, "owner", "Shop")]), \
         patch("src.ai.routers.auth._email_verified", return_value=True), \
         patch("src.ai.routers.auth._credential_version", return_value=0):
        return TestClient(app).post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})


def test_an_old_key_session_is_never_renewed(overlap):
    """An old-key token works until it expires but is never re-signed with the new key."""
    old = _token(PREVIOUS, auth_time=int(time.time()) - 3600)
    assert _authorize(old).signed_with_current_key is False
    assert _refresh(old).status_code == 401


def test_a_current_key_session_still_renews_during_the_overlap(overlap):
    current = _token(CURRENT, auth_time=int(time.time()) - 3600)
    assert _authorize(current).signed_with_current_key is True
    response = _refresh(current)
    assert response.status_code == 200, response.text
    renewed = response.json()["access_token"]
    assert jwt.decode(renewed, CURRENT, algorithms=["HS256"])["auth_time"] == jwt.decode(current, CURRENT, algorithms=["HS256"])["auth_time"]
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(renewed, PREVIOUS, algorithms=["HS256"])


def test_a_token_forged_with_the_old_key_cannot_outlive_the_rotation(overlap, monkeypatch):
    """Review finding on #107: a forged old-key token with a far-future auth_time was renewed into a
    new-key session that kept working after JWT_SECRET_PREVIOUS was removed."""
    forged = _token(PREVIOUS, auth_time=int(time.time()) + 10 * 365 * 86400)
    _refused(forged)
    assert _refresh(forged).status_code == 401
    plausible = _token(PREVIOUS)  # a forger choosing a believable auth_time instead
    assert _refresh(plausible).status_code == 401
    monkeypatch.setattr(security, "_JWT_VERIFICATION_KEYS", (CURRENT,))  # the previous key is removed
    _refused(plausible)


def test_a_sign_in_time_in_the_future_is_refused_for_any_key():
    for offset, accepted in ((-30, True), (30, True), (3600, False)):  # 60 s clock skew allowed
        token = _token(CURRENT, auth_time=int(time.time()) + offset)
        if accepted:
            _authorize(token)
        else:
            _refused(token)
    _refused(_token(CURRENT, auth_time="soon"))
    _refused(_token(CURRENT, iat=int(time.time()) + 3600))  # PyJWT itself refuses a future iat


def test_a_legacy_token_whose_derived_sign_in_time_is_in_the_future_is_refused():
    now = int(time.time())
    far_exp = jwt.encode({"tenant_id": TENANT, "user_id": USER, "exp": now + 365 * 86400, "jti": "x", "ev": True},
                         CURRENT, algorithm="HS256")
    _refused(far_exp)


# Every route that issues a new token from an existing session (second review finding on #107:
# switching to the same workspace laundered an old-key token into a current-key session).
_REISSUE_ROUTES = {
    ("POST", "/auth/refresh"): None,
    ("POST", "/auth/workspaces/switch"): {"tenant_id": TENANT},
    ("POST", "/auth/workspaces"): {"business_name": "Shop", "country_code": "JO", "primary_currency": "JOD"},
    ("POST", "/settings/security/change-password"): {"current_password": "Old-pass1!", "new_password": "New-pass1!"},
}


@pytest.mark.parametrize("method,path", sorted(_REISSUE_ROUTES))
def test_no_route_re_issues_an_old_key_session(overlap, method, path):
    from src.ai.main import app

    old = _token(PREVIOUS)
    with patch("src.ai.db.auth_lookup_connection") as lookup, patch("src.ai.db.app_role_connection") as app_conn:
        response = TestClient(app).request(method, path, json=_REISSUE_ROUTES[(method, path)],
                                           headers={"Authorization": f"Bearer {old}"})
    assert response.status_code == 401, (path, response.text)
    assert "access_token" not in response.text
    assert not lookup.called and not app_conn.called  # refused before the handler ran


def _dependency_calls(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _dependency_calls(sub)


def _api_routes(routes):
    """Every APIRoute, including routers kept nested by newer FastAPI versions."""
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested = getattr(route, "original_router", None) or getattr(route, "router", None)
        if nested is not None and getattr(nested, "routes", None) is not None and nested is not route:
            yield from _api_routes(nested.routes)


def test_every_token_issuing_route_refuses_old_key_sessions():
    """Fails when a route that creates a token from a signed-in session uses get_tenant_context directly."""
    import inspect

    from src.ai.main import app

    issuing, signed_in_routes = set(), 0
    for route in _api_routes(app.routes):
        calls = list(_dependency_calls(route.dependant))
        if security.get_tenant_context not in calls:
            continue  # not a signed-in route (login, signup, codes, invitations)
        signed_in_routes += 1
        source = inspect.getsource(route.endpoint)
        if re.search(r"\bcreate_access_token\(|\b_session\(", source):
            issuing.add(route.endpoint.__name__)
            direct = [sub.call for sub in route.dependant.dependencies]
            assert security.get_tenant_context not in direct, route.path
            assert security.get_current_key_context in direct, route.path
    assert signed_in_routes > 50  # the walk really saw the application's routes
    assert issuing == {"refresh", "switch_workspace", "create_workspace", "change_password"}


def test_only_a_wrong_signature_falls_through_to_the_previous_key():
    expired = jwt.encode({"exp": int(time.time()) - 5}, CURRENT, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt_keys.decode(expired, (CURRENT, PREVIOUS))
    with pytest.raises(jwt.InvalidSignatureError):
        jwt_keys.decode(jwt.encode({"exp": int(time.time()) + 60}, OTHER, algorithm="HS256"), (CURRENT, PREVIOUS))
    with pytest.raises(jwt.InvalidSignatureError):
        jwt_keys.decode(jwt.encode({"exp": int(time.time()) + 60}, OTHER, algorithm="HS256"), ())


# --- the rate limiter counts old-key sessions per company, not per address ----------------------

def test_rate_limiter_recognises_old_key_tokens_during_the_overlap(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", CURRENT)
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", PREVIOUS)
    middleware = RateLimitMiddleware(FastAPI())

    def identity(key):
        auth = ("Bearer " + jwt.encode({"tenant_id": TENANT, "user_id": USER}, key, algorithm="HS256")).encode()
        return middleware._identity({"headers": [(b"authorization", auth)], "client": ("203.0.113.9", 1)})[0]

    assert identity(CURRENT) == f"company:{TENANT}"
    assert identity(PREVIOUS) == f"company:{TENANT}"
    assert identity(OTHER) == "ip:203.0.113.9"


# --- configuration check -------------------------------------------------------------------------

@pytest.fixture
def config_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "n" * 64)
    monkeypatch.delenv("JWT_SECRET_PREVIOUS", raising=False)
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    return monkeypatch


def _jwt_previous_findings():
    return [f for f in config_check.check_environment() if f.setting == "JWT_SECRET_PREVIOUS"]


def test_config_check_is_silent_without_a_previous_key(config_env):
    assert _jwt_previous_findings() == []


def test_config_check_reminds_to_remove_a_valid_previous_key_without_its_value(config_env):
    config_env.setenv("JWT_SECRET_PREVIOUS", PREVIOUS)
    findings = _jwt_previous_findings()
    assert [f.level for f in findings] == [config_check.WARNING]
    assert "SESSION_MAX_HOURS" in findings[0].message or "remove" in findings[0].message
    assert all(PREVIOUS not in f.line() for f in config_check.check_environment())


def test_config_check_flags_a_short_previous_key_as_an_error_where_deployed(config_env):
    config_env.setenv("JWT_SECRET_PREVIOUS", "short")
    assert [f.level for f in _jwt_previous_findings()] == [config_check.WARNING]
    config_env.setenv("SENTRY_ENVIRONMENT", "production")
    assert [f.level for f in _jwt_previous_findings()] == [config_check.ERROR]


def test_config_check_flags_a_previous_key_equal_to_the_current_one(config_env):
    config_env.setenv("JWT_SECRET_PREVIOUS", "n" * 64)
    findings = _jwt_previous_findings()
    assert [f.level for f in findings] == [config_check.WARNING]
    assert "same as JWT_SECRET" in findings[0].message
