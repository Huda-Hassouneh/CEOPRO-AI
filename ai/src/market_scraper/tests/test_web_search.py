"""The provider-neutral web search: order, skipping unconfigured providers,
falling through on failure, and each provider's request/response shape."""
import httpx
import pytest

from src.market_scraper import web_search

_ENV = ("GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_CUSTOM_SEARCH_CX", "BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY",
        "SEARXNG_INSTANCE_URL", "WEB_SEARCH_PROVIDERS")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


class FakeFetch:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, method, url, *, params=None, json=None, headers=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json, "headers": headers})
        answer = self.responses[url.split("?")[0]]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_nothing_configured_means_no_search():
    assert web_search.configured_providers() == []
    with pytest.raises(web_search.SearchFailed, match="not_configured"):
        web_search.search("bakery amman", fetch=FakeFetch({}))


def test_providers_follow_the_configured_order_and_skip_missing_credentials(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("SEARXNG_INSTANCE_URL", "http://searx.local")
    monkeypatch.setenv("GOOGLE_CUSTOM_SEARCH_API_KEY", "only-half")  # no CX: not configured
    assert web_search.configured_providers() == ["tavily", "searxng"]
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "searxng, tavily, unknown")
    assert web_search.configured_providers() == ["searxng", "tavily"]


def test_brave_request_and_results(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "secret")
    fetch = FakeFetch({web_search.BRAVE_URL: {"web": {"results": [
        {"url": "https://a.jo", "title": "A", "description": "Bakery in Amman"},
        {"title": "no url"},
    ]}}})
    provider, results = web_search.search("bakery amman", 5, country="jo", fetch=fetch)
    assert provider == "brave"
    assert [r.as_dict() for r in results] == [{"url": "https://a.jo", "title": "A", "snippet": "Bakery in Amman"}]
    call = fetch.calls[0]
    assert call["params"] == {"q": "bakery amman", "count": 5, "country": "JO"}
    assert call["headers"]["X-Subscription-Token"] == "secret"  # key in a header, not in the URL


def test_tavily_request_and_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "secret")
    fetch = FakeFetch({web_search.TAVILY_URL: {"results": [{"url": "https://b.jo", "title": "B", "content": "text"}]}})
    provider, results = web_search.search("pharmacy", 3, fetch=fetch)
    assert provider == "tavily" and results[0].snippet == "text"
    assert fetch.calls[0]["json"] == {"query": "pharmacy", "max_results": 3, "search_depth": "basic"}
    assert fetch.calls[0]["headers"] == {"Authorization": "Bearer secret"}


def test_google_error_payload_and_http_failure_fall_through_to_the_next_provider(monkeypatch):
    monkeypatch.setenv("GOOGLE_CUSTOM_SEARCH_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_CUSTOM_SEARCH_CX", "cx")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "b")
    monkeypatch.setenv("SEARXNG_INSTANCE_URL", "http://searx.local/")
    fetch = FakeFetch({
        web_search.GOOGLE_CSE_URL: {"error": {"code": 403, "message": "closed"}},
        web_search.BRAVE_URL: httpx.ConnectError("down"),
        "http://searx.local/search": {"results": [{"url": "https://c.jo", "title": "C", "content": "c"}]},
    })
    provider, results = web_search.search("q", fetch=fetch)
    assert provider == "searxng" and results[0].url == "https://c.jo"
    assert [c["url"] for c in fetch.calls] == [web_search.GOOGLE_CSE_URL, web_search.BRAVE_URL, "http://searx.local/search"]


def test_an_empty_answer_is_a_real_answer(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "b")
    monkeypatch.setenv("SEARXNG_INSTANCE_URL", "http://searx.local")
    fetch = FakeFetch({web_search.BRAVE_URL: {"web": {"results": []}}})
    assert web_search.search("q", fetch=fetch) == ("brave", [])
    assert len(fetch.calls) == 1


def test_every_provider_failing_is_reported(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    with pytest.raises(web_search.SearchFailed, match="unreachable"):
        web_search.search("q", fetch=FakeFetch({web_search.TAVILY_URL: httpx.ReadTimeout("slow")}))


def test_exclude_limits_the_providers_used(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "b")
    monkeypatch.setenv("SEARXNG_INSTANCE_URL", "http://searx.local")
    assert web_search.configured_providers(exclude=("searxng",)) == ["brave"]
    assert web_search.is_configured(exclude=("brave", "searxng")) is False
