"""
Paid third-party data-provider collector - Instagram/Facebook/TikTok.

Why this collector exists and why it's shaped the way it is: none of these
three platforms offers a public API exposing a competitor's own product/
post data the way Amazon's PA-API or Google's Places API do (see
amazon_paapi.py/google_places.py), and their Terms of Service explicitly
prohibit automated collection of their pages - this repository does not,
and will not, scrape those platforms' HTML directly or attempt to evade
their bot detection. Instead this wraps a licensed, managed third-party
data provider's own REST API (modeled here on Apify's Actor API -
https://docs.apify.com/api/v2 - since it's a single consistent request
pattern across many pre-built platform-specific "Actors", including
published ones for Instagram, Facebook Pages, and TikTok); the provider,
not this codebase, is the one taking on the compliance relationship with
each platform.

This is real, callable code, not a stub - but it is a "paid feature"
section in the sense CEOPRO's own team asked for: with no
connection_credentials_vault.api_token configured, __init__ raises
PaidProviderNotConfiguredError immediately and no request is ever built or
sent. Nothing elsewhere in the pipeline breaks because of that - exactly
like amazon_paapi.py/google_places.py's existing missing-credentials
behavior, and like every other collector, this one only ever runs at all
once a human has approved its data_sources row (cli.py's run_collection()
already requires policy_status='ALLOWED' plus approval_reference/
approved_at/privacy_reviewed_at before ANY collector executes - this one
is not exempt from that gate).

Known limitation, flagged rather than silently assumed correct: the
per-platform request bodies in _run_input() below are a best-effort
default based on the input shape Apify's own published actors for these
platforms commonly document (directUrls/startUrls/profiles). Actor input
schemas are the provider's to change, and multiple competing community
actors exist per platform with different shapes - verify against the
actual actor's current input schema (visible on its Apify Store page)
before relying on this in production, or override entirely via
collector_config.run_input_template. actor_id itself is fully overridable
per data_sources row via collector_config.actor_id, so switching provider/
actor - or a different paid provider's API entirely, if this repo's
Apify-specific request shape doesn't fit - never requires a code change,
matching collectors.py's "database policy chooses capabilities" design.
"""

import json
from datetime import datetime, timezone

import scrapy

from src.ai.pricing.matching import similarity
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text

MATCH_THRESHOLD = 0.82

_APIFY_HOST = "api.apify.com"
_RUN_SYNC_URL_TEMPLATE = "https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"

# One published Apify Actor per platform - see this module's own docstring
# for why these exact IDs are a starting point, not a verified guarantee.
DEFAULT_ACTORS = {
    "instagram": "apify/instagram-scraper",
    "facebook": "apify/facebook-pages-scraper",
    "tiktok": "clockworks/tiktok-scraper",
}


class PaidProviderNotConfiguredError(ValueError):
    """Raised when this collector is invoked without a paid data-provider API token, or an unrecognized platform."""


class SocialDataProviderSpider(scrapy.Spider):
    """
    Collects competitor posts/profile data from Instagram, Facebook, or
    TikTok via a paid third-party provider's REST API - never directly
    from the platform itself. Same constructor contract as
    AmazonPricingSpider/GooglePlacesSpider so cli.py's dispatch needs no
    change: credentials_json carries the provider API token,
    collector_config_json carries which platform/actor to use.

    allowed_domains is pinned to the provider's own API host
    (api.apify.com), never to instagram.com/facebook.com/tiktok.com -
    PublicNetworkBoundaryMiddleware enforces that this collector can only
    ever talk to the paid provider, structurally, not just by convention.
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
                "social_data_provider collector requires connection_credentials_vault.api_token "
                "(a paid data-provider API token, e.g. an Apify account) - this collector is not "
                "usable until one is configured, and no request is ever sent without it. See "
                "src/market_scraper/README.md's 'Paid social data provider' section for setup."
            )

        collector_config = json.loads(collector_config_json or "{}")
        self.platform = collector_config.get("platform")
        if self.platform not in DEFAULT_ACTORS:
            raise PaidProviderNotConfiguredError(
                f"social_data_provider collector requires collector_config.platform to be one of "
                f"{sorted(DEFAULT_ACTORS)}, got {self.platform!r}."
            )
        self.actor_id = collector_config.get("actor_id") or DEFAULT_ACTORS[self.platform]
        self.run_input_template = collector_config.get("run_input_template")
        self.allowed_domains = [_APIFY_HOST]

    def _run_input(self, handle: str) -> dict:
        if self.run_input_template:
            # Caller-supplied override (see this module's docstring on why
            # the defaults below may not match every actor). "{handle}" is
            # substituted into any string value found at any depth.
            return json.loads(json.dumps(self.run_input_template).replace("{handle}", handle))
        if self.platform == "instagram":
            return {"directUrls": [f"https://www.instagram.com/{handle}/"], "resultsLimit": 30}
        if self.platform == "facebook":
            return {"startUrls": [{"url": f"https://www.facebook.com/{handle}/"}], "resultsLimit": 30}
        return {"profiles": [handle], "resultsPerPage": 30}  # tiktok

    def _initial_requests(self):
        for target in self.targets:
            handle = target.get("external_sku") or target.get("competitor_name")
            if not handle:
                self.logger.info("skipping target without a profile/page handle: %s", target.get("mapping_id"))
                continue
            url = f"{_RUN_SYNC_URL_TEMPLATE.format(actor_id=self.actor_id)}?token={self.api_token}"
            yield scrapy.Request(
                url, method="POST", headers={"Content-Type": "application/json"},
                body=json.dumps(self._run_input(handle)),
                callback=self.parse_items, cb_kwargs={"target": target}, dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse_items(self, response, target):
        try:
            items = response.json()
        except (json.JSONDecodeError, AttributeError):
            self.logger.warning("non-JSON %s response for %s", self.platform, target.get("competitor_name"))
            return
        if not isinstance(items, list):
            self.logger.warning("unexpected %s dataset shape for %s", self.platform, target.get("competitor_name"))
            return
        target_name = target.get("competitor_name") or ""
        for raw_item in items:
            record = self._normalize(raw_item, target, target_name)
            if record is not None:
                yield record

    def _normalize(self, raw_item: dict, target: dict, target_name: str):
        name_for_match = (
            clean_text(raw_item.get("ownerUsername") or raw_item.get("authorName") or raw_item.get("pageName"))
            or target_name
        )
        score = similarity(name_for_match, target_name)
        if score < MATCH_THRESHOLD:
            return None

        external_id = str(raw_item.get("id") or raw_item.get("shortCode") or raw_item.get("url") or "")
        if not external_id:
            return None

        title = clean_text(raw_item.get("caption") or raw_item.get("text") or raw_item.get("title"))
        page_text = (title or "")[:50_000]
        safety_flags = scan_external_text(page_text) if page_text else []
        price_amount, currency = self._extract_price(raw_item)
        engagement = self._extract_engagement(raw_item)
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return {
            "tenant_id": self.tenant_id, "source_id": self.source_id, "job_id": self.job_id,
            "mapping_id": target["mapping_id"], "product_id": target["product_id"],
            "global_competitor_id": target["global_competitor_id"],
            "competitor_name": target["competitor_name"], "source_name": self.source_name,
            "source_type": "paid_data_provider", "source_platform": self.platform,
            "collection_method": self.collection_method,
            "source_status": "ALLOWED", "is_exact_data": False,
            "match_score": score, "match_method": "FUZZY_NAME",
            "safety_status": "QUARANTINED" if safety_flags else "SAFE",
            "safety_flags": safety_flags,
            "external_id": external_id,
            "product_name": title or target.get("product_name") or target["competitor_name"],
            "category": None, "description": None,
            "price_amount": price_amount, "currency": currency,
            "availability": None, "is_available": None, "stock_quantity": None,
            "page_text": page_text or None,
            "rating": None, "review_count": None,
            "product_url": raw_item.get("url") or target["product_url"],
            "image_url": raw_item.get("displayUrl") or raw_item.get("imageUrl"),
            "reviews": [], "captured_at": captured_at,
            **engagement,
        }

    @staticmethod
    def _extract_engagement(raw_item: dict) -> dict:
        """
        Social engagement signals - the whole reason a post/profile scrape
        is worth more than a plain product listing. Field names are the
        common ones across Instagram/TikTok/Facebook actor outputs (e.g.
        Apify's own instagram-scraper/tiktok-scraper/facebook-pages-
        scraper), tried with graceful fallbacks - same "best-effort
        default, verify against the real actor schema" caveat as this
        module's own docstring and _run_input() already carry; a field
        this specific actor doesn't provide is simply None, never guessed.
        """
        author_name = raw_item.get("ownerFullName") or raw_item.get("authorName") or raw_item.get("pageName")
        author_meta = raw_item.get("authorMeta") if isinstance(raw_item.get("authorMeta"), dict) else {}
        author_handle = raw_item.get("ownerUsername") or author_meta.get("name")
        hashtags = raw_item.get("hashtags") or raw_item.get("tags") or []
        mentions = raw_item.get("mentions") or raw_item.get("taggedUsers") or []
        published_raw = raw_item.get("timestamp") or raw_item.get("publishedAt") or raw_item.get("createTime")
        published_at = None
        if isinstance(published_raw, str):
            published_at = published_raw
        elif isinstance(published_raw, (int, float)):
            published_at = datetime.fromtimestamp(published_raw, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "author_name": clean_text(author_name) if author_name else None,
            "author_handle": author_handle,
            "likes_count": raw_item.get("likesCount") or raw_item.get("diggCount") or raw_item.get("likes"),
            "comments_count": raw_item.get("commentsCount") or raw_item.get("commentCount"),
            "shares_count": raw_item.get("sharesCount") or raw_item.get("shareCount"),
            "views_count": raw_item.get("videoViewCount") or raw_item.get("playCount") or raw_item.get("viewsCount"),
            "hashtags": hashtags if isinstance(hashtags, list) else [],
            "mentions": mentions if isinstance(mentions, list) else [],
            "media_type": raw_item.get("type") or raw_item.get("mediaType"),
            "published_at": published_at,
            "engagement_captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @staticmethod
    def _extract_price(raw_item: dict):
        """
        A public post/profile scrape rarely carries a structured price -
        only populated if the specific actor/post happens to surface one
        (e.g. a Facebook Marketplace-style listing). None/None is the
        honest default, same as GooglePlacesSpider's price fields.
        """
        raw_price = raw_item.get("price")
        if raw_price is None:
            return None, None
        try:
            currency = str(raw_item.get("priceCurrency") or "").upper() or None
            return float(raw_price), currency
        except (TypeError, ValueError):
            return None, None
