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
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


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


def test_answer_query_short_circuits_on_empty_retrieval_without_calling_the_llm(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(
        llm_client, "run_retrieval", lambda *a, **k: AssembledContext(query="q", context_text="", sources=[])
    )

    result = llm_client.answer_query(conn=None, tenant_id="t", query_text="q")

    assert result["sources"] == []
    assert "don't have any relevant information" in result["answer"]
    assert calls == []  # the LLM was never called


def test_answer_query_returns_answer_and_sources_together(monkeypatch):
    fake_context = _context()
    monkeypatch.setattr(llm_client, "run_retrieval", lambda *a, **k: fake_context)
    monkeypatch.setattr(llm_client, "generate_answer", lambda context, **k: "Sunscreen SPF 50.")

    result = llm_client.answer_query(conn=None, tenant_id="t", query_text="what is our best seller?")

    assert result == {"answer": "Sunscreen SPF 50.", "sources": fake_context.sources}
