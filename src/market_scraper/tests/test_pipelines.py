import pytest
from scrapy.exceptions import DropItem

from src.market_scraper.pipelines import (
    DeduplicateMarketRecordPipeline,
    ValidateMarketRecordPipeline,
)


def valid_record():
    return {
        "source_name": "Books to Scrape",
        "external_id": "upc-1",
        "product_name": "A Book",
        "product_url": "https://books.toscrape.com/catalogue/a-book/index.html",
        "price_amount": 10.0,
        "currency": "GBP",
        "rating": 4,
    }


def test_validator_accepts_valid_record_and_rejects_missing_price():
    pipeline = ValidateMarketRecordPipeline()
    record = valid_record()
    assert pipeline.process_item(record) is record

    record["price_amount"] = None
    with pytest.raises(DropItem, match="price_amount"):
        pipeline.process_item(record)


def test_deduplicator_uses_source_and_external_id():
    pipeline = DeduplicateMarketRecordPipeline()
    pipeline.open_spider()
    record = valid_record()
    assert pipeline.process_item(record) is record
    with pytest.raises(DropItem, match="duplicate"):
        pipeline.process_item(record.copy())
