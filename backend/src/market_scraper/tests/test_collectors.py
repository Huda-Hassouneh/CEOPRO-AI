import pytest

from src.market_scraper.collectors import COLLECTORS, resolve_collector
from src.market_scraper.spiders.amazon_paapi import AmazonPricingSpider
from src.market_scraper.spiders.digikey_api import DigiKeyPricingSpider
from src.market_scraper.spiders.google_places import GooglePlacesSpider
from src.market_scraper.spiders.mouser_api import MouserPricingSpider
from src.market_scraper.spiders.scrape_creators import ScrapeCreatorsSpider
from src.market_scraper.spiders.social_data_provider import SocialDataProviderSpider


def test_google_places_and_amazon_paapi_are_registered():
    assert COLLECTORS["google_places"].spider is GooglePlacesSpider
    assert COLLECTORS["amazon_paapi"].spider is AmazonPricingSpider


def test_digikey_and_mouser_are_registered():
    assert COLLECTORS["digikey_api"].spider is DigiKeyPricingSpider
    assert COLLECTORS["mouser_api"].spider is MouserPricingSpider


def test_social_data_provider_is_registered():
    assert COLLECTORS["social_data_provider"].spider is SocialDataProviderSpider


def test_scrape_creators_is_registered():
    assert COLLECTORS["scrape_creators"].spider is ScrapeCreatorsSpider


def test_resolve_collector_honors_explicit_collector_key():
    source = {"collector_key": "google_places", "collection_method": "OFFICIAL_API"}
    assert resolve_collector(source).spider is GooglePlacesSpider

    source = {"collector_key": "amazon_paapi", "collection_method": "OFFICIAL_API"}
    assert resolve_collector(source).spider is AmazonPricingSpider


def test_resolve_collector_rejects_unregistered_key():
    with pytest.raises(ValueError, match="no approved collector"):
        resolve_collector({"collector_key": "not_a_real_collector"})
