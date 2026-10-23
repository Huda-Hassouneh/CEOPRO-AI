from fastapi.testclient import TestClient

from src.ai.core import security
from src.ai.main import app

client = TestClient(app)


def test_logout_makes_the_token_stop_working_immediately():
    token, _ = security.create_access_token("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/auth/logout", headers=headers).json()["revoked"] is True
    response = client.post("/auth/logout", headers=headers)
    assert response.status_code == 401 and "signed out" in response.json()["detail"]


def test_other_sessions_of_the_same_user_keep_working():
    first, _ = security.create_access_token("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    second, _ = security.create_access_token("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    client.post("/auth/logout", headers={"Authorization": f"Bearer {first}"})
    assert client.post("/auth/logout", headers={"Authorization": f"Bearer {second}"}).status_code == 200


def test_revocation_fails_open_when_the_store_is_unreachable(monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(security, "_revocation_store", broken)
    monkeypatch.setattr(security, "_durable_revocation", lambda *args: False)
    assert security.is_token_revoked("abc") is False
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as error:
        security.revoke_token("abc", None)
    assert error.value.status_code == 503


def test_billing_routes_fail_closed_when_redis_is_down(monkeypatch):
    def boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(security, "_revocation_store", boom)
    monkeypatch.setattr(security, "_durable_revocation", lambda *args: False)
    assert security.is_token_revoked("x") is False
    assert security.is_token_revoked("x", fail_closed=True) is True


def test_only_billing_paths_refuse_a_token_when_the_store_is_down(monkeypatch):
    import types

    import pytest
    from fastapi import HTTPException

    from src.ai.core import security

    def boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(security, "_revocation_store", boom)
    monkeypatch.setattr(security, "_durable_revocation", lambda *args: False)
    monkeypatch.setattr(security, "assert_active_principal", lambda *args: None)
    token, _ = security.create_access_token("t-1", "u-1", email_verified=True)
    header = f"Bearer {token}"

    def request(path):
        return types.SimpleNamespace(url=types.SimpleNamespace(path=path), state=types.SimpleNamespace())

    assert security.get_tenant_context(request("/pricing/comparisons"), header).tenant_id == "t-1"
    with pytest.raises(HTTPException) as err:
        security.get_tenant_context(request("/billing/checkout"), header)
    assert err.value.status_code == 401


def test_durable_revocation_still_rejects_a_session_when_redis_is_down(monkeypatch):
    import types
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(security, "_revocation_store", lambda: (_ for _ in ()).throw(ConnectionError("redis down")))
    monkeypatch.setattr(security, "_durable_revocation", lambda token_id: True)
    monkeypatch.setattr(security, "assert_active_principal", lambda *args: None)
    token, _ = security.create_access_token("tenant", "user", email_verified=True)
    headers = {"Authorization": f"******"}
    request = types.SimpleNamespace(url=types.SimpleNamespace(path="/reports/sales"), state=types.SimpleNamespace())

    with pytest.raises(HTTPException) as error:
        security.get_tenant_context(request, headers["Authorization"])
    assert error.value.status_code == 401
