"""
Paid third-party social-data provider collector (Instagram/Facebook/TikTok).

Instagram, Facebook, and TikTok offer no public API for competitor
product/engagement data, and each platform's own Terms of Service
prohibits direct automated collection of their pages - this repo does not
scrape them itself (see social_cross_reference.py for the free,
ToS-compliant alternative: finding *mentions* of a competitor via Google's
own index, which Googlebot is explicitly permitted to crawl). This
collector instead wraps a paid third-party provider's REST API - modeled
on Apify's Actor API (https://docs.apify.com/api/v2), which publishes and
maintains actors for all three platforms and is a real, low-cost
(pay-per-use, no monthly minimum) commercially-licensed channel, same
category of "credential-gated, paid, nothing configured yet" collector as
amazon_paapi.py/google_places.py.

Deliberately a "paid feature, nothing paid configured yet" module: with no
connection_credentials_vault.api_token, __init__ raises
PaidProviderNotConfiguredError immediately and never sends a request -
nothing else in a scrape run breaks while this collector alone is
unconfigured, same contract as the existing amazon_paapi/google_places
collectors when their own credentials are missing.

Per-platform request shape (collector_config["actor_ids"], the
run-sync-get-dataset-items input body) is a best-effort default matching
Apify's commonly-published actor conventions - verify against the
provider's actual actor input schema before production use.
collector_config["input_overrides"] is an escape hatch to override the
built default per platform without a code change.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

import scrapy

from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text

_DEFAULT_PROVIDER_BASE_URL = "https://api.apify.com/v2/acts"

# Apify's own maintained actors (apify/<name> namespace) - the provider
# default; override per-tenant via collector_config["actor_ids"] if a
# different actor or provider is preferred.
_DEFAULT_ACTOR_IDS = {
    "facebook": "apify/facebook-pages-scraper",
    "instagram": "apify/instagram-scraper",
    "tiktok": "apify/tiktok-scraper",
}

_PLATFORM_HOSTS = {
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "www.tiktok.com": "tiktok",
}


class PaidProviderNotConfiguredError(ValueError):
    """Raised when this collector is invoked with no provider API token set."""


def _platform_for(url: str) -> Optional[str]:
    hostname = (urlsplit(url).hostname or "").lower()
    return _PLATFORM_HOSTS.get(hostname)


def _default_input(profile_url: str, results_limit: int) -> dict:
    """
    Best-effort default input shape (startUrls + a results cap) - real
    actors vary in field names (some want resultsLimit, others maxItems);
    this is a reasonable starting point, not a verified-against-every-actor
    contract. Override via collector_config["input_overrides"][platform].
    """
    return {"startUrls": [{"url": profile_url}], "resultsLimit": results_limit}


class SocialDataProviderSpider(scrapy.Spider):
    """Collect competitor social-presence data via a paid third-party API.

    Never requests facebook.com/instagram.com/tiktok.com directly - the
    only host this spider's allowed_domains permits is the paid provider's
    own API, exactly like amazon_paapi.py only ever talks to
    webservices.amazon.com. Same constructor contract as every other
    collector in this repo (see collectors.py) so cli.py's dispatch needs
    no change.
    """

    name = "social_data_provider"

    def __init__(
        self,
        source_url,
        source_name,
        collection_method,
        targets_json,
        tenant_id,
        source_id,
        job_id,
        credentials_json="{}",
        render_javascript="false",
        collector_config_json="{}",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.source_url = source_url
        self.source_name = source_name
        self.collection_method = collection_method
        self.targets = json.loads(targets_json)
        self.tenant_id = tenant_id
        self.source_id = source_id
        self.job_id = job_id
        credentials = json.loads(credentials_json or "{}")
        self.api_token = credentials.get("api_token")
        if not self.api_token:
            raise PaidProviderNotConfiguredError(
                "social_data_provider collector requires "
                "connection_credentials_vault.api_token (a paid provider account) - "
                "not configured, so no request will be sent."
            )
        collector_config = json.loads(collector_config_json or "{}")
        self.provider_base_url = collector_config.get("provider_base_url", _DEFAULT_PROVIDER_BASE_URL)
        self.actor_ids = {**_DEFAULT_ACTOR_IDS, **(collector_config.get("actor_ids") or {})}
        self.input_overrides = collector_config.get("input_overrides") or {}
        self.results_limit = collector_config.get("results_limit", 20)
        self.allowed_domains = [urlsplit(self.provider_base_url).hostname]

    def _initial_requests(self):
        for target in self.targets:
            profile_url = target.get("product_url")
            if not profile_url:
                continue
            platform = _platform_for(profile_url)
            if platform is None or platform not in self.actor_ids:
                self.logger.info("no configured provider actor for URL: %s", profile_url)
                continue
            payload = self.input_overrides.get(platform) or _default_input(profile_url, self.results_limit)
            actor_id = self.actor_ids[platform]
            url = f"{self.provider_base_url}/{actor_id}/run-sync-get-dataset-items?token={self.api_token}"
            yield scrapy.Request(
                url, method="POST", headers={"Content-Type": "application/json"},
                body=json.dumps(payload), callback=self.parse_dataset_items,
                cb_kwargs={"target": target, "platform": platform}, dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse_dataset_items(self, response, target, platform):
        try:
            items = response.json()
        except Exception:
            self.logger.warning("non-JSON response from provider for %s", target.get("competitor_name"))
            return
        if not isinstance(items, list) or not items:
            self.logger.info("no dataset items returned for %s (%s)", target.get("competitor_name"), platform)
            return

        record = items[0]
        bio_or_caption = clean_text(
            record.get("caption") or record.get("bio") or record.get("description") or ""
        )
        safety_flags = scan_external_text(bio_or_caption) if bio_or_caption else []
        followers_count = record.get("followersCount") or record.get("fans") or record.get("followerCount")
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        yield {
            "tenant_id": self.tenant_id, "source_id": self.source_id, "job_id": self.job_id,
            "mapping_id": target["mapping_id"], "product_id": target["product_id"],
            "global_competitor_id": target["global_competitor_id"],
            "competitor_name": target["competitor_name"], "source_name": self.source_name,
            "source_type": "paid_third_party_api", "collection_method": self.collection_method,
            "source_status": "ALLOWED", "is_exact_data": True,
            "match_score": 1.0, "match_method": "DIRECT_PROFILE_URL",
            "safety_status": "QUARANTINED" if safety_flags else "SAFE",
            "safety_flags": safety_flags,
            "external_id": record.get("id") or record.get("username") or platform,
            "product_name": target.get("product_name") or target["competitor_name"],
            "category": None, "description": bio_or_caption or None,
            "price_amount": None, "currency": None,
            "availability": None, "is_available": None, "stock_quantity": None,
            "page_text": bio_or_caption or None,
            "rating": None, "review_count": len(items),
            "product_url": target["product_url"],
            "image_url": record.get("profilePicUrl") or record.get("imageUrl"),
            "reviews": [], "captured_at": captured_at,
            # Extra, non-schema key - not read by market_repository.save_market_record's
            # fixed columns, but preserved verbatim in market_observations.raw_payload
            # for anyone downstream who wants the engagement signal.
            "followers_count": followers_count,
        }
