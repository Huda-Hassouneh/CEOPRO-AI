"""
Offline tests for rag/web_fallback.py - urllib is monkeypatched, so these
never make a real network request or need real Google/SearXNG
credentials. Same convention as test_rag_llm_client.py (llm_client.py's
own HTTP calls are mocked the same way).
"""
from unittest.mock import MagicMock

import pytest

from src.ai.rag import web_fallback


# --- looks_like_answerable_question ---------------------------------------

@pytest.mark.parametrize("greeting", [
    "hi", "Hi", "hello", "hey", "thanks", "thank you", "how are you",
    "مرحبا", "هلا", "هاي", "كيفك", "كيفك؟", "ازيك", "شعلومك", "شعلومك؟",
    "شكرا", "مساء الخير", "صباح الخير",
])
def test_greeting_and_smalltalk_are_never_answerable(greeting):
    assert web_fallback.looks_like_answerable_question(greeting) is False


def test_empty_or_whitespace_query_is_never_answerable():
    assert web_fallback.looks_like_answerable_question("") is False
    assert web_fallback.looks_like_answerable_question("   ") is False
    assert web_fallback.looks_like_answerable_question(None) is False


def test_a_very_short_fragment_is_not_answerable():
    assert web_fallback.looks_like_answerable_question("ok") is False
    assert web_fallback.looks_like_answerable_question("why") is False


def test_a_real_business_question_is_answerable():
    assert web_fallback.looks_like_answerable_question("what should a pharmacy stock this season?") is True
    assert web_fallback.looks_like_answerable_question("من هو اقوى منافس بمجال المطاعم؟") is True


# --- build_web_fallback_context: gating ------------------------------------

def _fake_conn(business_row=(None, None, None)):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = business_row
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn


def test_build_web_fallback_context_skips_search_entirely_for_a_greeting(monkeypatch):
    called = []
    monkeypatch.setattr(web_fallback, "_run_search", lambda *a, **k: called.append(1))
    context, sources = web_fallback.build_web_fallback_context(_fake_conn(), "t1", "hi")
    assert context == ""
    assert sources == []
    assert called == []  # never even attempted a search


def test_build_web_fallback_context_returns_nothing_when_fewer_than_min_sources(monkeypatch):
    monkeypatch.setattr(web_fallback, "_run_search", lambda *a, **k: [
        {"url": "https://example.com/a", "title": "A", "snippet": "..."},
    ])
    context, sources = web_fallback.build_web_fallback_context(
        _fake_conn(), "t1", "what should a pharmacy stock this season?",
    )
    assert context == ""
    assert sources == []


def test_build_web_fallback_context_returns_a_labeled_block_with_enough_sources(monkeypatch):
    monkeypatch.setattr(web_fallback, "_run_search", lambda *a, **k: [
        {"url": "https://a.example.com", "title": "Pharmacy trends 2026", "snippet": "Vitamins are trending."},
        {"url": "https://b.example.com", "title": "OTC report", "snippet": "OTC demand is rising."},
    ])
    context, sources = web_fallback.build_web_fallback_context(
        _fake_conn(), "t1", "what should a pharmacy stock this season?",
    )
    assert "[External 1]" in context and "[External 2]" in context
    assert "https://a.example.com" in context
    assert "Vitamins are trending." in context
    assert sources == [
        {"url": "https://a.example.com", "title": "Pharmacy trends 2026"},
        {"url": "https://b.example.com", "title": "OTC report"},
    ]


def test_build_web_fallback_context_never_raises_on_a_search_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network exploded")
    monkeypatch.setattr(web_fallback, "_run_search", _boom)
    context, sources = web_fallback.build_web_fallback_context(_fake_conn(), "t1", "a real business question here")
    assert (context, sources) == ("", [])


def test_build_web_fallback_context_scopes_the_query_to_the_tenants_own_field(monkeypatch):
    captured = {}

    def _capture_search(conn, tenant_id, query, max_results):
        captured["query"] = query
        return [
            {"url": "https://a.example.com", "title": "A", "snippet": "..."},
            {"url": "https://b.example.com", "title": "B", "snippet": "..."},
        ]
    monkeypatch.setattr(web_fallback, "_run_search", _capture_search)

    conn = _fake_conn(business_row=("Jane's Pharmacy", "pharmacy", "JO"))
    web_fallback.build_web_fallback_context(conn, "t1", "what should I add to my catalog?")

    assert "pharmacy" in captured["query"]
    assert "JO" in captured["query"]


# --- _run_search: paid provider -> self-hosted search -----------------------

_ALL_SEARCH_ENV = ("GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_CUSTOM_SEARCH_CX", "BRAVE_SEARCH_API_KEY",
                   "TAVILY_API_KEY", "SEARXNG_INSTANCE_URL", "WEB_SEARCH_PROVIDERS")


@pytest.fixture
def no_search_env(monkeypatch):
    for name in _ALL_SEARCH_ENV:
        monkeypatch.delenv(name, raising=False)


def test_run_search_uses_the_self_hosted_search_when_no_paid_provider_is_configured(monkeypatch, no_search_env):
    monkeypatch.setattr(web_fallback, "_search_free", lambda query, max_results: [
        {"url": "https://searx.example.com/x", "title": "X", "snippet": "..."},
    ])
    results = web_fallback._run_search(_fake_conn(), "t1", "query", 5)
    assert results == [{"url": "https://searx.example.com/x", "title": "X", "snippet": "..."}]


def test_run_search_does_not_search_again_on_a_real_zero_result_answer(monkeypatch):
    """A genuine 'no results' answer is real evidence, not a failure."""
    called = []
    monkeypatch.setattr(web_fallback, "_search_paid", lambda *a, **k: [])
    monkeypatch.setattr(web_fallback, "_search_free", lambda *a, **k: called.append(1))
    assert web_fallback._run_search(_fake_conn(), "t1", "query", 5) == []
    assert called == []


def test_run_search_falls_back_to_the_self_hosted_search_when_the_paid_one_fails(monkeypatch):
    monkeypatch.setattr(web_fallback, "_search_paid", lambda *a, **k: None)
    monkeypatch.setattr(web_fallback, "_search_free", lambda query, max_results: [
        {"url": "https://searx.example.com/y", "title": "Y", "snippet": "..."},
    ])
    results = web_fallback._run_search(_fake_conn(), "t1", "query", 5)
    assert results == [{"url": "https://searx.example.com/y", "title": "Y", "snippet": "..."}]


# --- _search_paid: quota gate ------------------------------------------------

def test_paid_search_skips_the_call_when_over_budget(monkeypatch, no_search_env):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "key")
    monkeypatch.setattr(web_fallback.search_quota, "has_budget", lambda conn, limit: False)
    called = []
    monkeypatch.setattr(web_fallback.web_search, "search", lambda *a, **k: called.append(1))
    assert web_fallback._search_paid(_fake_conn(), "query", 5) is None
    assert called == []  # never even attempted the HTTP call


def test_paid_search_returns_none_when_unconfigured(no_search_env):
    assert web_fallback._search_paid(_fake_conn(), "query", 5) is None


def test_paid_search_records_the_query_and_returns_plain_results(monkeypatch, no_search_env):
    monkeypatch.setenv("TAVILY_API_KEY", "key")
    monkeypatch.setattr(web_fallback.search_quota, "has_budget", lambda conn, limit: True)
    recorded = []
    monkeypatch.setattr(web_fallback.search_quota, "record_query", lambda conn: recorded.append(1))
    monkeypatch.setattr(web_fallback.web_search, "_default_fetch", lambda method, url, **kw: {
        "results": [{"url": "https://a.example/1", "title": "A", "content": "about a"}]})
    assert web_fallback._search_paid(_fake_conn(), "query", 5) == [
        {"url": "https://a.example/1", "title": "A", "snippet": "about a"}]
    assert recorded == [1]
