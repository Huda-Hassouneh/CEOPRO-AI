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


def test_validator_accepts_review_only_record_with_no_price_or_currency():
    """Google Places (and any other reviews-only collector) has no price to report."""
    pipeline = ValidateMarketRecordPipeline()
    record = valid_record()
    record["price_amount"] = None
    record["currency"] = None
    assert pipeline.process_item(record) is record


def test_validator_rejects_price_without_currency_or_currency_without_price():
    pipeline = ValidateMarketRecordPipeline()
    price_only = valid_record()
    price_only["currency"] = None
    with pytest.raises(DropItem, match="price_amount and currency"):
        pipeline.process_item(price_only)

    currency_only = valid_record()
    currency_only["price_amount"] = None
    with pytest.raises(DropItem, match="price_amount and currency"):
        pipeline.process_item(currency_only)


def test_deduplicator_uses_mapping_id_before_external_id():
    pipeline = DeduplicateMarketRecordPipeline()
    pipeline.open_spider()
    record = valid_record()
    assert pipeline.process_item(record) is record
    second_mapping = record.copy()
    second_mapping["mapping_id"] = "mapping-2"
    assert pipeline.process_item(second_mapping) is second_mapping
    duplicate_mapping = record.copy()
    duplicate_mapping["mapping_id"] = "mapping-2"
    with pytest.raises(DropItem, match="duplicate"):
        pipeline.process_item(duplicate_mapping)
