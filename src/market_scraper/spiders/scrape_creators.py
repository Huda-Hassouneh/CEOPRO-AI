"""
ScrapeCreators paid third-party social-data provider collector.

A genuine alternative to spiders/social_data_provider.py's Apify-shaped
design: ScrapeCreators (https://docs.scrapecreators.com) is a REST API,
not an actor-run platform - GET requests with an `x-api-key` header,
cursor-based pagination (`cursor`/`has_next_page`), and (confirmed live,
2026-09-06, against the real Facebook comments endpoint) billing PER
CALL, not per row returned: one request that returned 10 comments
charged exactly 1 credit (`credits_charged: 1`). That changes the
economics for deep comment threads completely versus a per-row-billed
provider - a post with hundreds of comments costs one credit per ~10
comments paginated, not one credit per comment.

Confirmed real response shape (Facebook comments, live payload checked
against this collector):
    {"success": true, "credits_charged": 1,
     "comments": [{"id", "text", "created_at" (ISO8601 string),
                   "reply_count", "reaction_count",
                   "reactions": {"like": N, "love": N, "haha": N,
                                 "wow": N, "sad": N, "anger": N, ...},
                   "author": {"id", "name", "gender", "short_name"}}],
     "cursor": "...", "has_next_page": true}

Instagram/TikTok endpoint paths below are ScrapeCreators' own documented
URLs (confirmed to exist) but their exact response field names have NOT
been confirmed the same way Facebook's was - collector_config's
"endpoints"/"field_overrides" cover that gap until a real payload is
checked for each, same "best-effort default, verify before production"
convention as spiders/social_data_provider.py.

Deliberately a "paid feature, nothing paid configured yet" module: with
no connection_credentials_vault.api_key, __init__ raises
PaidProviderNotConfiguredError immediately and never sends a request -
same contract as amazon_paapi/google_places/social_data_provider.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode, urlsplit

import scrapy

from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text
from src.market_scraper.spiders.social_data_provider import PaidProviderNotConfiguredError

_DEFAULT_BASE_URL = "https://api.scrapecreators.com"

# Facebook's shape is live-verified (see module docstring). Instagram's
# path is this collector's best guess pending a confirmed example -
# override via collector_config["endpoints"]["instagram"] once checked.
_DEFAULT_ENDPOINTS = {
    "facebook": {"post": "/v1/facebook/post/", "comments": "/v1/facebook/post/comments", "url_param": "url"},
    "instagram": {"post": "/v1/instagram/post/", "comments": "/v1/instagram/post/comments", "url_param": "url"},
    "tiktok": {"post": "/v1/tiktok/video/", "comments": "/v1/tiktok/video/comments", "url_param": "url"},
}

_PLATFORM_HOSTS = {
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "www.tiktok.com": "tiktok",
}


def _platform_for(url: str) -> Optional[str]:
    hostname = (urlsplit(url).hostname or "").lower()
    return _PLATFORM_HOSTS.get(hostname)


def _first_present(record: dict, *keys):
    """First non-None value among candidate field names a platform might use."""
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


class ScrapeCreatorsSpider(scrapy.Spider):
    """Collect one specific post's engagement + full (paginated) comment thread.

    Each target's product_url is treated as a direct post/video URL, not
    a competitor's profile URL - this is the confirmed, working mode:
    monitor a specific competitor post's real comment thread in depth.
    Never requests facebook.com/instagram.com/tiktok.com directly, only
    api.scrapecreators.com. Same constructor contract as every other
    collector in this repo (see collectors.py) so cli.py's dispatch
    needs no change.
    """

    name = "scrape_creators"

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
        self.api_key = credentials.get("api_key")
        if not self.api_key:
            raise PaidProviderNotConfiguredError(
                "scrape_creators collector requires "
                "connection_credentials_vault.api_key (a ScrapeCreators account) - "
                "not configured, so no request will be sent."
            )
        collector_config = json.loads(collector_config_json or "{}")
        self.base_url = collector_config.get("base_url", _DEFAULT_BASE_URL)
        endpoint_overrides = collector_config.get("endpoints") or {}
        self.endpoints = {
            platform: {**_DEFAULT_ENDPOINTS[platform], **(endpoint_overrides.get(platform) or {})}
            for platform in _DEFAULT_ENDPOINTS
        }
        self.field_overrides = collector_config.get("field_overrides") or {}
        self.max_comment_pages = collector_config.get("max_comment_pages", 5)
        self.fetch_comments = collector_config.get("fetch_comments", True)
        self.allowed_domains = [urlsplit(self.base_url).hostname]

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key}

    def _endpoint_url(self, path: str, params: dict) -> str:
        return f"{self.base_url}{path}?{urlencode(params)}"

    def _fields(self, platform: str, key: str, *default_candidates):
        return self.field_overrides.get(platform, {}).get(key, list(default_candidates))

    def _initial_requests(self):
        for target in self.targets:
            post_url = target.get("product_url")
            if not post_url:
                continue
            platform = _platform_for(post_url)
            if platform is None or platform not in self.endpoints:
                self.logger.info("no configured ScrapeCreators endpoint for URL: %s", post_url)
                continue
            endpoint = self.endpoints[platform]
            url = self._endpoint_url(endpoint["post"], {endpoint["url_param"]: post_url})
            yield scrapy.Request(
                url, headers=self._headers(), callback=self.parse_post,
                cb_kwargs={"target": target, "platform": platform, "post_url": post_url}, dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse_post(self, response, target, platform, post_url):
        try:
            post = response.json()
        except Exception:
            self.logger.warning("non-JSON post response for %s", post_url)
            post = {}
        if not post.get("success", True):
            self.logger.info("ScrapeCreators reported failure for %s", post_url)
            return

        if not self.fetch_comments:
            yield self._build_item(target, platform, post, post_url, reviews=[])
            return

        endpoint = self.endpoints[platform]
        url = self._endpoint_url(endpoint["comments"], {endpoint["url_param"]: post_url})
        yield scrapy.Request(
            url, headers=self._headers(), callback=self.parse_comments_page,
            cb_kwargs={
                "target": target, "platform": platform, "post": post, "post_url": post_url,
                "accumulated": [], "page": 1,
            },
            dont_filter=True,
        )

    def parse_comments_page(self, response, target, platform, post, post_url, accumulated, page):
        try:
            payload = response.json()
        except Exception:
            self.logger.warning("non-JSON comments response for %s", post_url)
            payload = {}
        comments = payload.get("comments") or []
        accumulated = accumulated + self._build_reviews(comments, platform)

        cursor = payload.get("cursor")
        if payload.get("has_next_page") and cursor and page < self.max_comment_pages:
            endpoint = self.endpoints[platform]
            url = self._endpoint_url(endpoint["comments"], {endpoint["url_param"]: post_url, "cursor": cursor})
            yield scrapy.Request(
                url, headers=self._headers(), callback=self.parse_comments_page,
                cb_kwargs={
                    "target": target, "platform": platform, "post": post, "post_url": post_url,
                    "accumulated": accumulated, "page": page + 1,
                },
                dont_filter=True,
            )
        else:
            yield self._build_item(target, platform, post, post_url, reviews=accumulated)

    def _build_item(self, target, platform, post, post_url, reviews: list) -> dict:
        caption = clean_text(_first_present(post, "description", "caption", "text") or "")
        safety_flags = scan_external_text(caption) if caption else []
        like_count = _first_present(post, *self._fields(platform, "like_count", "like_count", "likesCount"))
        share_count = _first_present(post, *self._fields(platform, "share_count", "share_count", "sharesCount"))
        comment_count = _first_present(
            post, *self._fields(platform, "comment_count", "comment_count", "commentsCount")
        )
        external_id = post.get("id") or platform
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
            "image_url": post.get("image_url") or post.get("thumbnail_url"),
            "reviews": reviews, "captured_at": captured_at,
        }

    def _build_reviews(self, comments: list, platform: str) -> list:
        reviews = []
        for comment in comments:
            text = clean_text(comment.get("text") or "")
            if not text:
                continue
            safety_flags = scan_external_text(text)
            author = comment.get("author") or {}
            reviews.append({
                "external_review_id": str(comment.get("id")),
                "review_text": text,
                "reviewer_name": author.get("name") or author.get("short_name"),
                "review_rating": None,
                "review_date": comment.get("created_at"),
                "like_count": _first_present(
                    comment,
                    *self._fields(platform, "comment_like_count", "reaction_count", "like_count", "likesCount"),
                ),
                "reply_count": _first_present(
                    comment, *self._fields(platform, "reply_count", "reply_count", "repliesCount")
                ),
                "safety_status": "QUARANTINED" if safety_flags else "SAFE",
                "safety_flags": safety_flags,
                # Not a reviews-table column - rides along in
                # market_observations.raw_payload for anyone downstream
                # who wants the per-reaction-type breakdown (like/love/
                # haha/wow/sad/anger/...), which is real negative-
                # sentiment signal a flat like_count can't give.
                "reactions": comment.get("reactions"),
            })
        return reviews
