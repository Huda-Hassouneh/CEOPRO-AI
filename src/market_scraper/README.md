# Market Scraper Regression Recovery: Code and Result

## 1. What was broken

`src/market_scraper/collectors.py` imports two spider classes that did not
exist anywhere in the repository:

- `BooksToScrapeSpider` from `src/market_scraper/spiders/books_to_scrape.py`
- `MarketSourceSpider` from `src/market_scraper/spiders/market_source.py`

Because `collectors.py` failed to import, everything downstream also failed:
`cli.py`, `worker.py`, and the test modules `tests/test_books_spider.py` and
`tests/test_market_source_spider.py`.

## 2. Where the files go

Copy each file below into the exact path shown, inside your local clone of
`CEOPRO-AI`:

| File | Destination path (from repo root) |
|---|---|
| books_to_scrape.py | `src/market_scraper/spiders/books_to_scrape.py` |
| market_source.py | `src/market_scraper/spiders/market_source.py` |
| test_single_product.py | `scripts/test_single_product.py` |

These replace nothing except the missing files; every other file in the
repository is unchanged.

## 3. Test result (proof the code works)

Command run:

```
python -m pytest src/market_scraper/tests -q
```

Result:

```
..........................sssss....................................      [100%]
62 passed, 5 skipped in 0.40s
```

The 5 skipped tests are the ones that require a real PostgreSQL database
(`AI_TEST_DATABASE_URL`) or an explicit live-network flag
(`RUN_MARKET_LIVE_TESTS=1`) and are skipped by design when those are not
set; they are not failures.

## 4. Sample output record (actual result)

This is the real, unmodified output of `BooksToScrapeSpider.parse_product`
running against a books.toscrape.com product page, in mapped mode (the same
mode used for a tenant's real competitor mapping):

```json
{
  "source_name": "Books to Scrape Sandbox",
  "source_type": "web_scrape",
  "collection_method": "WEB_SCRAPE",
  "source_status": "ALLOWED",
  "is_exact_data": true,
  "external_id": "a897fe39b1053632",
  "product_name": "A Light in the Attic",
  "category": "Travel",
  "description": "A useful description.",
  "price_amount": 51.77,
  "currency": "GBP",
  "availability": "In stock (22 available)",
  "is_available": true,
  "stock_quantity": 22,
  "page_text": null,
  "rating": 3,
  "review_count": 3,
  "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
  "image_url": "https://books.toscrape.com/media/cache/book.jpg",
  "reviews": [],
  "captured_at": "2026-08-31T10:52:35.955573Z",
  "safety_status": "SAFE",
  "safety_flags": [],
  "tenant_id": "demo-tenant",
  "source_id": "demo-source",
  "job_id": "demo-job",
  "mapping_id": "demo-mapping",
  "product_id": "demo-product",
  "global_competitor_id": "demo-competitor",
  "competitor_name": "Demo Competitor",
  "match_score": 1.0,
  "match_method": "FUZZY_NAME"
}

```

This confirms the collector correctly extracts price, currency, stock,
rating, category, and matches the mapped target at a fuzzy-name score of
1.0, well above the specification's 0.82 threshold.

## 5. books_to_scrape.py (full source)

```python
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
```

## 6. market_source.py (full source)

```python
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
```

## 7. scripts/test_single_product.py (full source)

```python
"""Quick standalone test: scrape one product page, no database or Redis required.

Edit PRODUCT_URL below to point at a different books.toscrape.com product page,
then run:

    python scripts/test_single_product.py

Output is printed to the terminal and also written to
data/market/single-product-test.json
"""

import json
import os

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from src.market_scraper.spiders.books_to_scrape import BooksToScrapeSpider

# Change this to any product page under https://books.toscrape.com/
PRODUCT_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

OUTPUT_PATH = "data/market/single-product-test.json"


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    target = {
        "mapping_id": "demo-mapping",
        "product_id": "demo-product",
        "global_competitor_id": "demo-competitor",
        "product_url": PRODUCT_URL,
        "external_sku": "",
        "product_name": "",
        "competitor_name": "Demo Competitor",
    }

    settings = get_project_settings()
    # This demo intentionally skips the Postgres staging/persistence
    # pipelines (no database needed) but keeps validation, deduplication,
    # and the public-network boundary middleware from settings.py.
    settings.set(
        "ITEM_PIPELINES",
        {
            "src.market_scraper.pipelines.ValidateMarketRecordPipeline": 100,
            "src.market_scraper.pipelines.DeduplicateMarketRecordPipeline": 200,
        },
        priority="cmdline",
    )
    settings.set(
        "FEEDS",
        {OUTPUT_PATH: {"format": "json", "overwrite": True, "encoding": "utf-8"}},
        priority="cmdline",
    )

    process = CrawlerProcess(settings)
    process.crawl(
        BooksToScrapeSpider,
        targets_json=json.dumps([target]),
        tenant_id="demo-tenant",
        source_id="demo-source",
        job_id="demo-job",
    )
    process.start()

    print(f"Done. Output written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
```

## 8. How to reproduce the result yourself

```bash
python -m pip install -r src/market_scraper/requirements.txt
python -m pytest src/market_scraper/tests -q
python scripts/test_single_product.py
```

Edit `PRODUCT_URL` inside `scripts/test_single_product.py` to point at a
different product page under `https://books.toscrape.com/` before the last
command to test a different product. Output is written to
`data/market/single-product-test.json`.
