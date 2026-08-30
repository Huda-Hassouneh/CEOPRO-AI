import pytest

from src.market_scraper.collectors import COLLECTORS, resolve_collector
from src.market_scraper.spiders.amazon_paapi import AmazonPricingSpider
from src.market_scraper.spiders.google_places import GooglePlacesSpider


def test_google_places_and_amazon_paapi_are_registered():
    assert COLLECTORS["google_places"].spider is GooglePlacesSpider
    assert COLLECTORS["amazon_paapi"].spider is AmazonPricingSpider


def test_resolve_collector_honors_explicit_collector_key():
    source = {"collector_key": "google_places", "collection_method": "OFFICIAL_API"}
    assert resolve_collector(source).spider is GooglePlacesSpider

    source = {"collector_key": "amazon_paapi", "collection_method": "OFFICIAL_API"}
    assert resolve_collector(source).spider is AmazonPricingSpider


def test_resolve_collector_rejects_unregistered_key():
    with pytest.raises(ValueError, match="no approved collector"):
        resolve_collector({"collector_key": "not_a_real_collector"})
