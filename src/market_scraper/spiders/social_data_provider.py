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

Two-stage collection, matching the shared item schema
(sample_output_ready.json) rather than inventing ad-hoc fields:

1. One request per target profile to a "posts" actor - yields each
   returned post's own like_count/share_count/aggregate comment count.
2. Optionally (collector_config["fetch_comments"], default True) one
   further request per post to a "comments" actor, populating `reviews`
   with real per-comment text/author/date plus like_count/reply_count -
   the same shape reviews from every other collector use, just with two
   new optional engagement columns behind them (see the
   20260906010000_add_engagement_metrics_columns.sql migration). Comments
   are a second billed provider call on top of the posts call - disable
   fetch_comments for the cheaper posts-only mode when comment-level
   detail isn't needed.

Per-platform request/response shape (collector_config["actor_ids"]/
["comments_actor_ids"], the run-sync-get-dataset-items input body and
response fields) is a best-effort default matching commonly-published
actor conventions - verify against the provider's actual actor schema
before production use. collector_config["input_overrides"]/
["comments_input_overrides"] are escape hatches to override the built
request per platform without a code change.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

import scrapy

from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text

_DEFAULT_PROVIDER_BASE_URL = "https://api.apify.com/v2/acts"

# Apify's own maintained actors (apify/<name> namespace on the actor's
# store page). The REST API itself, however, requires the owner and actor
# name joined with "~" (a literal "/" in the URL path is a separate path
# segment, not the actor ID) - a real, previously-live bug: using the
# store-page slash form here 404'd ("no API endpoint at this URL") on
# every real call, since /v2/acts/apify/instagram-scraper/... does not
# match Apify's routing, only /v2/acts/apify~instagram-scraper/... does.
# See https://docs.apify.com/api/v2/actor-run-sync-get-dataset-items-post.
_DEFAULT_ACTOR_IDS = {
    "facebook": "apify~facebook-pages-scraper",
    "instagram": "apify~instagram-scraper",
    "tiktok": "apify~tiktok-scraper",
}

# Dedicated comments actors - a second, separately-billed call per post.
_DEFAULT_COMMENTS_ACTOR_IDS = {
    "facebook": "apify~facebook-comments-scraper",
    "instagram": "apify~instagram-comment-scraper",
    "tiktok": "clockworks~tiktok-comments-scraper",
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


def _first_present(record: dict, *keys) -> Optional[object]:
    """First non-None value among candidate field names a provider might use."""
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def _default_input(profile_or_post_url: str, results_limit: int) -> dict:
    """
    Best-effort default input shape (startUrls + a results cap) - real
    actors vary in field names (some want resultsLimit, others maxItems);
    this is a reasonable starting point, not a verified-against-every-actor
    contract. Override via collector_config["input_overrides"]/
    ["comments_input_overrides"][platform].
    """
    return {"startUrls": [{"url": profile_or_post_url}], "resultsLimit": results_limit}


def _normalize_timestamp(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


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
        self.comments_actor_ids = {**_DEFAULT_COMMENTS_ACTOR_IDS, **(collector_config.get("comments_actor_ids") or {})}
        self.input_overrides = collector_config.get("input_overrides") or {}
        self.comments_input_overrides = collector_config.get("comments_input_overrides") or {}
        self.results_limit = collector_config.get("results_limit", 20)
        self.comments_per_post = collector_config.get("comments_per_post", 20)
        self.fetch_comments = collector_config.get("fetch_comments", True)
        self.allowed_domains = [urlsplit(self.provider_base_url).hostname]

    def _actor_run_url(self, actor_id: str) -> str:
        return f"{self.provider_base_url}/{actor_id}/run-sync-get-dataset-items?token={self.api_token}"

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
            yield scrapy.Request(
                self._actor_run_url(self.actor_ids[platform]),
                method="POST", headers={"Content-Type": "application/json"},
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
            posts = response.json()
        except Exception:
            self.logger.warning("non-JSON response from provider for %s", target.get("competitor_name"))
            return
        if not isinstance(posts, list) or not posts:
            self.logger.info("no dataset items returned for %s (%s)", target.get("competitor_name"), platform)
            return

        for post in posts:
            post_url = post.get("url") or post.get("webVideoUrl") or post.get("permalink") or target["product_url"]
            comments_actor = self.comments_actor_ids.get(platform)
            if self.fetch_comments and comments_actor:
                payload = self.comments_input_overrides.get(platform) or _default_input(
                    post_url, self.comments_per_post
                )
                yield scrapy.Request(
                    self._actor_run_url(comments_actor),
                    method="POST", headers={"Content-Type": "application/json"},
                    body=json.dumps(payload), callback=self.parse_comments,
                    cb_kwargs={"target": target, "platform": platform, "post": post, "post_url": post_url},
                    dont_filter=True,
                )
            else:
                yield self._build_item(target, platform, post, post_url, reviews=[])

    def parse_comments(self, response, target, platform, post, post_url):
        try:
            comments = response.json()
        except Exception:
            self.logger.warning("non-JSON comments response for %s", post_url)
            comments = []
        if not isinstance(comments, list):
            comments = []
        yield self._build_item(target, platform, post, post_url, reviews=self._build_reviews(comments))

    def _build_item(self, target, platform, post, post_url, reviews: list) -> dict:
        caption = clean_text(
            post.get("caption") or post.get("text") or post.get("bio") or post.get("description") or ""
        )
        safety_flags = scan_external_text(caption) if caption else []
        like_count = _first_present(post, "likesCount", "like_count", "diggCount", "likes")
        share_count = _first_present(post, "sharesCount", "share_count", "shares")
        comment_count = _first_present(post, "commentsCount", "comment_count", "commentCount")
        external_id = post.get("id") or post.get("shortCode") or post.get("videoId") or platform
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "tenant_id": self.tenant_id, "source_id": self.source_id, "job_id": self.job_id,
            "mapping_id": target["mapping_id"], "product_id": target["product_id"],
            "global_competitor_id": target["global_competitor_id"],
            "competitor_name": target["competitor_name"], "source_name": self.source_name,
            "source_type": "paid_third_party_api", "collection_method": self.collection_method,
            "source_status": "ALLOWED", "is_exact_data": True,
            "match_score": 1.0, "match_method": "DIRECT_PROFILE_URL",
            "safety_status": "QUARANTINED" if safety_flags else "SAFE",
            "safety_flags": safety_flags,
            "external_id": external_id,
            "product_name": target.get("product_name") or target["competitor_name"],
            "category": None, "description": caption or None,
            "price_amount": None, "currency": None,
            "availability": None, "is_available": None, "stock_quantity": None,
            "page_text": caption or None,
            "rating": None,
            "review_count": comment_count if comment_count is not None else (len(reviews) or None),
            "like_count": like_count, "share_count": share_count,
            "product_url": post_url,
            "image_url": post.get("displayUrl") or post.get("thumbnailUrl") or post.get("imageUrl") or post.get("profilePicUrl"),
            "reviews": reviews, "captured_at": captured_at,
        }

    @staticmethod
    def _build_reviews(comments: list) -> list:
        reviews = []
        for index, comment in enumerate(comments):
            text = clean_text(comment.get("text") or comment.get("comment") or "")
            if not text:
                continue
            safety_flags = scan_external_text(text)
            comment_id = comment.get("id") or comment.get("cid") or index
            reviews.append({
                "external_review_id": str(comment_id),
                "review_text": text,
                "reviewer_name": comment.get("ownerUsername") or comment.get("username") or comment.get("author"),
                "review_rating": None,
                "review_date": _normalize_timestamp(
                    _first_present(comment, "timestamp", "createTime", "created_at", "createdAt")
                ),
                "like_count": _first_present(comment, "likesCount", "like_count", "diggCount"),
                "reply_count": _first_present(comment, "repliesCount", "reply_count", "replyCommentTotal", "reply_comment_total"),
                "safety_status": "QUARANTINED" if safety_flags else "SAFE",
                "safety_flags": safety_flags,
            })
        return reviews
