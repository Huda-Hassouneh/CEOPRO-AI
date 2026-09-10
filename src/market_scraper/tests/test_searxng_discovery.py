from unittest.mock import MagicMock, patch

from src.market_scraper.searxng_discovery import discover_product_candidates


def test_returns_empty_list_when_instance_url_is_not_configured(monkeypatch):
    monkeypatch.delenv("SEARXNG_INSTANCE_URL", raising=False)
    assert discover_product_candidates("Espresso Machine", "espresso machine buy shop") == []


def test_returns_candidates_from_a_real_shaped_response():
    payload = {
        "results": [
            {"title": "Buy Espresso Machine - Acme", "url": "https://acme.example/espresso"},
            {"title": "Espresso | Bean Co", "url": "https://beanco.example/espresso"},
        ]
    }
    fake_resp = MagicMock()
    fake_resp.read.return_value = __import__("json").dumps(payload).encode()
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    with patch("src.market_scraper.searxng_discovery.urllib.request.urlopen", return_value=fake_resp):
        candidates = discover_product_candidates("Espresso Machine", "espresso machine buy", instance_url="https://searx.example.org")
    assert len(candidates) == 2
    assert candidates[0].url == "https://acme.example/espresso"


def test_returns_empty_list_when_request_fails():
    with patch("src.market_scraper.searxng_discovery.urllib.request.urlopen", side_effect=OSError("boom")):
        assert discover_product_candidates("Espresso Machine", "q", instance_url="https://searx.example.org") == []


def test_skips_results_missing_a_url():
    payload = {"results": [{"title": "No url"}, {"title": "Has one", "url": "https://example.test/p"}]}
    fake_resp = MagicMock()
    fake_resp.read.return_value = __import__("json").dumps(payload).encode()
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False
    with patch("src.market_scraper.searxng_discovery.urllib.request.urlopen", return_value=fake_resp):
        candidates = discover_product_candidates("Sofa", "q", instance_url="https://searx.example.org")
    assert len(candidates) == 1
    assert candidates[0].url == "https://example.test/p"


def test_uses_env_var_when_instance_url_not_passed_explicitly(monkeypatch):
    monkeypatch.setenv("SEARXNG_INSTANCE_URL", "https://searx.env.example.org")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        raise OSError("stop after capturing")

    with patch("src.market_scraper.searxng_discovery.urllib.request.urlopen", side_effect=fake_urlopen):
        discover_product_candidates("Sofa", "q")
    assert captured["url"].startswith("https://searx.env.example.org/search?")
