from unittest.mock import patch

from src.market_scraper.discovery import CandidateSource
from src.market_scraper.web_product_discovery import discover_product_candidates, discover_social_profile_candidates


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
