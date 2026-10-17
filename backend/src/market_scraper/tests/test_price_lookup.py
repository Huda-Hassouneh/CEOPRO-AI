"""Offline tests for market_scraper/price_lookup: matching rules, each provider's
parsing (network mocked), and the pipeline's keep/flag/record decisions."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.market_scraper import web_search
from src.market_scraper.price_lookup import matching, pipeline, providers
from src.market_scraper.price_lookup.models import PriceQuote, ProductContext, ProviderError, ProviderUnavailable

CTX = ProductContext("p1", "Nutella Hazelnut Spread 350g", "JO", "JOD", 3.5)


# ---- matching --------------------------------------------------------------------

def test_a_listing_for_the_same_product_matches_and_a_different_size_does_not():
    assert matching.match_score("Nutella Hazelnut Spread 350g", "Nutella hazelnut spread, 350g jar") == 1.0
    assert matching.match_score("Nutella Hazelnut Spread 350g", "Nutella Hazelnut Spread 750g") == 0.0
    assert matching.is_match(matching.match_score("Arduino Nano", "Arduino Nano Board ATmega328")) is True
    assert matching.is_match(matching.match_score("Arduino Nano", "Raspberry Pi Zero")) is False


def test_plausibility_is_a_wide_band_and_unknown_without_a_reference():
    assert matching.plausible_price(4.0, 3.5) is True
    assert matching.plausible_price(40.0, 3.5) is False
    assert matching.plausible_price(0.1, 3.5) is False
    assert matching.plausible_price(4.0, None) is None


# ---- providers ------------------------------------------------------------------------

def test_open_prices_returns_this_countrys_prices_with_the_product_title():
    def get(url, params):
        if "search.pl" in url:
            return {"products": [{"code": "3017620422003", "product_name": "Hazelnut Spread", "brands": "Nutella,Ferrero"}]}
        return {"items": [
            {"price": 3.2, "currency": "jod", "location": {"osm_name": "Safeway", "osm_address_country_code": "JO"}},
            {"price": 5.0, "currency": "EUR", "location": {"osm_name": "Carrefour", "osm_address_country_code": "FR"}},
            {"price": None, "currency": "JOD"},
        ]}
    quotes = providers.OpenPrices(get).search(CTX)
    assert [(q.price, q.currency, q.seller) for q in quotes] == [(3.2, "JOD", "Safeway")]
    assert quotes[0].title.startswith("Nutella") and "3017620422003" in quotes[0].url


def test_open_prices_failure_is_a_provider_error_not_a_crash():
    def get(url, params):
        raise ProviderError("ConnectError")
    with pytest.raises(ProviderError):
        providers.OpenPrices(get).search(CTX)


HTML = '''<html><head>
<meta property="og:title" content="ignored when JSON-LD exists">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"Product","name":"Nutella Hazelnut Spread 350g","url":"https://shop.example/nutella",
  "aggregateRating":{"ratingValue":"4.6","reviewCount":"128"},
  "offers":{"@type":"Offer","price":"3.45","priceCurrency":"jod","seller":{"name":"Shop Example"}}},
 {"@type":"Product","name":"No currency","offers":{"price":"9"}}]}</script></head></html>'''


def test_extract_offers_reads_price_seller_rating_and_review_count_and_drops_unitless_prices():
    quotes = providers.extract_offers(HTML, "https://www.shop.example/p")
    assert len(quotes) == 1
    q = quotes[0]
    assert (q.price, q.currency, q.seller, q.rating, q.review_count) == (3.45, "JOD", "Shop Example", 4.6, 128)


def test_extract_offers_falls_back_to_open_graph_product_tags():
    html = '<meta property="og:title" content="Widget"><meta property="product:price:amount" content="12.50"><meta property="product:price:currency" content="USD">'
    q = providers.extract_offers(html, "https://www.widgets.example/w")[0]
    assert (q.title, q.price, q.currency, q.seller) == ("Widget", 12.5, "USD", "widgets.example")
    assert providers.extract_offers("<html>no data</html>", "https://x.example") == []


def test_web_offers_reads_one_page_per_host_and_collects_their_offers():
    results = [web_search.Result("https://a.example/1", "A", ""), web_search.Result("https://a.example/2", "A2", ""),
               web_search.Result("https://b.example/1", "B", ""), web_search.Result("ftp://c.example", "C", "")]
    fetched = []

    def fetch(url):
        fetched.append(url)
        return HTML

    provider = providers.WebOffers(search=lambda q, **k: ("brave", results), fetch_page=fetch)
    quotes = provider.search(CTX)
    assert fetched == ["https://a.example/1", "https://b.example/1"]  # one page per host, only http(s)
    assert len(quotes) == 2


def test_web_offers_reports_missing_search_setup_as_unavailable_and_failures_as_errors():
    def not_configured(q, **k):
        raise web_search.SearchFailed("not_configured")

    def broken(q, **k):
        raise web_search.SearchFailed("unreachable")
    with pytest.raises(ProviderUnavailable):
        providers.WebOffers(search=not_configured).search(CTX)
    with pytest.raises(ProviderError):
        providers.WebOffers(search=broken).search(CTX)


def test_serpapi_needs_a_key_parses_results_and_never_leaks_the_key(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    assert providers.SerpApiShopping().available() is False
    with pytest.raises(ProviderUnavailable):
        providers.SerpApiShopping().search(CTX)
    monkeypatch.setenv("SERPAPI_API_KEY", "SECRETKEY")
    payload = {"shopping_results": [
        {"title": "Nutella 350g", "extracted_price": 3.9, "price": "JD 3.90", "source": "Shop", "product_link": "https://g.example/p", "rating": 4.7, "reviews": 210},
        {"title": "No price"}, {"title": "Free currency", "extracted_price": 5, "price": "5"},
    ]}
    seen = {}

    def get(url, params):
        seen.update(params)
        return payload
    quotes = providers.SerpApiShopping(get).search(CTX)
    assert seen["engine"] == "google_shopping" and seen["gl"] == "jo"
    assert [(q.price, q.currency, q.rating, q.review_count) for q in quotes] == [(3.9, "JOD", 4.7, 210), (5.0, "JOD", None, None)]  # falls back to the tenant currency
    with pytest.raises(ProviderError) as exc:
        providers.SerpApiShopping(lambda u, p: {"error": "Invalid API key SECRETKEY"}).search(CTX)
    assert "SECRETKEY" not in str(exc.value)


def test_configured_order_defaults_cheapest_first_and_ignores_unknown_names(monkeypatch):
    monkeypatch.delenv("PRICE_LOOKUP_PROVIDERS", raising=False)
    assert providers.configured_order() == ["open_prices", "web_offers", "serpapi_shopping"]
    monkeypatch.setenv("PRICE_LOOKUP_PROVIDERS", "web_offers,nope")
    assert providers.configured_order() == ["web_offers"]


# ---- pipeline -----------------------------------------------------------------------------

class FakeProvider:
    def __init__(self, name, quotes=(), available=True, error=None, unavailable=False):
        self.name, self._quotes, self._available, self._error, self._unavailable = name, list(quotes), available, error, unavailable
        self.calls = 0

    def available(self):
        return self._available

    def search(self, ctx):
        self.calls += 1
        if self._unavailable:
            raise ProviderUnavailable("x")
        if self._error:
            raise self._error
        return self._quotes


def _quote(provider="web_offers", title="Nutella Hazelnut Spread 350g", price=3.4, currency="JOD"):
    return PriceQuote(provider, title, price, currency, seller="Shop", url="https://shop.example/p")


def _run(instances, order, all_providers=False):
    conn = MagicMock()
    with patch.object(pipeline, "_store", return_value=True) as store, patch.object(pipeline, "_record_lookup") as record:
        result = pipeline.lookup_product(conn, "t1", CTX, instances, order, all_providers)
    return result, store, record


def test_stops_at_the_first_provider_that_yields_an_acceptable_quote():
    first, second = FakeProvider("a", [_quote("a")]), FakeProvider("b", [_quote("b")])
    result, store, record = _run({"a": first, "b": second}, ["a", "b"])
    assert result["outcome"] == pipeline.OUTCOME_FOUND and result["providers_tried"] == ["a"] and second.calls == 0
    store.assert_called_once()
    assert record.call_args.args[3:] == (pipeline.OUTCOME_FOUND, ["a"], 1)


def test_can_consult_every_provider_when_asked_for_more_evidence():
    first, second = FakeProvider("a", [_quote("a")]), FakeProvider("b", [_quote("b")])
    result, store, _ = _run({"a": first, "b": second}, ["a", "b"], all_providers=True)
    assert result["quotes_kept"] == 2 and store.call_count == 2


def test_a_listing_for_another_product_is_not_kept_and_the_next_provider_is_tried():
    wrong = FakeProvider("a", [_quote("a", title="Nutella Hazelnut Spread 750g")])
    right = FakeProvider("b", [_quote("b")])
    result, store, _ = _run({"a": wrong, "b": right}, ["a", "b"])
    assert result["providers_tried"] == ["a", "b"] and result["quotes_kept"] == 1
    assert store.call_args.args[3].provider == "b"


def test_an_implausible_price_is_stored_but_does_not_count():
    result, store, _ = _run({"a": FakeProvider("a", [_quote("a", price=90.0)])}, ["a"])
    store.assert_called_once()
    assert store.call_args.args[5] is False  # plausible flag
    assert result["outcome"] == pipeline.OUTCOME_NOTHING and result["quotes_kept"] == 0


def test_outcomes_distinguish_not_configured_nothing_found_and_provider_errors():
    nothing, _, _ = _run({"a": FakeProvider("a", [])}, ["a"])
    assert nothing["outcome"] == pipeline.OUTCOME_NOTHING
    unconfigured, _, _ = _run({"a": FakeProvider("a", available=False), "b": FakeProvider("b", unavailable=True)}, ["a", "b"])
    assert unconfigured["outcome"] == pipeline.OUTCOME_NOT_CONFIGURED and unconfigured["providers_tried"] == []
    broken, _, _ = _run({"a": FakeProvider("a", error=ProviderError("boom"))}, ["a"])
    assert broken["outcome"] == pipeline.OUTCOME_ERROR


def test_an_error_in_one_provider_does_not_stop_the_next_one():
    result, _, _ = _run({"a": FakeProvider("a", error=ProviderError("boom")), "b": FakeProvider("b", [_quote("b")])}, ["a", "b"])
    assert result["outcome"] == pipeline.OUTCOME_FOUND


def test_a_foreign_currency_quote_needs_a_verified_rate_to_be_judged():
    conn = MagicMock()
    quote = _quote(price=5.0, currency="EUR")
    with patch.object(pipeline.fx, "convert", return_value=None):
        assert pipeline._plausible(conn, quote, CTX) is None  # unknown, not guessed
    with patch.object(pipeline.fx, "convert", return_value=SimpleNamespace(converted_amount=4.0)):
        assert pipeline._plausible(conn, quote, CTX) is True
    assert pipeline._plausible(conn, quote, ProductContext("p", "x", "JO", "JOD", None)) is None


def test_lookup_missing_prices_isolates_one_products_failure_and_counts_outcomes():
    contexts = [ProductContext(f"p{i}", "Nutella Hazelnut Spread 350g", "JO", "JOD", 3.5) for i in range(3)]
    results = [{"outcome": "FOUND"}, RuntimeError("db"), {"outcome": "NOTHING_FOUND"}]
    conn = MagicMock()
    with patch.object(pipeline, "products_needing_a_price", return_value=contexts) as needing, \
         patch.object(pipeline, "lookup_product", side_effect=results):
        summary = pipeline.lookup_missing_prices(conn, "t1", limit=5, provider_instances={"open_prices": FakeProvider("open_prices")})
    assert summary == {"products_attempted": 2, "candidates": 3, "outcomes": {"FOUND": 1, "NOTHING_FOUND": 1}}
    assert needing.call_args.args[2] == 5
    conn.rollback.assert_called_once()
