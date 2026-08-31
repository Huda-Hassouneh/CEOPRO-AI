"""General-purpose collector for any reviewed, non-official-API source.

Handles the three method-selection outcomes documented in the README, in
priority order: official public API (JSON), public structured data
(JSON-LD), and controlled public web scraping (reviewed CSS selectors under
``data_sources.collector_config.selectors``). Selectors are configuration,
not code -- this spider never hardcodes a single competitor's markup;
a real competitor that needs bespoke behavior selectors cannot express gets
its own dedicated adapter instead (see README "Adding another source").

Every mapped observation is matched against its ``competitor_product_mappings``
target by exact external SKU (score 1.0) or the specification's 0.82
fuzzy-name floor; a match below that floor makes the fetch fail rather than
silently persist an unrelated product.
"""

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import scrapy

from src.ai.pricing.matching import similarity
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text, parse_price

MATCH_THRESHOLD = 0.82


class MarketSourceSpider(scrapy.Spider):
    """Collect normalized records from a reviewed API, JSON-LD, or selector source."""

    name = "standards"

    def __init__(
        self,
        source_url,
        source_name,
        collection_method,
        targets_json,
        tenant_id,
        source_id,
        job_id,
        collector_config_json="{}",
        credentials_json="{}",
        render_javascript="false",
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
        self.collector_config = json.loads(collector_config_json or "{}")
        self.credentials = json.loads(credentials_json or "{}")

        source_host = (urlsplit(source_url).hostname or "").lower().rstrip(".")
        self.allowed_domains = [source_host] if source_host else []
        for target in self.targets:
            target_host = (urlsplit(target["product_url"]).hostname or "").lower().rstrip(".")
            if target_host != source_host:
                raise ValueError(
                    "mapped target must share the source's reviewed host"
                )

    # -- entry points ------------------------------------------------

    def _initial_requests(self):
        if self.collection_method == "OFFICIAL_API":
            yield scrapy.Request(self.source_url, callback=self.parse_api, dont_filter=True)
            return
        for target in self.targets:
            yield scrapy.Request(
                target["product_url"],
                callback=self.parse_structured,
                cb_kwargs={"target": target},
                dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    # -- structured data / reviewed selectors -------------------------

    def parse_structured(self, response, target):
        selectors = self.collector_config.get("selectors")
        if selectors:
            record = self._parse_via_selectors(response, selectors)
            source_type = "web_scrape"
        else:
            record = self._parse_via_jsonld(response)
            source_type = "structured_data"

        match_score, match_method = self._match_single(
            record["product_name"], record.get("external_sku"), target
        )

        safety_text = " ".join(filter(None, [record.get("description"), record.get("page_text")]))
        safety_flags = scan_external_text(safety_text)
        safety_status = "QUARANTINED" if safety_flags else "SAFE"

        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        content_hash = hashlib.sha256(response.body).hexdigest()

        yield {
            "tenant_id": self.tenant_id,
            "source_id": self.source_id,
            "job_id": self.job_id,
            "mapping_id": target["mapping_id"],
            "product_id": target["product_id"],
            "global_competitor_id": target["global_competitor_id"],
            "competitor_name": target.get("competitor_name"),
            "source_name": self.source_name,
            "source_type": source_type,
            "collection_method": self.collection_method,
            "source_status": "ALLOWED",
            "is_exact_data": match_method == "EXACT_SKU",
            "match_score": match_score,
            "match_method": match_method,
            "safety_status": safety_status,
            "safety_flags": safety_flags,
            "external_id": record.get("external_sku"),
            "product_name": record["product_name"],
            "category": record.get("category"),
            "description": record.get("description"),
            "price_amount": record.get("price_amount"),
            "currency": record.get("currency"),
            "availability": record.get("availability"),
            "is_available": record.get("is_available"),
            "stock_quantity": record.get("stock_quantity"),
            "page_text": record.get("page_text"),
            "rating": record.get("rating"),
            "review_count": record.get("review_count"),
            "product_url": response.url,
            "image_url": record.get("image_url"),
            "reviews": record.get("reviews", []),
            "captured_at": captured_at,
            "content_hash": content_hash,
        }

    def _parse_via_jsonld(self, response):
        raw = response.css('script[type="application/ld+json"]::text').get()
        document = json.loads(raw or "{}")
        offers = document.get("offers") or {}
        aggregate = document.get("aggregateRating") or {}
        availability = offers.get("availability") or ""
        price = offers.get("price")

        reviews = []
        for entry in document.get("review") or []:
            rating_value = (entry.get("reviewRating") or {}).get("ratingValue")
            body = clean_text(entry.get("reviewBody"))
            review_flags = scan_external_text(body or "")
            reviews.append({
                "external_review_id": entry.get("@id"),
                "review_text": body,
                "review_rating": rating_value,
                "safety_status": "QUARANTINED" if review_flags else "SAFE",
                "safety_flags": review_flags,
            })

        return {
            "product_name": clean_text(document.get("name")),
            "external_sku": document.get("sku"),
            "category": clean_text(document.get("category")),
            "description": clean_text(document.get("description")),
            "image_url": document.get("image"),
            "price_amount": float(price) if price is not None else None,
            "currency": str(offers["priceCurrency"]).upper() if offers.get("priceCurrency") else None,
            "availability": availability or None,
            "is_available": ("instock" in availability.lower()) if availability else None,
            "stock_quantity": None,
            "page_text": None,
            "rating": float(aggregate["ratingValue"]) if aggregate.get("ratingValue") is not None else None,
            "review_count": int(aggregate["reviewCount"]) if aggregate.get("reviewCount") is not None else None,
            "reviews": reviews,
        }

    def _parse_via_selectors(self, response, selectors):
        def sel(key):
            css = selectors.get(key)
            if not css:
                return None
            return clean_text(" ".join(response.css(css).getall()))

        price_text = sel("price")
        price_amount = currency = None
        if price_text:
            price_amount, currency = parse_price(price_text)

        availability_text = sel("availability")
        rating_text = sel("rating")
        review_count_text = sel("review_count")

        return {
            "product_name": sel("product_name"),
            "external_sku": sel("external_id"),
            "category": sel("category"),
            "description": sel("description"),
            "image_url": sel("image_url"),
            "price_amount": price_amount,
            "currency": currency,
            "availability": availability_text,
            "is_available": ("in stock" in availability_text.lower()) if availability_text else None,
            "stock_quantity": None,
            "page_text": sel("page_text"),
            "rating": float(rating_text) if rating_text else None,
            "review_count": int(review_count_text) if (review_count_text or "").isdigit() else None,
            "reviews": [],
        }

    # -- official JSON API ---------------------------------------------

    def parse_api(self, response):
        payload = json.loads(response.text)
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        content_hash = hashlib.sha256(response.body).hexdigest()

        for product in payload.get("products") or []:
            name = product.get("name")
            sku = product.get("sku")
            try:
                target, match_score, match_method = self._match_any(name, sku)
            except ValueError:
                # An API payload can legitimately list products this tenant
                # has not mapped; skip them rather than fail the whole job.
                continue

            price = product.get("price")
            currency = product.get("currency")
            description = clean_text(product.get("description"))
            safety_flags = scan_external_text(description or "")

            yield {
                "tenant_id": self.tenant_id,
                "source_id": self.source_id,
                "job_id": self.job_id,
                "mapping_id": target["mapping_id"],
                "product_id": target["product_id"],
                "global_competitor_id": target["global_competitor_id"],
                "competitor_name": target.get("competitor_name"),
                "source_name": self.source_name,
                "source_type": "official_api",
                "collection_method": self.collection_method,
                "source_status": "ALLOWED",
                "is_exact_data": match_method == "EXACT_SKU",
                "match_score": match_score,
                "match_method": match_method,
                "safety_status": "QUARANTINED" if safety_flags else "SAFE",
                "safety_flags": safety_flags,
                "external_id": sku,
                "product_name": clean_text(name),
                "category": None,
                "description": description,
                "price_amount": float(price) if price is not None else None,
                "currency": str(currency).upper() if currency else None,
                "availability": None,
                "is_available": None,
                "stock_quantity": None,
                "page_text": None,
                "rating": None,
                "review_count": None,
                "product_url": target["product_url"],
                "image_url": None,
                "reviews": [],
                "captured_at": captured_at,
                "content_hash": content_hash,
            }

    # -- shared matching helpers ----------------------------------------

    @staticmethod
    def _match_single(name, sku, target):
        """Match one fetched product against the one mapped target it was requested for."""
        target_sku = target.get("external_sku")
        if sku and target_sku and sku == target_sku:
            return 1.0, "EXACT_SKU"
        score = similarity(name or "", target.get("product_name") or "")
        if score >= MATCH_THRESHOLD:
            return score, "FUZZY_NAME"
        raise ValueError(
            "mapped product is below the specification's 0.82 fuzzy-name "
            f"threshold: {score:.2f}"
        )

    def _match_any(self, name, sku):
        """Match one API-listed product against whichever mapped target fits best."""
        if sku:
            for target in self.targets:
                if target.get("external_sku") == sku:
                    return target, 1.0, "EXACT_SKU"
        best_target, best_score = None, 0.0
        for target in self.targets:
            score = similarity(name or "", target.get("product_name") or "")
            if score > best_score:
                best_target, best_score = target, score
        if best_target and best_score >= MATCH_THRESHOLD:
            return best_target, best_score, "FUZZY_NAME"
        raise ValueError(
            "no mapped target reaches the specification's 0.82 fuzzy-name "
            f"threshold: {best_score:.2f}"
        )
