from unittest.mock import MagicMock, patch

from src.market_scraper.discovery import CandidateSource
from src.market_scraper.web_product_discovery import (
    discover_industry_candidates, discover_product_candidates, discover_social_profile_candidates,
)


def test_returns_empty_list_when_credentials_are_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_CX", raising=False)
    assert discover_product_candidates("Espresso Machine") == []


def test_returns_candidate_sources_from_real_shaped_search_results():
    payload = {
        "items": [
            {"title": "Buy Espresso Machine - Acme Coffee Co", "link": "https://acmecoffee.example/espresso-machine"},
            {"title": "Espresso Machine | Bean Supply", "link": "https://beansupply.example/products/espresso"},
        ]
    }
    with patch("src.market_scraper.web_product_discovery._get", return_value=payload):
        candidates = discover_product_candidates(
            "Espresso Machine", api_key="k", cx="c",
        )

    assert candidates == [
        CandidateSource("Espresso Machine", "https://acmecoffee.example/espresso-machine", "Buy Espresso Machine - Acme Coffee Co"),
        CandidateSource("Espresso Machine", "https://beansupply.example/products/espresso", "Espresso Machine | Bean Supply"),
    ]


def test_skips_items_missing_a_link():
    payload = {"items": [{"title": "No link here"}, {"title": "Has one", "link": "https://example.test/p"}]}
    with patch("src.market_scraper.web_product_discovery._get", return_value=payload):
        candidates = discover_product_candidates("Sofa", api_key="k", cx="c")
    assert len(candidates) == 1
    assert candidates[0].url == "https://example.test/p"


def test_returns_empty_list_on_api_error_payload():
    with patch("src.market_scraper.web_product_discovery._get", return_value={"error": {"code": 403}}):
        assert discover_product_candidates("Sofa", api_key="k", cx="c") == []


def test_returns_empty_list_when_request_fails():
    with patch("src.market_scraper.web_product_discovery._get", return_value=None):
        assert discover_product_candidates("Sofa", api_key="k", cx="c") == []


def test_returns_empty_list_when_there_are_genuinely_no_results():
    with patch("src.market_scraper.web_product_discovery._get", return_value={"items": []}):
        assert discover_product_candidates("A product nobody sells", api_key="k", cx="c") == []


def test_social_discovery_returns_empty_list_when_credentials_are_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_CX", raising=False)
    assert discover_social_profile_candidates("Espresso Machine") == []


def test_social_discovery_queries_each_platform_and_returns_real_profile_urls():
    def fake_get(params):
        if "instagram.com" in params["q"]:
            return {"items": [{"title": "Acme Coffee Co (@acmecoffee) - Instagram", "link": "https://www.instagram.com/acmecoffee/"}]}
        if "facebook.com" in params["q"]:
            return {"items": [{"title": "Acme Coffee Co - Facebook", "link": "https://www.facebook.com/acmecoffeeco/"}]}
        return {"items": []}

    with patch("src.market_scraper.web_product_discovery._get", side_effect=fake_get):
        candidates = discover_social_profile_candidates("Espresso Machine", api_key="k", cx="c")

    urls = {c.url for c in candidates}
    assert urls == {"https://www.instagram.com/acmecoffee/", "https://www.facebook.com/acmecoffeeco/"}


def test_social_discovery_query_uses_site_operator_for_each_platform():
    captured_queries = []

    def fake_get(params):
        captured_queries.append(params["q"])
        return {"items": []}

    with patch("src.market_scraper.web_product_discovery._get", side_effect=fake_get):
        discover_social_profile_candidates("Espresso Machine", api_key="k", cx="c")

    assert captured_queries == ['"Espresso Machine" site:instagram.com', '"Espresso Machine" site:facebook.com']


def test_social_discovery_one_platform_erroring_does_not_drop_the_other():
    def fake_get(params):
        if "instagram.com" in params["q"]:
            return {"error": {"code": 403}}
        return {"items": [{"title": "Acme - Facebook", "link": "https://www.facebook.com/acme/"}]}

    with patch("src.market_scraper.web_product_discovery._get", side_effect=fake_get):
        candidates = discover_social_profile_candidates("Espresso Machine", api_key="k", cx="c")

    assert len(candidates) == 1
    assert candidates[0].url == "https://www.facebook.com/acme/"


def test_cache_hit_skips_the_live_api_call_entirely():
    with patch("src.market_scraper.web_product_discovery.search_cache.get_cached", return_value=[
        CandidateSource("Espresso Machine", "https://cached.example/espresso", "Cached Result"),
    ]), patch("src.market_scraper.web_product_discovery._get") as mocked_get:
        candidates = discover_product_candidates("Espresso Machine", api_key="k", cx="c", conn=object())

    mocked_get.assert_not_called()
    assert candidates[0].url == "https://cached.example/espresso"


def test_cache_miss_calls_live_api_and_stores_the_result():
    payload = {"items": [{"title": "Buy Espresso Machine", "link": "https://acme.example/espresso"}]}
    conn = MagicMock()
    with patch("src.market_scraper.web_product_discovery.search_cache.get_cached", return_value=None), \
         patch("src.market_scraper.web_product_discovery.search_cache.set_cached") as mocked_set, \
         patch("src.market_scraper.web_product_discovery.search_quota.has_budget", return_value=True), \
         patch("src.market_scraper.web_product_discovery.search_quota.record_query") as mocked_record, \
         patch("src.market_scraper.web_product_discovery._get", return_value=payload):
        candidates = discover_product_candidates("Espresso Machine", api_key="k", cx="c", conn=conn)

    assert len(candidates) == 1
    mocked_set.assert_called_once()
    mocked_record.assert_called_once()  # the real call that was made counts against today's budget


def test_a_genuinely_empty_google_result_is_cached_not_treated_as_a_failure():
    conn = MagicMock()
    with patch("src.market_scraper.web_product_discovery.search_cache.get_cached", return_value=None), \
         patch("src.market_scraper.web_product_discovery.search_cache.set_cached") as mocked_set, \
         patch("src.market_scraper.web_product_discovery.search_quota.has_budget", return_value=True), \
         patch("src.market_scraper.web_product_discovery.search_quota.record_query"), \
         patch("src.market_scraper.web_product_discovery._get", return_value={"items": []}), \
         patch("src.market_scraper.web_product_discovery.searxng_discovery.discover_product_candidates") as mocked_searxng:
        candidates = discover_product_candidates("A product nobody sells", api_key="k", cx="c", conn=conn)

    assert candidates == []
    mocked_set.assert_called_once()  # cached as a real "no results" answer
    mocked_searxng.assert_not_called()  # not a failure, so no fallback needed


def test_google_error_triggers_searxng_fallback_and_is_not_cached():
    conn = MagicMock()
    with patch("src.market_scraper.web_product_discovery.search_cache.get_cached", return_value=None), \
         patch("src.market_scraper.web_product_discovery.search_cache.set_cached") as mocked_set, \
         patch("src.market_scraper.web_product_discovery.search_quota.has_budget", return_value=True), \
         patch("src.market_scraper.web_product_discovery.search_quota.record_query"), \
         patch("src.market_scraper.web_product_discovery._get", return_value={"error": {"code": 429}}), \
         patch(
             "src.market_scraper.web_product_discovery.searxng_discovery.discover_product_candidates",
             return_value=[CandidateSource("Espresso Machine", "https://searxng-result.example", "From SearXNG")],
         ) as mocked_searxng:
        candidates = discover_product_candidates("Espresso Machine", api_key="k", cx="c", conn=conn)

    assert candidates[0].url == "https://searxng-result.example"
    mocked_set.assert_not_called()  # a failure is never cached
    mocked_searxng.assert_called_once()


def test_record_query_commits_immediately_even_when_the_result_is_zero_candidates():
    """
    The real fix: a real Google API call's quota spend must be durably
    recorded the instant it happens, not only as a side effect of some
    later caller (e.g. discovery.py registering a competitor elsewhere in
    the same transaction) committing the connection. Before this, a query
    that found zero candidates - exactly this scenario - left the spend
    uncommitted with nothing downstream to ever commit it, silently
    under-counting real usage against the daily budget.
    """
    conn = MagicMock()
    call_order = []
    conn.commit.side_effect = lambda: call_order.append("commit")

    with patch("src.market_scraper.web_product_discovery.search_cache.get_cached", return_value=None), \
         patch("src.market_scraper.web_product_discovery.search_cache.set_cached"), \
         patch("src.market_scraper.web_product_discovery.search_quota.has_budget", return_value=True), \
         patch(
             "src.market_scraper.web_product_discovery.search_quota.record_query",
             side_effect=lambda *a, **k: call_order.append("record_query"),
         ), \
         patch("src.market_scraper.web_product_discovery._get", return_value={"items": []}):
        discover_product_candidates("A product nobody sells", api_key="k", cx="c", conn=conn)

    assert "commit" in call_order
    assert call_order.index("record_query") < call_order.index("commit")


def test_quota_exhausted_skips_the_live_call_and_tries_searxng():
    with patch("src.market_scraper.web_product_discovery.search_cache.get_cached", return_value=None), \
         patch("src.market_scraper.web_product_discovery.search_quota.has_budget", return_value=False), \
         patch("src.market_scraper.web_product_discovery._get") as mocked_get, \
         patch(
             "src.market_scraper.web_product_discovery.searxng_discovery.discover_product_candidates",
             return_value=[CandidateSource("Espresso Machine", "https://searxng-result.example", "From SearXNG")],
         ) as mocked_searxng:
        candidates = discover_product_candidates("Espresso Machine", api_key="k", cx="c", conn=object())

    mocked_get.assert_not_called()  # the real Google HTTP call is never even attempted over budget
    mocked_searxng.assert_called_once()
    assert candidates[0].url == "https://searxng-result.example"


def test_daily_query_limit_none_disables_local_quota_tracking():
    payload = {"items": [{"title": "Buy Espresso Machine", "link": "https://acme.example/espresso"}]}
    with patch("src.market_scraper.web_product_discovery.search_cache.get_cached", return_value=None), \
         patch("src.market_scraper.web_product_discovery.search_cache.set_cached"), \
         patch("src.market_scraper.web_product_discovery.search_quota.has_budget") as mocked_has_budget, \
         patch("src.market_scraper.web_product_discovery.search_quota.record_query"), \
         patch("src.market_scraper.web_product_discovery._get", return_value=payload):
        candidates = discover_product_candidates(
            "Espresso Machine", api_key="k", cx="c", conn=MagicMock(), daily_query_limit=None,
        )

    mocked_has_budget.assert_not_called()  # None means "don't track locally at all"
    assert len(candidates) == 1


def test_missing_google_credentials_go_straight_to_searxng(monkeypatch):
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_CX", raising=False)
    with patch(
        "src.market_scraper.web_product_discovery.searxng_discovery.discover_product_candidates",
        return_value=[CandidateSource("Espresso Machine", "https://searxng-result.example", "From SearXNG")],
    ) as mocked_searxng:
        candidates = discover_product_candidates("Espresso Machine")

    assert candidates[0].url == "https://searxng-result.example"
    mocked_searxng.assert_called_once()


def test_query_passed_to_search_is_built_by_sector_detection_helper():
    captured = {}

    def fake_get(params):
        captured.update(params)
        return {"items": []}

    with patch("src.market_scraper.web_product_discovery._get", side_effect=fake_get):
        discover_product_candidates("Running Shoes", geo_scope="Jordan", api_key="k", cx="c")

    assert captured["q"] == '"Running Shoes" buy shop store price Jordan'
    assert captured["key"] == "k"
    assert captured["cx"] == "c"


def test_industry_discovery_builds_an_industry_not_product_query():
    captured = {}

    def fake_get(params):
        captured.update(params)
        return {"items": []}

    with patch("src.market_scraper.web_product_discovery._get", side_effect=fake_get):
        discover_industry_candidates("electronics_hobbyist", geo_scope="Jordan", api_key="k", cx="c")

    assert captured["q"] == "electronics store buy shop store price Jordan"


def test_industry_discovery_returns_real_candidate_sources():
    payload = {
        "items": [
            {"title": "Downtown Electronics", "link": "https://downtown-electronics.example"},
        ]
    }
    with patch("src.market_scraper.web_product_discovery._get", return_value=payload):
        candidates = discover_industry_candidates("electronics_hobbyist", api_key="k", cx="c")

    assert candidates == [
        CandidateSource("electronics_hobbyist", "https://downtown-electronics.example", "Downtown Electronics"),
    ]


def test_industry_discovery_returns_empty_list_when_credentials_are_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CUSTOM_SEARCH_CX", raising=False)
    assert discover_industry_candidates("electronics_hobbyist") == []
