"""Question-driven public research (research/): safe page reading, provenance,
official sources first, private figures kept out of searches, and explicit
outcomes when research cannot be done. The network is replaced by fakes."""
import socket

import httpx
import pytest

from src.ai.rag import evidence as ev
from src.ai.research import page_reader, research, sources

ARTICLE = """<html lang="en"><head><title>Import duties on olive oil</title>
<meta property="og:site_name" content="Jordan Customs">
<meta property="article:published_time" content="2026-03-02T10:00:00Z">
<script type="application/ld+json">{"@type": "Article", "dateModified": "2026-05-01"}</script>
<script>ignore me</script></head><body><nav>Home | Contact</nav>
<article><h1>Olive oil</h1><p>Olive oil (HS 1509) attracts a customs duty of 20% on import into Jordan.</p>
<p>A general sales tax of 16% applies to the customs value plus duty.</p>
<table><tr><th>HS</th><th>Duty</th></tr><tr><td>1509.10</td><td>20%</td></tr></table></article>
<footer>Copyright</footer></body></html>"""


def _public(host, port, type=None):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _private(host, port, type=None):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]


def _fetch(pages, robots="User-agent: *\nAllow: /"):
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots, request=httpx.Request("GET", url))
        status, body, content_type, headers = pages.get(url, (404, "", "text/html", {}))
        return httpx.Response(status, text=body, headers={"content-type": content_type, **headers},
                              request=httpx.Request("GET", url))
    fetch.calls = calls
    return fetch


@pytest.fixture(autouse=True)
def _fresh_robots_cache():
    page_reader._ROBOTS_CACHE.clear()


def test_a_page_is_read_with_its_title_publisher_dates_and_tables():
    url = "https://customs.gov.jo/olive-oil"
    page = page_reader.read(url, fetch=_fetch({url: (200, ARTICLE, "text/html", {})}), resolver=_public)
    assert page.readable
    assert page.title == "Import duties on olive oil" and page.site_name == "Jordan Customs"
    assert page.published_at == "2026-03-02" and page.modified_at == "2026-05-01"
    assert "customs duty of 20%" in page.text and "ignore me" not in page.text and "Home | Contact" not in page.text
    assert page.tables == ["HS | Duty\n1509.10 | 20%"]


def test_a_page_resolving_to_a_private_address_is_never_fetched():
    fetch = _fetch({})
    page = page_reader.read("https://intranet.example.com/", fetch=fetch, resolver=_private)
    assert page.status == page_reader.UNSAFE_TARGET and fetch.calls == []


def test_a_redirect_into_a_private_network_is_refused():
    url = "https://public.example.com/a"
    fetch = _fetch({url: (302, "", "text/html", {"location": "http://localhost:8000/admin"})})
    page = page_reader.read(url, fetch=fetch, resolver=_public)
    assert page.status == page_reader.UNSAFE_TARGET


def test_robots_txt_is_honoured():
    url = "https://shop.example.com/products"
    page = page_reader.read(url, fetch=_fetch({url: (200, ARTICLE, "text/html", {})}, robots="User-agent: *\nDisallow: /"),
                            resolver=_public)
    assert page.status == page_reader.BLOCKED_BY_ROBOTS and not page.readable


def test_login_walls_and_refusals_are_reported_not_read():
    url = "https://paywalled.example.com/report"
    login = "<html><body><p>Please log in to continue reading.</p></body></html>"
    assert page_reader.read(url, fetch=_fetch({url: (200, login, "text/html", {})}), resolver=_public).status \
        == page_reader.NEEDS_LOGIN
    assert page_reader.read(url, fetch=_fetch({url: (403, "", "text/html", {})}), resolver=_public).status \
        == page_reader.NEEDS_LOGIN


def test_credibility_and_jurisdiction_of_sources():
    assert sources.credibility("https://www.customs.gov.jo/x") == sources.OFFICIAL
    assert sources.jurisdiction("https://www.customs.gov.jo/x") == "JO"
    assert sources.jurisdiction("https://zatca.gov.sa/en") == "SA"
    assert sources.jurisdiction("https://www.wto.org/tariffs") == "International"
    assert sources.credibility("https://blog.example.com/x") == sources.SECONDARY
    assert sources.jurisdiction("https://blog.example.com/x") is None


def test_private_figures_never_reach_a_search_query():
    query = research.public_safe("import olive oil at 4.5 JOD per bottle, 1000 bottles, call +962 79 123 4567 or a@b.com")
    for leaked in ("4.5", "1000", "962", "a@b.com"):
        assert leaked not in query
    assert research.public_safe("tariff for HS 150910", hs_code="150910").endswith("150910")


def test_template_queries_name_the_route_and_aim_at_the_official_site():
    queries = research.plan_queries("customs duty to import olive oil", ["trade"],
                                    {"origin_country": "TR", "destination_country": "JO", "hs_code": "1509"},
                                    {"country_code": "JO"})
    assert any("Jordan" in q and "HS 1509" in q for q in queries)
    assert any(q.startswith("site:customs.gov.jo") for q in queries)
    assert len(queries) <= research.MAX_QUERIES


def _run(results, pages, intents=("trade",), slots=None):
    registry = ev.EvidenceRegistry()
    outcome = research.research(None, "t1", registry, "customs duty to import olive oil into Jordan", list(intents),
                                slots or {"destination_country": "JO"}, {"country_code": "JO"},
                                search_fn=lambda query: results, fetch=_fetch(pages), resolver=_public)
    return outcome, registry


def test_research_reads_the_pages_and_keeps_their_provenance():
    official, blog = "https://customs.gov.jo/olive-oil", "https://blog.example.com/olive-oil"
    outcome, registry = _run(
        [{"url": blog, "title": "Blog", "snippet": "duty is about 20 percent"},
         {"url": official, "title": "Customs", "snippet": "duty 20%"}],
        {official: (200, ARTICLE, "text/html", {}),
         blog: (200, "<html><body><p>" + "Importers report duties on olive oil. " * 20 + "</p></body></html>", "text/html", {})})
    assert outcome.status == research.FOUND
    assert outcome.pages[0]["url"] == official, "official sources are read first for legal and trade questions"
    first = outcome.evidence[0]
    assert first.kind == ev.WEB_PAGE and first.credibility == ev.OFFICIAL and first.jurisdiction == "JO"
    assert first.url == official and first.published_at == "2026-03-02" and first.retrieved_at
    assert "20%" in " ".join(item.excerpt for item in outcome.evidence)
    blog_items = [item for item in outcome.evidence if item.url == blog]
    assert blog_items and blog_items[0].credibility == ev.SECONDARY
    assert any("does not state when it was published" in limit for limit in blog_items[0].limitations)


def test_an_unreadable_page_falls_back_to_its_snippet_clearly_marked():
    url = "https://blocked.example.com/x"
    outcome, _ = _run([{"url": url, "title": "Blocked", "snippet": "duty 20% on olive oil"}], {url: (403, "", "text/html", {})})
    assert outcome.status == research.FOUND
    assert "only the search engine's summary" in outcome.evidence[0].limitations[0]
    assert outcome.detail == "only search summaries were available; no page could be read"


def test_no_results_and_no_provider_are_explicit_outcomes(monkeypatch):
    outcome, registry = _run([], {})
    assert outcome.status == research.NO_RESULTS and len(registry) == 0

    from src.market_scraper import web_search

    monkeypatch.setattr(web_search, "is_configured", lambda exclude=(): False)
    registry = ev.EvidenceRegistry()
    outcome = research.research(None, "t1", registry, "customs duty for olive oil", ["trade"], {}, {"country_code": "JO"})
    assert outcome.status == research.NOT_CONFIGURED and len(registry) == 0


def test_links_the_user_pasted_are_read_without_searching():
    url = "https://supplier.example.com/olive-oil"
    searched = []
    registry = ev.EvidenceRegistry()
    outcome = research.research(None, "t1", registry, f"is this supplier cheaper? {url}", ["product_research"],
                                {"urls": [url]}, {"country_code": "JO"},
                                search_fn=lambda q: searched.append(q) or [],
                                fetch=_fetch({url: (200, ARTICLE, "text/html", {})}), resolver=_public)
    assert outcome.status == research.FOUND and outcome.pages[0]["url"] == url
