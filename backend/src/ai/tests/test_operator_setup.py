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


def _response(status, body=None):
    response = MagicMock(status_code=status)
    response.json.return_value = body or {}
    return response


def test_a_restricted_apify_token_is_valid_and_a_bad_one_is_rejected():
    ok_list = _response(200, {"data": {"total": 3}})
    evidence = {}
    with patch.object(provider_setup.httpx, "get", side_effect=[_response(403), ok_list]):
        assert provider_setup._test_apify(SECRET, evidence) == "valid_restricted"  # noqa: SLF001
    assert evidence == {"account_http": 403, "actor_list_http": 200, "actors_total": 3}
    with patch.object(provider_setup.httpx, "get", side_effect=[_response(403), _response(401)]):
        assert provider_setup._test_apify(SECRET) == "rejected"  # noqa: SLF001
    with patch.object(provider_setup.httpx, "get", return_value=_response(401)):
        assert provider_setup._test_apify(SECRET) == "rejected"  # noqa: SLF001


def test_groq_checks_the_key_the_model_and_a_real_reply(monkeypatch):
    from src.ai.rag import llm_client

    models = _response(200, {"data": [{"id": llm_client.MODEL_NAME}, {"id": "other"}]})
    reply = _response(200, {"choices": [{"message": {"content": "OK"}}]})
    evidence = {}
    with patch.object(provider_setup.httpx, "get", return_value=models), patch.object(provider_setup.httpx, "post", return_value=reply):
        assert provider_setup._test_groq(SECRET, evidence) == "valid"  # noqa: SLF001
    assert evidence["models"] == 2 and evidence["answer"] == "OK"
    with patch.object(provider_setup.httpx, "get", return_value=_response(200, {"data": [{"id": "other"}]})):
        assert provider_setup._test_groq(SECRET) == "model_unavailable"  # noqa: SLF001
    with patch.object(provider_setup.httpx, "get", return_value=_response(401)):
        assert provider_setup._test_groq(SECRET) == "rejected"  # noqa: SLF001
    with patch.object(provider_setup.httpx, "get", return_value=models), patch.object(provider_setup.httpx, "post", return_value=_response(429)):
        assert provider_setup._test_groq(SECRET) == "quota_exhausted"  # noqa: SLF001


def test_tavily_runs_a_real_search_and_names_its_quota_codes():
    found = _response(200, {"results": [{"url": "https://www.example.jo/menu"}]})
    evidence = {}
    with patch.object(provider_setup.httpx, "post", return_value=found):
        assert provider_setup._test_tavily(SECRET, evidence) == "valid"  # noqa: SLF001
    assert evidence == {"search_http": 200, "results": 1, "first_source": "www.example.jo"}
    for status, expected in ((401, "rejected"), (432, "quota_exhausted"), (433, "quota_exhausted"), (500, "error")):
        with patch.object(provider_setup.httpx, "post", return_value=_response(status)):
            assert provider_setup._test_tavily(SECRET) == expected  # noqa: SLF001


def test_a_key_pasted_with_spaces_quotes_or_bearer_is_sent_clean(monkeypatch):
    from src.ai.core import env_secret

    for pasted in (f"  {SECRET}\n", f'"{SECRET}"', f"Bearer {SECRET}", f"'Bearer {SECRET} '"):
        monkeypatch.setenv("TAVILY_API_KEY", pasted)
        assert env_secret.secret("TAVILY_API_KEY") == SECRET
        assert env_secret.shape_problem("TAVILY_API_KEY") and SECRET not in env_secret.shape_problem("TAVILY_API_KEY")
    monkeypatch.setenv("TAVILY_API_KEY", "two words")
    assert "inside" in env_secret.shape_problem("TAVILY_API_KEY")
    monkeypatch.setenv("TAVILY_API_KEY", SECRET)
    assert env_secret.shape_problem("TAVILY_API_KEY") is None


def test_the_integration_check_prints_evidence_and_causes_never_a_key(monkeypatch, capsys):
    import httpx

    from scripts import integration_check

    monkeypatch.setenv("GROQ_API_KEY", f" {SECRET} ")
    monkeypatch.setenv("TAVILY_API_KEY", SECRET)
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)

    def groq(key, evidence):
        assert key == SECRET  # spaces removed before the call
        evidence.update(models=12, answer="OK")
        return "valid"

    def tavily(key, evidence):
        raise httpx.ConnectError("proxy said no")

    monkeypatch.setitem(provider_setup._TESTS, "groq", groq)  # noqa: SLF001
    monkeypatch.setitem(provider_setup._TESTS, "tavily", tavily)  # noqa: SLF001
    assert integration_check.main([]) == 1
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "PASS - works" in out and "models=12" in out and "has spaces" in out
    assert "network: ConnectError" in out and "not set in this environment" in out
    assert "1 of 3 checks passed" in out
