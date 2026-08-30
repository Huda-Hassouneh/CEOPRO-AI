"""Official Google Places API collector - business reviews, no price data."""

import json
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import scrapy

from src.ai.pricing.matching import similarity
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text

MATCH_THRESHOLD = 0.82

_FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


class GooglePlacesSpider(scrapy.Spider):
    """Collect competitor reviews from the official Google Places API.

    Places has no price/availability data to offer, so every record this
    spider yields has price_amount=currency=None; it still flows through the
    full Tier-2 staging/validation/content-safety pipeline like a
    price-bearing record (market_repository.save_market_record only skips
    the competitor_prices INSERT and price-derived events when price_amount
    is absent - market_observations and review persistence are unconditional).
    Same constructor contract as MarketSourceSpider so cli.py's dispatch
    needs no change, plus credentials_json for the API key (see
    data_access.py::load_source's connection_credentials_vault field).
    allowed_domains is pinned to Google's own API host rather than derived
    from mapped targets, since this spider never requests a target's
    product_url - PublicNetworkBoundaryMiddleware still validates every
    request/response against that one host.
    """

    name = "google_places"

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
            raise ValueError("google_places collector requires connection_credentials_vault.api_key")
        self.allowed_domains = [urlsplit(_FIND_PLACE_URL).hostname]

    def _initial_requests(self):
        for target in self.targets:
            query = target.get("competitor_name") or target.get("product_name")
            if not query:
                continue
            url = (
                f"{_FIND_PLACE_URL}?input={quote(query)}&inputtype=textquery"
                f"&fields=place_id,name&key={self.api_key}"
            )
            yield scrapy.Request(
                url, callback=self.parse_find_place, cb_kwargs={"target": target}, dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse_find_place(self, response, target):
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            self.logger.info("no Places candidate for %s", target.get("competitor_name"))
            return
        target_name = target.get("competitor_name") or ""
        best = max(candidates, key=lambda c: similarity(c.get("name", ""), target_name))
        score = similarity(best.get("name", ""), target_name)
        if score < MATCH_THRESHOLD:
            self.logger.info("Places candidate below match threshold for %s", target_name)
            return
        place_id = best.get("place_id")
        if not place_id:
            return
        url = f"{_DETAILS_URL}?place_id={place_id}&fields=reviews,name&key={self.api_key}"
        yield scrapy.Request(
            url, callback=self.parse_details,
            cb_kwargs={"target": target, "match_score": score, "place_id": place_id},
            dont_filter=True,
        )

    def parse_details(self, response, target, match_score, place_id):
        payload = response.json()
        result = payload.get("result") or {}
        reviews = self._reviews(result.get("reviews") or [])
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        yield {
            "tenant_id": self.tenant_id, "source_id": self.source_id, "job_id": self.job_id,
            "mapping_id": target["mapping_id"], "product_id": target["product_id"],
            "global_competitor_id": target["global_competitor_id"],
            "competitor_name": target["competitor_name"], "source_name": self.source_name,
            "source_type": "official_api", "collection_method": self.collection_method,
            "source_status": "ALLOWED", "is_exact_data": True,
            "match_score": match_score, "match_method": "FUZZY_NAME",
            "safety_status": "SAFE", "safety_flags": [],
            "external_id": place_id,
            "product_name": clean_text(result.get("name")) or target.get("product_name") or target["competitor_name"],
            "category": None, "description": None,
            "price_amount": None, "currency": None,
            "availability": None, "is_available": None, "stock_quantity": None,
            "page_text": None,
            "rating": None, "review_count": len(reviews),
            "product_url": target["product_url"], "image_url": None,
            "reviews": reviews, "captured_at": captured_at,
        }

    @staticmethod
    def _reviews(raw_reviews):
        records = []
        for review in raw_reviews:
            body = clean_text(review.get("text"))
            if not body:
                continue
            safety_flags = scan_external_text(body)
            timestamp = review.get("time")
            review_date = (
                datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
                if isinstance(timestamp, (int, float)) else None
            )
            records.append({
                "external_review_id": f"{review.get('author_name', 'anonymous')}:{timestamp}",
                "review_text": body,
                "reviewer_name": review.get("author_name"),
                "review_rating": review.get("rating"),
                "review_date": review_date,
                "safety_status": "QUARANTINED" if safety_flags else "SAFE",
                "safety_flags": safety_flags,
            })
        return records
