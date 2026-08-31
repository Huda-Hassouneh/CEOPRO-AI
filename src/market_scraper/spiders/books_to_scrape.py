"""Approved development-target collector for https://books.toscrape.com/.

Supports the two modes described in the service README:

1. Production-shaped mapped mode -- when ``targets_json`` carries mapped
   product URLs, each target is fetched directly and normalized with full
   tenant/source/job lineage, matched by exact external SKU (UPC) or the
   spec's 0.82 fuzzy-name threshold.
2. Demo catalogue mode -- when there are no mapped targets, the spider
   follows the public catalogue's own pagination from ``start_url`` and
   yields normalized records without any database write. ``max_pages``
   bounds a demo/smoke run (see the ``-a max_pages=1`` example in the
   README's "Safe demo crawl" section).

``start_url`` is restricted to the single approved development domain --
this repository's approved development target is books.toscrape.com, not an
arbitrary site (see MASTER_SPEC_v4.md Section 13 / README "Method
selection").
"""

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

MATCH_THRESHOLD = 0.82


class BooksToScrapeSpider(scrapy.Spider):
    """Collect normalized book listings from the approved sandbox catalogue."""

    name = "books_to_scrape"
    approved_domain = "books.toscrape.com"
    default_start_url = "https://books.toscrape.com/"
    default_source_name = "Books to Scrape Sandbox"

    def __init__(
        self,
        start_url=None,
        targets_json="[]",
        source_name=None,
        collection_method="WEB_SCRAPE",
        source_status="ALLOWED",
        tenant_id=None,
        source_id=None,
        job_id=None,
        max_pages=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.start_url = start_url or self.default_start_url
        start_host = (urlsplit(self.start_url).hostname or "").lower().rstrip(".")
        if start_host != self.approved_domain:
            raise ValueError(
                f"start_url must be an approved {self.approved_domain} URL"
            )
        self.allowed_domains = [self.approved_domain]
        self.targets = json.loads(targets_json)
        for target in self.targets:
            target_host = (urlsplit(target["product_url"]).hostname or "").lower().rstrip(".")
            if target_host != self.approved_domain:
                raise ValueError(
                    f"mapped target must stay on the approved {self.approved_domain} host"
                )
        self.source_name = source_name or self.default_source_name
        self.collection_method = collection_method
        self.source_status = source_status
        self.tenant_id = tenant_id
        self.source_id = source_id
        self.job_id = job_id
        self.max_pages = int(max_pages) if max_pages is not None else None

    # -- entry points ------------------------------------------------

    def _initial_requests(self):
        if self.targets:
            for target in self.targets:
                listing = {
                    "product_name": target.get("product_name"),
                    "price_text": None,
                    "availability_text": None,
                    "rating_classes": [],
                    "image_url": None,
                }
                yield scrapy.Request(
                    target["product_url"],
                    callback=self.parse_product,
                    cb_kwargs={"listing": listing, "target": target},
                    dont_filter=True,
                )
        else:
            yield scrapy.Request(
                self.start_url, callback=self.parse_catalogue, cb_kwargs={"page": 1}
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    # -- demo catalogue mode ------------------------------------------

    def parse_catalogue(self, response, page):
        for card in response.css("article.product_pod"):
            relative_url = card.css("h3 a::attr(href)").get()
            if not relative_url:
                continue
            listing = {
                "product_name": card.css("h3 a::attr(title)").get(),
                "price_text": card.css("p.price_color::text").get(),
                "availability_text": clean_text(
                    " ".join(card.css("p.instock.availability::text").getall())
                ),
                "rating_classes": (card.css("p.star-rating::attr(class)").get() or "").split(),
                "image_url": response.urljoin(
                    card.css("div.image_container img::attr(src)").get() or ""
                ),
            }
            yield scrapy.Request(
                response.urljoin(relative_url),
                callback=self.parse_product,
                cb_kwargs={"listing": listing},
            )

        if self.max_pages and page >= self.max_pages:
            return
        next_relative = response.css("li.next a::attr(href)").get()
        if next_relative:
            yield scrapy.Request(
                response.urljoin(next_relative),
                callback=self.parse_catalogue,
                cb_kwargs={"page": page + 1},
            )

    # -- shared product-detail parsing --------------------------------

    def parse_product(self, response, listing, target=None):
        listing = listing or {}

        product_name = clean_text(
            response.css("div.product_main h1::text").get()
        ) or listing.get("product_name")

        category = clean_text(response.css("ul.breadcrumb li:nth-child(3) a::text").get())

        price_text = clean_text(response.css("p.price_color::text").get()) or listing.get(
            "price_text"
        )
        price_amount, currency = parse_price(price_text)

        availability_text = clean_text(
            " ".join(response.css("p.instock.availability::text").getall())
        ) or listing.get("availability_text")
        is_available = bool(availability_text) and "in stock" in availability_text.lower()
        stock_quantity = parse_stock_quantity(availability_text)

        rating_classes = (
            response.css("div.product_main p.star-rating::attr(class)").get() or ""
        ).split()
        if not rating_classes:
            rating_classes = listing.get("rating_classes") or []
        rating = parse_rating(rating_classes)

        external_id = self._table_value(response, "UPC")
        review_count_text = self._table_value(response, "Number of reviews")
        review_count = int(review_count_text) if (review_count_text or "").isdigit() else None

        description = clean_text(response.css("#product_description ~ p::text").get())

        image_relative = response.css("div.item.active img::attr(src)").get()
        image_url = response.urljoin(image_relative) if image_relative else listing.get(
            "image_url"
        )

        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        safety_flags = scan_external_text(description or "")
        safety_status = "QUARANTINED" if safety_flags else "SAFE"

        record = {
            "source_name": self.source_name,
            "source_type": "web_scrape",
            "collection_method": self.collection_method,
            "source_status": self.source_status,
            "is_exact_data": True,
            "external_id": external_id,
            "product_name": product_name,
            "category": category,
            "description": description,
            "price_amount": price_amount,
            "currency": currency,
            "availability": availability_text,
            "is_available": is_available,
            "stock_quantity": stock_quantity,
            "page_text": None,
            "rating": rating,
            "review_count": review_count,
            "product_url": response.url,
            "image_url": image_url,
            "reviews": [],
            "captured_at": captured_at,
            "safety_status": safety_status,
            "safety_flags": safety_flags,
        }

        if target:
            record.update({
                "tenant_id": self.tenant_id,
                "source_id": self.source_id,
                "job_id": self.job_id,
                "mapping_id": target["mapping_id"],
                "product_id": target["product_id"],
                "global_competitor_id": target["global_competitor_id"],
                "competitor_name": target.get("competitor_name"),
            })
            target_sku = target.get("external_sku")
            if target_sku and external_id and target_sku == external_id:
                match_score, match_method = 1.0, "EXACT_SKU"
            else:
                match_score = similarity(product_name or "", target.get("product_name") or "")
                match_method = "FUZZY_NAME"
                if match_score < MATCH_THRESHOLD:
                    raise ValueError(
                        "mapped product is below the specification's 0.82 "
                        f"fuzzy-name threshold: {match_score:.2f}"
                    )
            record["match_score"] = match_score
            record["match_method"] = match_method

        yield record

    @staticmethod
    def _table_value(response, label):
        return clean_text(
            response.xpath(
                f"//table//tr[th[normalize-space()='{label}']]/td/text()"
            ).get()
        )
