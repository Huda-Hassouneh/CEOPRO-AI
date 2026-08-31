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
