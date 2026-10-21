"""
Offline tests for llm_client.py's provider fallback chain (LLM_PROVIDERS):
which failures hand the call to the next provider, which never do, and that
one provider's circuit breaker never fails fast a healthy one. httpx.post is
monkeypatched per provider URL; no real network request is made.
"""
import pytest

from src.ai.billing import credits
from src.ai.rag import llm_client

LOCAL_URL = "http://127.0.0.1:8080/v1/chat/completions"
PAID_URL = "https://paid.example/v1/chat/completions"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(llm_client, "LOCAL_LLM_BASE_URL", None)
    monkeypatch.setattr(llm_client, "PAID_LLM_BASE_URL", None)
    monkeypatch.setattr(llm_client, "PAID_LLM_API_KEY", None)
    monkeypatch.setattr(llm_client, "PAID_LLM_MODEL", None)
    monkeypatch.setattr(llm_client, "HUGGINGFACE_LLM_MODEL", None)
    monkeypatch.setattr(llm_client, "RATE_LIMIT_MAX_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(llm_client, "MAX_RETRIES", 0)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    monkeypatch.delenv("LLM_PROVIDERS", raising=False)
    llm_client._reset_circuit_breaker()
    yield
    llm_client._reset_circuit_breaker()


class _Response:
    def __init__(self, status_code=200, json_body=None, text="", headers=None):
        self.status_code, self._json, self.text, self.headers = status_code, json_body, text, headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


def _ok(content="answer"):
    return _Response(200, {"choices": [{"message": {"content": content}}],
                           "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})


def _routes(monkeypatch, by_url):
    """by_url: url -> response (or exception to raise). Records the call order."""
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        result = by_url[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    return calls


def _messages():
    return [{"role": "user", "content": "hello"}]


def _groq_then_local(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq,local")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm_client, "LOCAL_LLM_BASE_URL", LOCAL_URL)


def test_without_llm_providers_the_chain_is_the_single_active_provider(monkeypatch):
    assert llm_client.provider_chain() == ["groq"]
    monkeypatch.setattr(llm_client, "LOCAL_LLM_BASE_URL", LOCAL_URL)
    assert llm_client.provider_chain() == ["local"]


def test_unknown_names_are_ignored_and_duplicates_dropped(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq, openai ,local,groq")
    assert llm_client.provider_chain() == ["groq", "local"]
    monkeypatch.setenv("LLM_PROVIDERS", "nonsense")
    assert llm_client.provider_chain() == ["groq"]


@pytest.mark.parametrize("groq_response", [
    _Response(401, {"error": {"code": "invalid_api_key"}}, text="Invalid API Key"),
    _Response(403, {"error": "forbidden"}, text="forbidden"),
    _Response(429, {"error": "rate limited"}, text="rate limited", headers={"retry-after": "30"}),
    _Response(503, {"error": "down"}, text="down"),
    _Response(200, {"unexpected": "shape"}, text="{}"),
    _Response(200, None, text="<html>not json</html>"),
])
def test_a_failing_first_provider_hands_over_to_the_next(monkeypatch, groq_response):
    _groq_then_local(monkeypatch)
    calls = _routes(monkeypatch, {llm_client.GROQ_API_URL: groq_response, LOCAL_URL: _ok("from local")})
    answer, usage = llm_client._chat_completion_with_usage(_messages())
    assert answer == "from local"
    assert usage["provider"] == "local"
    assert calls == [llm_client.GROQ_API_URL, LOCAL_URL]


def test_a_network_failure_hands_over_to_the_next(monkeypatch):
    _groq_then_local(monkeypatch)
    _routes(monkeypatch, {llm_client.GROQ_API_URL: llm_client.httpx.ConnectError("no route"), LOCAL_URL: _ok("ok")})
    assert llm_client.chat_completion(_messages()) == "ok"


def test_a_provider_listed_but_not_configured_is_skipped_without_a_request(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq,local")  # no GROQ_API_KEY
    monkeypatch.setattr(llm_client, "LOCAL_LLM_BASE_URL", LOCAL_URL)
    calls = _routes(monkeypatch, {LOCAL_URL: _ok("local")})
    assert llm_client.chat_completion(_messages()) == "local"
    assert calls == [LOCAL_URL]


def test_the_first_healthy_provider_answers_and_the_rest_are_not_called(monkeypatch):
    _groq_then_local(monkeypatch)
    calls = _routes(monkeypatch, {llm_client.GROQ_API_URL: _ok("groq"), LOCAL_URL: _ok("local")})
    answer, usage = llm_client._chat_completion_with_usage(_messages())
    assert (answer, usage["provider"], calls) == ("groq", "groq", [llm_client.GROQ_API_URL])


def test_a_provider_refused_for_its_price_hands_over(monkeypatch):
    _groq_then_local(monkeypatch)
    real = llm_client._call_provider

    def refuse_groq(provider, *args, **kwargs):
        if provider == "groq":
            raise credits.BudgetError("COST_NOT_CONFIGURED", credits.AI, detail="no confirmed price")
        return real(provider, *args, **kwargs)

    monkeypatch.setattr(llm_client, "_call_provider", refuse_groq)
    _routes(monkeypatch, {LOCAL_URL: _ok("local")})
    assert llm_client.chat_completion(_messages()) == "local"


def test_the_companys_own_budget_refusal_never_falls_back(monkeypatch):
    _groq_then_local(monkeypatch)
    called = []

    def out_of_credits(provider, *args, **kwargs):
        called.append(provider)
        raise credits.BudgetError("BUDGET_EXHAUSTED", credits.AI)

    monkeypatch.setattr(llm_client, "_call_provider", out_of_credits)
    with pytest.raises(credits.BudgetError):
        llm_client.chat_completion(_messages())
    assert called == ["groq"]


def test_every_provider_unconfigured_reports_not_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq,local,huggingface,paid")
    _routes(monkeypatch, {})
    with pytest.raises(llm_client.LLMNotConfiguredError):
        llm_client.chat_completion(_messages())
    assert not llm_client.provider_configured()


def test_when_all_fail_a_rate_limit_is_reported_with_its_retry_hint(monkeypatch):
    _groq_then_local(monkeypatch)
    _routes(monkeypatch, {
        llm_client.GROQ_API_URL: _Response(429, {}, text="slow down", headers={"retry-after": "12"}),
        LOCAL_URL: _Response(500, {}, text="crashed"),
    })
    with pytest.raises(llm_client.LLMRateLimitError) as caught:
        llm_client.chat_completion(_messages())
    assert caught.value.retry_after_seconds == 12.0


def test_when_all_fail_the_last_real_error_is_raised(monkeypatch):
    _groq_then_local(monkeypatch)
    _routes(monkeypatch, {llm_client.GROQ_API_URL: _Response(401, {}, text="bad key"),
                          LOCAL_URL: _Response(500, {}, text="crashed")})
    with pytest.raises(llm_client.LLMError, match="500"):
        llm_client.chat_completion(_messages())


def test_paid_is_only_used_when_listed(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq,local")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm_client, "PAID_LLM_BASE_URL", PAID_URL)
    monkeypatch.setattr(llm_client, "PAID_LLM_API_KEY", "paid-key")
    calls = _routes(monkeypatch, {llm_client.GROQ_API_URL: _Response(503, {}, text="down")})
    with pytest.raises(llm_client.LLMError):
        llm_client.chat_completion(_messages())
    assert PAID_URL not in calls


def test_an_open_breaker_on_one_provider_does_not_block_the_next(monkeypatch):
    _groq_then_local(monkeypatch)
    monkeypatch.setattr(llm_client, "CIRCUIT_BREAKER_THRESHOLD", 1)
    calls = _routes(monkeypatch, {llm_client.GROQ_API_URL: _Response(503, {}, text="down"), LOCAL_URL: _ok("local")})
    assert llm_client.chat_completion(_messages()) == "local"
    assert llm_client._circuit_is_open(llm_client.GROQ_API_URL)
    assert not llm_client._circuit_is_open(LOCAL_URL)
    # Groq fails fast now (no request); local still answers.
    calls.clear()
    assert llm_client.chat_completion(_messages()) == "local"
    assert calls == [LOCAL_URL]


def test_huggingface_needs_its_model_and_token_to_count_as_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "huggingface")
    assert not llm_client.provider_configured()
    monkeypatch.setattr(llm_client, "HUGGINGFACE_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf-test")
    assert llm_client.provider_configured()
