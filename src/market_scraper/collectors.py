"""Allowlisted collector registry; database policy chooses capabilities, not arbitrary code."""

from dataclasses import dataclass

from src.market_scraper.spiders.amazon_paapi import AmazonPricingSpider
from src.market_scraper.spiders.books_to_scrape import BooksToScrapeSpider
from src.market_scraper.spiders.google_places import GooglePlacesSpider
from src.market_scraper.spiders.market_source import MarketSourceSpider
from src.market_scraper.spiders.social_data_provider import SocialDataProviderSpider


@dataclass(frozen=True)
class Collector:
    spider: type
    requires_targets: bool = True


COLLECTORS = {
    "books_to_scrape": Collector(BooksToScrapeSpider),
    "standards": Collector(MarketSourceSpider),
    "google_places": Collector(GooglePlacesSpider),
    "amazon_paapi": Collector(AmazonPricingSpider),
    # Paid third-party data provider (Instagram/Facebook/TikTok) - see
    # spiders/social_data_provider.py's own docstring. Requires
    # connection_credentials_vault.api_token; raises
    # PaidProviderNotConfiguredError (not a crash elsewhere) until one is
    # set, same "doesn't break with nothing paid configured" contract as
    # every other credentialed collector here.
    "social_data_provider": Collector(SocialDataProviderSpider),
}

DEFAULT_BY_METHOD = {
    "OFFICIAL_API": "standards",
    "RSS": "standards",
    "STRUCTURED_DATA": "standards",
    "WEB_SCRAPE": "standards",
}


def resolve_collector(source: dict) -> Collector:
    key = source.get("collector_key") or DEFAULT_BY_METHOD.get(source.get("collection_method"))
    if key not in COLLECTORS:
        raise ValueError(f"no approved collector registered for key: {key!r}")
    if source.get("collection_method") == "WEB_SCRAPE" and key == "standards" and not source.get("render_javascript"):
        # Generic web collection is intentionally limited to public JSON-LD.
        # Site-specific HTML selectors belong in a reviewed source adapter.
        return COLLECTORS[key]
    return COLLECTORS[key]
