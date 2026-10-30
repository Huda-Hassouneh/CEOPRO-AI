"""Operator-only service setup: access gate, no key values leaked, test classification, one alert per day."""
import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.core.security import create_access_token  # noqa: E402
from src.ai.main import app  # noqa: E402
from src.market_scraper import provider_setup  # noqa: E402

client = TestClient(app)
SECRET = "sk-super-secret-value"


def _auth():
    token, _ = create_access_token(tenant_id="t1", user_id="u1", email_verified=True)
    return {"Authorization": f"Bearer {token}"}


def _as_user(email, verified=True):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (email, "2026-01-01" if verified else None)
    return patch("src.ai.routers.operator.db.app_role_connection", return_value=conn)


def test_requires_auth():
    assert client.get("/operator/providers").status_code == 401


def test_non_operator_gets_404_and_me_is_false(monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "ops@example.com")
    with _as_user("jane@example.com"):
        assert client.get("/operator/providers", headers=_auth()).status_code == 404
        assert client.post("/operator/providers/youtube/test", headers=_auth()).status_code == 404
        assert client.get("/operator/me", headers=_auth()).json() == {"is_operator": False}


def test_unverified_or_unlisted_operator_list_is_closed(monkeypatch):
    monkeypatch.delenv("OPERATOR_EMAILS", raising=False)
    with _as_user("ops@example.com"):
        assert client.get("/operator/me", headers=_auth()).json() == {"is_operator": False}
    monkeypatch.setenv("OPERATOR_EMAILS", "ops@example.com")
    with _as_user("ops@example.com", verified=False):
        assert client.get("/operator/me", headers=_auth()).json() == {"is_operator": False}


def test_operator_sees_status_without_any_key_value(monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "OPS@example.com")
    monkeypatch.setenv("YOUTUBE_API_KEY", SECRET)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    with _as_user("ops@example.com"), patch.object(provider_setup, "_redis", side_effect=RuntimeError):
        response = client.get("/operator/providers", headers=_auth())
    assert response.status_code == 200
    assert SECRET not in response.text
    rows = {r["provider"]: r for r in response.json()["providers"]}
    assert rows["youtube"]["configured"] is True and rows["youtube"]["env"] == ["YOUTUBE_API_KEY"]
    assert rows["google_places"]["configured"] is False


def test_connection_test_classifies_and_never_echoes(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", SECRET)
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    redis = MagicMock()
    redis.set.return_value = True
    with patch.object(provider_setup, "_redis", return_value=redis):
        assert provider_setup.test_connection("apify") == "not_configured"
        for status, expected in ((200, "valid"), (400, "rejected"), (500, "error")):
            response = MagicMock(status_code=status)
            response.json.return_value = {}
            with patch.object(provider_setup.httpx, "get", return_value=response):
                assert provider_setup.test_connection("youtube") == expected
        quota = MagicMock(status_code=403)
        quota.json.return_value = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
        with patch.object(provider_setup.httpx, "get", return_value=quota):
            assert provider_setup.test_connection("youtube") == "quota_exhausted"
        with patch.object(provider_setup.httpx, "get", side_effect=RuntimeError(SECRET)):
            assert provider_setup.test_connection("youtube") == "error"


def test_alert_is_sent_once_per_problem(monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "ops@example.com")
    redis = MagicMock()
    redis.set.side_effect = [True, False]
    with patch.object(provider_setup, "_redis", return_value=redis), patch("src.ai.core.notifications.send_email") as send:
        provider_setup.report_problem("youtube", "CREDENTIALS_REJECTED")
        provider_setup.report_problem("youtube", "CREDENTIALS_REJECTED")
        provider_setup.report_problem("youtube", "PROVIDER_ERROR")
        provider_setup.report_problem("unknown", "QUOTA_EXHAUSTED")
    assert send.call_count == 1
    assert SECRET not in str(send.call_args)


def test_alert_never_raises_without_redis():
    with patch.object(provider_setup, "_redis", side_effect=RuntimeError):
        provider_setup.report_problem("youtube", "QUOTA_EXHAUSTED")
