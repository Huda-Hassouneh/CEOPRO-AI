"""News for market trends (GDELT DOC API): the query sent, parsing the
article list it returns, competitor headlines, the request-spacing rule
and honest failure."""
import httpx

from src.market_scraper.market_discovery import news

GDELT = {"articles": [
    {"url": "https://jordantimes.com/news/bakeries-flour-prices", "url_mobile": "", "title": "Bakeries feel rising flour prices",
     "seendate": "20261001T081500Z", "socialimage": "", "domain": "jordantimes.com", "language": "English", "sourcecountry": "Jordan"},
    {"url": "https://roya.news/habibah-new-branch", "title": "Habibah Sweets opens a new branch in Irbid",
     "seendate": "20260920T100000Z", "domain": "roya.news", "language": "English", "sourcecountry": "Jordan"},
    {"url": "https://jordantimes.com/news/bakeries-flour-prices", "title": "duplicate", "seendate": "20261001T081500Z"},
    {"url": "javascript:alert(1)", "title": "not a link"},
]}


def test_query_is_the_industry_words_in_the_country():
    assert news.build_query(["bakery", "sweets shop", "حلويات", "ab"], "JO") == \
        '(bakery OR "sweets shop" OR حلويات) sourcecountry:jordan'
    assert news.build_query(["bakery"], "ZZ") == "bakery"
    assert news.build_query(["ab", ""], "JO") is None


def test_articles_keep_link_title_publisher_and_date():
    parsed = news.parse(GDELT)
    assert [a["url"] for a in parsed] == ["https://jordantimes.com/news/bakeries-flour-prices", "https://roya.news/habibah-new-branch"]
    assert parsed[0] == {"url": "https://jordantimes.com/news/bakeries-flour-prices", "title": "Bakeries feel rising flour prices",
                         "source_domain": "jordantimes.com", "language": "English", "published_at": "2026-10-01T08:15:00+00:00"}
    assert news.parse({}) == []  # GDELT answers {} when nothing matched


def test_competitor_news_must_name_a_competitor_and_requests_are_spaced(monkeypatch):
    sent, waits = [], []

    def fake(method, url, params=None, **kwargs):
        sent.append(params["query"])
        return GDELT

    monkeypatch.setattr(news, "request_json", fake)
    result = news.collect(["bakery"], ["Habibah Sweets", "Zalatimo"], "JO", sleep=waits.append)
    assert sent == ["bakery sourcecountry:jordan", '("Habibah Sweets" OR Zalatimo) sourcecountry:jordan']
    assert waits == [news.GDELT_INTERVAL_SECONDS]
    competitor = [a for a in result["articles"] if a["topic"] == "competitor"]
    assert [(a["title"], a["competitor"]) for a in competitor] == [("Habibah Sweets opens a new branch in Irbid", "Habibah Sweets")]
    assert result["status"] == "ok" and (result["requests"], result["answered"]) == (2, 2)


def test_unreachable_news_fails_honestly_and_can_be_turned_off(monkeypatch):
    def down(*args, **kwargs):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(news, "request_json", down)
    result = news.collect(["bakery"], [], "JO", sleep=lambda s: None)
    assert result["status"] == "failed" and result["articles"] == [] and result["reason"] == "unreachable"
    monkeypatch.setenv("DISCOVERY_DISABLE_NEWS", "1")
    assert news.collect(["bakery"], [], "JO")["status"] == "skipped"


def test_a_rate_limited_answer_is_asked_once_more_after_a_wait(monkeypatch):
    answers = iter([httpx.HTTPStatusError("429", request=httpx.Request("GET", news.API_URL),
                                          response=httpx.Response(429)), GDELT])

    def fake(*args, **kwargs):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    waits = []
    monkeypatch.setattr(news, "request_json", fake)
    result = news.collect(["bakery"], [], "JO", sleep=waits.append)
    assert result["status"] == "ok" and len(result["articles"]) == 2
    assert waits == [news.GDELT_INTERVAL_SECONDS * 2]
