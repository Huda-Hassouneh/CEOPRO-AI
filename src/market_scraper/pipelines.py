"""Validation and in-run deduplication for collected market records."""

from urllib.parse import urlsplit

from scrapy.exceptions import DropItem


class ValidateMarketRecordPipeline:
    """Reject malformed records before they can reach analytics or storage."""

    required_fields = ("source_name", "product_name", "product_url", "price_amount", "currency")

    def process_item(self, item):
        missing = [field for field in self.required_fields if item.get(field) in (None, "")]
        if missing:
            raise DropItem(f"missing required fields: {', '.join(missing)}")

        if float(item["price_amount"]) < 0:
            raise DropItem("price_amount cannot be negative")
        if len(item["currency"]) != 3 or not item["currency"].isalpha():
            raise DropItem("currency must be a three-letter ISO code")
        if item.get("rating") is not None and not 1 <= int(item["rating"]) <= 5:
            raise DropItem("rating must be between 1 and 5")
        if urlsplit(item["product_url"]).scheme not in {"http", "https"}:
            raise DropItem("product_url must be HTTP(S)")
        return item


class DeduplicateMarketRecordPipeline:
    """Drop duplicate product observations emitted during one crawl."""

    def open_spider(self):
        self.seen = set()

    def process_item(self, item):
        identity = (item.get("source_name"), item.get("external_id") or item["product_url"])
        if identity in self.seen:
            raise DropItem(f"duplicate market record: {identity[1]}")
        self.seen.add(identity)
        return item
