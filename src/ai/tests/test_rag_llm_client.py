"""
Offline tests for llm_client.py - the HTTP call to Groq is monkeypatched
(httpx.post), so these never make a real network request or need a real
GROQ_API_KEY. No test in this file exercises a real Groq call - there is
no live-gated counterpart (unlike embeddings.py/reranking.py's
AI_TEST_EMBEDDINGS/AI_TEST_RERANKING) since doing that needs a real
account/API key only the user can provision - see the module's own
docstring.
"""

import httpx
import pytest

from src.ai.rag import llm_client
from src.ai.rag.retrieval_types import AssembledContext


@pytest.fixture(autouse=True)
def _isolated_from_local_llm_config(monkeypatch):
    """
    Every test in this file assumes the Groq backend unless it explicitly
    sets up the local one - but LOCAL_LLM_BASE_URL is read into a
    module-level constant at import time (llm_client.py's own
    `LOCAL_LLM_BASE_URL = os.getenv(...)`), so monkeypatching the
    environment variable alone does nothing once the module is already
    imported; the attribute itself has to be patched. Without this, any
    developer machine that happens to have LOCAL_LLM_BASE_URL exported
    (e.g. for local Ollama/llama-server use) silently breaks these tests -
    a real, previously-unisolated test environment leak, not a bug in the
    tests' logic.
    """
    monkeypatch.setattr(llm_client, "LOCAL_LLM_BASE_URL", None)
    monkeypatch.setattr(llm_client, "PAID_LLM_BASE_URL", None)
    monkeypatch.setattr(llm_client, "PAID_LLM_API_KEY", None)
    monkeypatch.setattr(llm_client, "PAID_LLM_MODEL", None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # The circuit breaker is module-level, in-process state - without this,
    # a test earlier in the run that pushes it past CIRCUIT_BREAKER_THRESHOLD
    # consecutive failures would leave it open for every test after it.
    llm_client._reset_circuit_breaker()


def _context(context_text="Sunscreen SPF 50 is our best seller.", query="what is our best seller?"):
    return AssembledContext(query=query, context_text=context_text, sources=[{"source_index": 1, "chunk_id": "c1", "score": 0.9}])


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        return self._json_body


def test_generate_answer_raises_without_an_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(llm_client.LLMError, match="GROQ_API_KEY"):
        llm_client.generate_answer(_context(), api_key=None)


def test_generate_answer_returns_the_model_content_on_success(monkeypatch):
    def fake_post(url, headers, json, timeout):
        assert url == llm_client.GROQ_API_URL
        assert headers["Authorization"] == "Bearer test-key"
        assert json["messages"][1]["content"].startswith("Context:")
        return _FakeResponse(200, {"choices": [{"message": {"content": "Sunscreen SPF 50."}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    answer = llm_client.generate_answer(_context(), api_key="test-key")
    assert answer == "Sunscreen SPF 50."


def test_generate_answer_raises_llm_error_on_non_200(monkeypatch):
    """400 is deliberately not in _RETRYABLE_STATUS_CODES (a malformed
    request stays malformed on retry) - this test stays fast/single-call,
    retry behavior itself is covered separately below."""
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: _FakeResponse(400, text="bad request"))
    with pytest.raises(llm_client.LLMError, match="400"):
        llm_client.generate_answer(_context(), api_key="test-key")


def test_generate_answer_raises_llm_error_on_malformed_response_shape(monkeypatch):
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: _FakeResponse(200, {"unexpected": "shape"}))
    with pytest.raises(llm_client.LLMError, match="Unexpected LLM provider response shape"):
        llm_client.generate_answer(_context(), api_key="test-key")


def test_generate_answer_raises_llm_error_on_network_failure_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda *a: None)  # no real delay in the test suite
    calls = []

    def raise_network_error(*a, **k):
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(llm_client.httpx, "post", raise_network_error)
    with pytest.raises(llm_client.LLMError, match="LLM provider request failed"):
        llm_client.generate_answer(_context(), api_key="test-key")
    assert len(calls) == llm_client.MAX_RETRIES + 1  # every retry was actually attempted, not skipped


def test_generate_answer_retries_a_5xx_and_succeeds_on_a_later_attempt(monkeypatch):
    """The behavior the retry logic exists for: a transient failure that
    would have been a hard error before now succeeds instead of failing
    the whole request."""
    monkeypatch.setattr(llm_client.time, "sleep", lambda *a: None)
    responses = iter([
        _FakeResponse(503, text="service unavailable"),
        _FakeResponse(200, {"choices": [{"message": {"content": "Sunscreen SPF 50."}}]}),
    ])
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: next(responses))

    answer = llm_client.generate_answer(_context(), api_key="test-key")
    assert answer == "Sunscreen SPF 50."


def test_generate_answer_does_not_retry_a_client_error(monkeypatch):
    """A 401 (bad key) won't become valid on retry - retrying it would just
    burn latency and quota for a guaranteed-identical outcome."""
    calls = []
    monkeypatch.setattr(
        llm_client.httpx, "post",
        lambda *a, **k: calls.append(1) or _FakeResponse(401, text="invalid api key"),
    )
    with pytest.raises(llm_client.LLMError, match="401"):
        llm_client.generate_answer(_context(), api_key="test-key")
    assert len(calls) == 1  # no retry attempted at all


def test_backoff_seconds_is_never_shorter_than_the_unjittered_base(monkeypatch):
    """RETRY_JITTER_FRACTION only ever lengthens a wait, never shortens it -
    a real retry storm made worse by retrying SOONER would defeat the point."""
    monkeypatch.setattr(llm_client, "RETRY_BACKOFF_SECONDS", 0.5)
    monkeypatch.setattr(llm_client, "RETRY_JITTER_FRACTION", 0.5)
    for attempt in range(3):
        base = 0.5 * (attempt + 1)
        for _ in range(20):  # random - sample enough to catch a bug in either bound
            waited = llm_client._backoff_seconds(attempt)
            assert base <= waited <= base * 1.5


def test_circuit_breaker_opens_after_threshold_consecutive_failures(monkeypatch):
    """
    The real fix: after enough consecutive request-level failures (each
    one already exhausted its own retries), a NEW call must fail fast -
    without even attempting an HTTP call - instead of repeating the full
    retry sequence against a provider that's already known to be down.
    """
    monkeypatch.setattr(llm_client, "MAX_RETRIES", 0)  # one attempt per call, fail fast for this test
    monkeypatch.setattr(llm_client, "CIRCUIT_BREAKER_THRESHOLD", 2)
    monkeypatch.setattr(llm_client.time, "sleep", lambda *a: None)
    calls = []
    monkeypatch.setattr(
        llm_client.httpx, "post",
        lambda *a, **k: calls.append(1) or _FakeResponse(503, text="service unavailable"),
    )

    with pytest.raises(llm_client.LLMError, match="503"):
        llm_client.generate_answer(_context(), api_key="test-key")
    with pytest.raises(llm_client.LLMError, match="503"):
        llm_client.generate_answer(_context(), api_key="test-key")
    assert len(calls) == 2  # both real failures, circuit not open yet

    with pytest.raises(llm_client.LLMError, match="circuit breaker is open"):
        llm_client.generate_answer(_context(), api_key="test-key")
    assert len(calls) == 2  # the third call never even attempted an HTTP request


def test_circuit_breaker_resets_after_a_successful_call(monkeypatch):
    monkeypatch.setattr(llm_client, "MAX_RETRIES", 0)
    monkeypatch.setattr(llm_client, "CIRCUIT_BREAKER_THRESHOLD", 2)
    monkeypatch.setattr(llm_client.time, "sleep", lambda *a: None)
    responses = iter([
        _FakeResponse(503, text="service unavailable"),
        _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}),
        _FakeResponse(503, text="service unavailable"),
    ])
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: next(responses))

    with pytest.raises(llm_client.LLMError):
        llm_client.generate_answer(_context(), api_key="test-key")  # 1 consecutive failure
    llm_client.generate_answer(_context(), api_key="test-key")  # succeeds - resets the counter
    with pytest.raises(llm_client.LLMError, match="503"):
        # a real failure again, not "circuit breaker is open" - the earlier
        # failure no longer counts toward the threshold after the reset
        llm_client.generate_answer(_context(), api_key="test-key")


def test_circuit_breaker_closes_again_after_the_cooldown_elapses(monkeypatch):
    monkeypatch.setattr(llm_client, "MAX_RETRIES", 0)
    monkeypatch.setattr(llm_client, "CIRCUIT_BREAKER_THRESHOLD", 1)
    monkeypatch.setattr(llm_client, "CIRCUIT_BREAKER_COOLDOWN_SECONDS", 10)
    monkeypatch.setattr(llm_client.time, "sleep", lambda *a: None)
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: _FakeResponse(503, text="service unavailable"))

    fake_now = [1000.0]
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: fake_now[0])

    with pytest.raises(llm_client.LLMError, match="503"):
        llm_client.generate_answer(_context(), api_key="test-key")  # opens the circuit

    with pytest.raises(llm_client.LLMError, match="circuit breaker is open"):
        llm_client.generate_answer(_context(), api_key="test-key")

    fake_now[0] += 11  # past the 10s cooldown
    with pytest.raises(llm_client.LLMError, match="503"):
        # cooldown elapsed - a real attempt is made again, not "circuit breaker is open"
        llm_client.generate_answer(_context(), api_key="test-key")


def test_generate_answer_uses_env_model_when_not_overridden(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "qwen/some-other-model")
    monkeypatch.setattr(llm_client, "MODEL_NAME", "qwen/some-other-model")
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["model"] = json["model"]
        return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    llm_client.generate_answer(_context(), api_key="test-key")
    assert captured["model"] == "qwen/some-other-model"


def test_generate_answer_uses_the_paid_provider_when_configured(monkeypatch):
    """The flexible placeholder: setting PAID_LLM_BASE_URL (+ API key)
    routes generate_answer() at that vendor instead of Groq, with the
    exact same request shape - no other code path change needed."""
    monkeypatch.setattr(llm_client, "PAID_LLM_BASE_URL", "https://paid-vendor.example/v1/chat/completions")
    monkeypatch.setattr(llm_client, "PAID_LLM_API_KEY", "paid-key")
    monkeypatch.setattr(llm_client, "PAID_LLM_MODEL", "paid-vendor/best-model")

    def fake_post(url, headers, json, timeout):
        assert url == "https://paid-vendor.example/v1/chat/completions"
        assert headers["Authorization"] == "Bearer paid-key"
        assert json["model"] == "paid-vendor/best-model"
        return _FakeResponse(200, {"choices": [{"message": {"content": "Sunscreen SPF 50."}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    answer = llm_client.generate_answer(_context())
    assert answer == "Sunscreen SPF 50."


def test_generate_answer_paid_provider_takes_priority_over_local(monkeypatch):
    monkeypatch.setattr(llm_client, "LOCAL_LLM_BASE_URL", "http://localhost:8080/v1/chat/completions")
    monkeypatch.setattr(llm_client, "PAID_LLM_BASE_URL", "https://paid-vendor.example/v1/chat/completions")
    monkeypatch.setattr(llm_client, "PAID_LLM_API_KEY", "paid-key")

    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_client.httpx, "post", fake_post)
    llm_client.generate_answer(_context())
    assert captured["url"] == "https://paid-vendor.example/v1/chat/completions"


def test_generate_answer_raises_when_paid_base_url_set_without_an_api_key(monkeypatch):
    monkeypatch.setattr(llm_client, "PAID_LLM_BASE_URL", "https://paid-vendor.example/v1/chat/completions")
    with pytest.raises(llm_client.LLMError, match="PAID_LLM_API_KEY"):
        llm_client.generate_answer(_context())


def test_answer_query_short_circuits_when_neither_retrieval_nor_structured_facts_have_anything(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(
        llm_client, "run_retrieval", lambda *a, **k: AssembledContext(query="q", context_text="", sources=[])
    )
    monkeypatch.setattr(llm_client, "build_structured_facts_block", lambda *a, **k: "")

    result = llm_client.answer_query(conn=None, tenant_id="t", query_text="q")

    assert result["sources"] == []
    assert "don't have any relevant information" in result["answer"]
    assert calls == []  # the LLM was never called


def test_answer_query_still_answers_from_structured_facts_alone(monkeypatch):
    """The real fix: a question with no matching document but real,
    current structured data must still get a real answer, not a
    reflexive "I don't have any relevant information"."""
    monkeypatch.setattr(
        llm_client, "run_retrieval", lambda *a, **k: AssembledContext(query="q", context_text="", sources=[])
    )
    monkeypatch.setattr(
        llm_client, "build_structured_facts_block",
        lambda *a, **k: "Current overall sentiment score: 0.42 (source: sentiment_results).",
    )
    captured = {}
    monkeypatch.setattr(llm_client, "generate_answer", lambda context, **k: captured.update(k) or "0.42.")

    result = llm_client.answer_query(conn=None, tenant_id="t", query_text="what's my sentiment score?")

    assert result["answer"] == "0.42."
    assert "0.42" in captured["structured_facts"]


def test_answer_query_returns_answer_and_sources_together(monkeypatch):
    fake_context = _context()
    monkeypatch.setattr(llm_client, "run_retrieval", lambda *a, **k: fake_context)
    monkeypatch.setattr(llm_client, "build_structured_facts_block", lambda *a, **k: "")
    monkeypatch.setattr(llm_client, "generate_answer", lambda context, **k: "Sunscreen SPF 50.")

    result = llm_client.answer_query(conn=None, tenant_id="t", query_text="what is our best seller?")

    assert result == {"answer": "Sunscreen SPF 50.", "sources": fake_context.sources}


def test_answer_query_skips_structured_facts_when_disabled(monkeypatch):
    fake_context = _context()
    monkeypatch.setattr(llm_client, "run_retrieval", lambda *a, **k: fake_context)
    calls = []
    monkeypatch.setattr(llm_client, "build_structured_facts_block", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(llm_client, "generate_answer", lambda context, **k: "Sunscreen SPF 50.")

    llm_client.answer_query(conn=None, tenant_id="t", query_text="q", include_structured_facts=False)

    assert calls == []  # never even queried


def test_build_user_prompt_includes_a_separately_labeled_structured_facts_section():
    prompt = llm_client._build_user_prompt(_context(), structured_facts="Sentiment score: 0.42.")
    assert "Context:" in prompt
    assert "Current business data (live, queried for this question):" in prompt
    assert "Sentiment score: 0.42." in prompt


def test_build_user_prompt_omits_the_structured_facts_section_when_empty():
    prompt = llm_client._build_user_prompt(_context(), structured_facts="")
    assert "Current business data" not in prompt


def test_system_prompt_explicitly_bans_ml_jargon_terms():
    """
    Extreme Simplicity is a hard product requirement: the merchant-facing
    chatbot must never surface statistical/ML jargon (MASE, RMSE, XGBoost,
    raw confidence scores), even if the retrieved context or structured
    facts happen to contain it (forecasting/pipeline.py's own internal
    technical explanation does, by design - see its own docstring). The
    instruction to strip it has to live in SYSTEM_PROMPT itself since the
    model can't be trusted to omit it on its own once it's already in
    front of it as "the source material" - so the prompt must both name
    the specific terms to ban AND say plainly never to use them.
    """
    jargon_terms = ["MASE", "RMSE", "XGBoost", "confidence 0.73"]
    for term in jargon_terms:
        assert term in llm_client.SYSTEM_PROMPT  # named as an example of banned jargon

    prompt_lower = llm_client.SYSTEM_PROMPT.lower()
    assert "never" in prompt_lower and "jargon" in prompt_lower
    assert "plain" in prompt_lower


def test_system_prompt_mandates_plain_spoken_arabic_not_formal_or_transliterated():
    prompt_lower = llm_client.SYSTEM_PROMPT.lower()
    assert "arabic" in prompt_lower
    assert "formal" in prompt_lower  # explicitly rules out stiff/formal register


def test_system_prompt_includes_a_teaching_mode_for_confused_users():
    prompt_lower = llm_client.SYSTEM_PROMPT.lower()
    assert "teach" in prompt_lower
    assert "explain" in prompt_lower


def test_system_prompt_mandates_exact_language_matching_never_defaulting_to_english():
    prompt_lower = llm_client.SYSTEM_PROMPT.lower()
    assert "exact same language" in prompt_lower
    assert "never" in prompt_lower and "default" in prompt_lower and "english" in prompt_lower


def test_system_prompt_mandates_dialect_and_tone_matching():
    """
    The vision's own example: Jordanian Arabic -> natural Jordanian Arabic,
    formal English -> professional English, casual -> casual. Plain
    Modern Standard Arabic for every Arabic speaker regardless of their
    own dialect would fail this - the prompt must name dialect and
    register matching explicitly, not just "respond in Arabic".
    """
    prompt_lower = llm_client.SYSTEM_PROMPT.lower()
    assert "dialect" in prompt_lower
    assert "jordanian" in prompt_lower or "levantine" in prompt_lower
    assert "register" in prompt_lower or "tone" in prompt_lower


def test_system_prompt_says_dialect_matching_never_excuses_jargon():
    """Guards against a real failure mode: a model told to "match the
    user's casual dialect" could misread that as license to relax the
    Extreme Simplicity rule too - the prompt must say explicitly that it
    doesn't."""
    prompt_lower = llm_client.SYSTEM_PROMPT.lower()
    assert "excuses using jargon" in prompt_lower or "excuse" in prompt_lower
