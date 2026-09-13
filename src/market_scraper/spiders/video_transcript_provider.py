"""
Paid third-party video-transcript collector (Instagram/Facebook video posts).

Fixed to a specific chosen actor: hgservices/instagram-ai-transcript-scraper
(https://apify.com/hgservices/instagram-ai-transcript-scraper) - a real,
live Apify actor (confirmed via web search 2026-09-13: speaker-labeled,
multilingual transcription with automatic language detection, priced
per-second, no external API key beyond the tenant's own Apify token).
apify.com itself is not directly fetchable from this environment's network
egress, so this actor's exact input/output JSON field names were not
independently confirmed against its own schema page - its Apify Console
"Input" tab is described (via search) as taking "Instagram Post URLs", but
the literal JSON key for that field, and the exact output field names,
remain a best-effort guess below, same caveat as every other unconfirmed
field mapping in this codebase (see _default_input()/_build_item()'s own
notes). Verify both against a real run before production use, and use
collector_config["input_overrides"] to correct the request body once
confirmed, without a code change.

Its REST API id uses Apify's owner~actor-name routing (see
social_data_provider.py's own docstring for the "~" vs "/" gotcha):
"hgservices~instagram-ai-transcript-scraper" - this is now the fixed
default (_DEFAULT_ACTOR_ID below), not left unset. Other actors exist in
Apify's Store for the same job (memo23/video-audio-transcriber,
zaver.api/universal-video-audio-transcriber, lergassy/speech-to-text,
almoutasem_nabil/video-transcript-summary, among others) -
collector_config["actor_id"] can still override the default to switch to
one of those without a code change.

Same "paid feature, nothing paid configured yet" contract as
social_data_provider.py/scrape_creators.py: with no
connection_credentials_vault.api_token, __init__ raises before any request
is sent.

One request per target video URL to the configured actor -
run-sync-get-dataset-items, same Apify Actor API shape as
social_data_provider.py.

TikTok is deliberately not a supported platform here, same as
social_data_provider.py/scrape_creators.py.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

import scrapy

from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text
from src.market_scraper.spiders.social_data_provider import PaidProviderNotConfiguredError

_DEFAULT_PROVIDER_BASE_URL = "https://api.apify.com/v2/acts"

# The chosen actor - see this module's own docstring for how it was picked
# and confirmed real. Apify's "~" (not "/") owner/actor-name separator,
# same routing gotcha social_data_provider.py's own default actor ids need.
_DEFAULT_ACTOR_ID = "hgservices~instagram-ai-transcript-scraper"

_PLATFORM_HOSTS = {
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
}


def _platform_for(url: str) -> Optional[str]:
    hostname = (urlsplit(url).hostname or "").lower()
    return _PLATFORM_HOSTS.get(hostname)


def _first_present(record: dict, *keys) -> Optional[object]:
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def _default_input(video_url: str) -> dict:
    """
    Best-effort default input shape for hgservices/instagram-ai-transcript-
    scraper - its Apify Console "Input" tab is described (via search) as
    taking "Instagram Post URLs", but the literal JSON key for that field
    was not independently confirmed (apify.com is not fetchable from this
    environment). Sends several plausible candidate keys at once
    ("videoUrl", "postUrls"/"startUrls" as arrays) so a real run reveals
    which one the actor actually reads; override via
    collector_config["input_overrides"][platform] once confirmed.
    """
    return {
        "videoUrl": video_url, "postUrls": [video_url],
        "startUrls": [{"url": video_url}], "language": "auto",
    }


def _normalize_timestamp(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


class VideoTranscriptProviderSpider(scrapy.Spider):
    """Collect a competitor's video spoken-text transcript plus post metadata.

    Never requests facebook.com/instagram.com directly - the only host
    this spider's allowed_domains permits is the configured provider's own
    API host, same isolation contract as every other paid-provider
    collector in this repo.
    """

    name = "video_transcript_provider"

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
                "video_transcript_provider collector requires "
                "connection_credentials_vault.api_token (a paid provider account) - "
                "not configured, so no request will be sent."
            )
        collector_config = json.loads(collector_config_json or "{}")
        self.actor_id = collector_config.get("actor_id") or _DEFAULT_ACTOR_ID
        self.provider_base_url = collector_config.get("provider_base_url", _DEFAULT_PROVIDER_BASE_URL)
        self.input_overrides = collector_config.get("input_overrides") or {}
        self.allowed_domains = [urlsplit(self.provider_base_url).hostname]

    def _actor_run_url(self) -> str:
        return f"{self.provider_base_url}/{self.actor_id}/run-sync-get-dataset-items?token={self.api_token}"

    def _initial_requests(self):
        for target in self.targets:
            video_url = target.get("product_url")
            if not video_url:
                continue
            platform = _platform_for(video_url)
            if platform is None:
                self.logger.info("no recognized video platform for URL: %s", video_url)
                continue
            payload = self.input_overrides.get(platform) or _default_input(video_url)
            yield scrapy.Request(
                self._actor_run_url(),
                method="POST", headers={"Content-Type": "application/json"},
                body=json.dumps(payload), callback=self.parse_dataset_items,
                cb_kwargs={"target": target, "platform": platform, "video_url": video_url}, dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse_dataset_items(self, response, target, platform, video_url):
        try:
            items = response.json()
        except Exception:
            self.logger.warning("non-JSON response from provider for %s", video_url)
            return
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or not items:
            self.logger.info("no dataset items returned for %s (%s)", target.get("competitor_name"), video_url)
            return
        yield self._build_item(target, platform, video_url, items[0])

    def _build_item(self, target, platform, video_url, record: dict) -> dict:
        transcript = clean_text(
            _first_present(record, "transcript", "transcriptText", "text", "spokenText", "fullText") or ""
        )
        caption = clean_text(
            _first_present(record, "caption", "description", "title") or ""
        )
        safety_flags = scan_external_text(transcript) if transcript else []
        creator_handle = _first_present(
            record, "creator", "authorUsername", "ownerUsername", "channelName", "username", "author",
        )
        view_count = _first_present(record, "viewCount", "videoViewCount", "playCount", "views")
        like_count = _first_present(record, "likesCount", "likeCount", "likes")
        share_count = _first_present(record, "sharesCount", "shareCount", "shares")
        external_id = record.get("id") or record.get("shortCode") or platform
        published_at = _normalize_timestamp(
            _first_present(record, "uploadDate", "date", "publishedAt", "createdAt", "timestamp")
        )
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
            "page_text": transcript or None,
            "rating": None, "review_count": None,
            "like_count": like_count, "share_count": share_count,
            "view_count": view_count, "creator_handle": creator_handle,
            "content_date": published_at,
            "product_url": video_url,
            "image_url": record.get("thumbnailUrl") or record.get("displayUrl") or record.get("imageUrl"),
            "reviews": [], "captured_at": captured_at,
        }
