"""Respectful full-catalogue crawler for the repository's approved demo target."""

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import scrapy

from src.ai.pricing.matching import similarity
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import (
    clean_text,
    parse_price,
    parse_rating,
    parse_stock_quantity,
)


class BooksToScrapeSpider(scrapy.Spider):
    """Collect normalized product observations from books.toscrape.com."""

    name = "books_to_scrape"
    allowed_domains = ["books.toscrape.com"]
    default_start_url = "https://books.toscrape.com/"

    def __init__(
        self,
        start_url=None,
        source_name="Books to Scrape",
        source_status="ALLOWED",
        collection_method="WEB_SCRAPE",
        max_pages=None,
        targets_json=None,
        tenant_id=None,
        source_id=None,
        job_id=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.start_url = start_url or self.default_start_url
        self.source_name = source_name
        self.source_status = source_status
        self.collection_method = collection_method
        self.tenant_id = tenant_id
        self.source_id = source_id
        self.job_id = job_id
        self.targets = json.loads(targets_json) if targets_json else []
        urls = [target["product_url"] for target in self.targets] or [self.start_url]
        if any(urlsplit(url).hostname != self.allowed_domains[0] for url in urls):
            raise ValueError("all URLs must be on the approved books.toscrape.com domain")
        if self.targets and (not tenant_id or not source_id or not job_id):
            raise ValueError("mapped targets require tenant_id, source_id, and job_id")
        self.max_pages = int(max_pages) if max_pages is not None else None
        if self.max_pages is not None and self.max_pages < 1:
            raise ValueError("max_pages must be at least 1")

    def _initial_requests(self):
        if self.targets:
            empty_listing = {
                "product_name": None,
                "price_text": None,
                "availability_text": None,
                "rating_classes": [],
                "image_url": None,
            }
            for target in self.targets:
                yield scrapy.Request(
                    target["product_url"],
                    callback=self.parse_product,
                    cb_kwargs={"listing": empty_listing, "context": target},
                    dont_filter=True,
                )
            return
        yield scrapy.Request(self.start_url, callback=self.parse, cb_kwargs={"page_number": 1})

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse(self, response, page_number=1):
        """Schedule every product detail page, then follow catalogue pagination."""
        cards = response.css("article.product_pod")
        self.logger.info("catalogue page %s: found %s products", page_number, len(cards))

        for card in cards:
            href = card.css("h3 > a::attr(href)").get()
            if not href:
                self.logger.warning("skipping listing card without a product link")
                continue
            listing = {
                "product_name": card.css("h3 > a::attr(title)").get(),
                "price_text": card.css("p.price_color::text").get(),
                "availability_text": clean_text(
                    card.css("p.instock.availability").xpath("string(.)").get()
                ),
                "rating_classes": (
                    card.css("p.star-rating::attr(class)").get() or ""
                ).split(),
                "image_url": response.urljoin(
                    card.css(".image_container img::attr(src)").get() or ""
                ),
            }
            yield response.follow(
                href,
                callback=self.parse_product,
                cb_kwargs={"listing": listing, "context": None},
            )

        next_href = response.css("li.next > a::attr(href)").get()
        if next_href and (self.max_pages is None or page_number < self.max_pages):
            yield response.follow(
                next_href,
                callback=self.parse,
                cb_kwargs={"page_number": page_number + 1},
            )

    def parse_product(self, response, listing, context=None):
        """Build one analytics-ready observation from a product detail page."""
        product_info = self._product_information(response)
        price_text = response.css(".product_main p.price_color::text").get() or listing["price_text"]
        price_amount, currency = parse_price(price_text)
        availability = clean_text(
            response.css(".product_main p.instock.availability").xpath("string(.)").get()
        ) or listing["availability_text"]
        rating_classes = (
            response.css(".product_main p.star-rating::attr(class)").get() or ""
        ).split() or listing["rating_classes"]
        review_count = self._optional_int(product_info.get("Number of reviews"))
        image_path = response.css(".item.active img::attr(src)").get() or listing["image_url"]

        record = {
            "source_name": self.source_name,
            "source_type": "public_website",
            "collection_method": self.collection_method,
            "source_status": self.source_status,
            "is_exact_data": True,
            "external_id": product_info.get("UPC") or (context or {}).get("external_sku"),
            "product_name": clean_text(
                response.css(".product_main h1::text").get()
            ) or listing["product_name"],
            "category": clean_text(
                response.css("ul.breadcrumb li:nth-of-type(3) a::text").get()
            ),
            "description": clean_text(
                response.css("#product_description + p").xpath("string(.)").get()
            ),
            "price_amount": price_amount,
            "original_price_amount": None,
            "currency": currency,
            "discount_percent": None,
            "availability": availability,
            "is_available": bool(availability and "in stock" in availability.lower()),
            "stock_quantity": parse_stock_quantity(
                product_info.get("Availability") or availability
            ),
            "rating": parse_rating(rating_classes),
            "review_count": review_count,
            "product_url": response.url,
            "image_url": response.urljoin(image_path),
            "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        page_text = (clean_text(response.css("body").xpath("string(.)").get()) or "")[:50_000]
        safety_flags = scan_external_text("\n".join(filter(None, (
            record["product_name"], record["category"], record["description"], page_text,
        ))))
        record.update({
            "page_text": page_text or None,
            "safety_status": "QUARANTINED" if safety_flags else "SAFE",
            "safety_flags": safety_flags,
        })
        if context:
            external_sku = str(record["external_id"] or "").lower()
            target_sku = str(context.get("external_sku") or "").lower()
            exact_sku = bool(external_sku and target_sku and external_sku == target_sku)
            match_score = 1.0 if exact_sku else similarity(
                record["product_name"], context.get("product_name") or ""
            )
            if match_score < 0.82:
                raise ValueError("demo product did not meet the 0.82 mapping threshold")
            record.update({
                "tenant_id": self.tenant_id,
                "source_id": self.source_id,
                "job_id": self.job_id,
                "mapping_id": context["mapping_id"],
                "product_id": context["product_id"],
                "global_competitor_id": context["global_competitor_id"],
                "competitor_name": context["competitor_name"],
                "match_score": match_score,
                "match_method": "EXACT_SKU" if exact_sku else "FUZZY_NAME",
                "reviews": [],
            })
        yield record

    @staticmethod
    def _product_information(response):
        information = {}
        for row in response.css("table.table.table-striped tr"):
            key = clean_text(row.css("th::text").get())
            value = clean_text(row.css("td").xpath("string(.)").get())
            if key:
                information[key] = value
        return information

    @staticmethod
    def _optional_int(value):
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
