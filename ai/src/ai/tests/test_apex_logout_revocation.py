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
    assert security.is_token_revoked("abc") is False
    assert security.revoke_token("abc", None) is False
