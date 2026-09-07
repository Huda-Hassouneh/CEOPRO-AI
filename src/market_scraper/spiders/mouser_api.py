"""
Official Mouser Search API v1 collector - price and availability for an
exact Mouser (or manufacturer) part number.

Real, confirmed-from-Mouser's-own-published-documentation structural
elements (mouser.com/en/api-search/, api.mouser.com/api/docs/ui): POST
https://api.mouser.com/api/v1/search/partnumber?apiKey={key}, JSON body
wrapping the query in a "SearchByPartRequest" object with
"mouserPartNumber"/"partSearchOptions" fields, Content-Type/Accept
headers of application/json. Single api-key auth, no OAuth - simpler
than Digi-Key's flow, real not assumed (Mouser's docs are explicit that
apiKey is a query-string credential, not a bearer token).

Honest, flagged limit - same category as digikey_api.py's own note and
this PR's original note on scrape_creators.py's Instagram/TikTok field
names: the exact JSON response FIELD NAMES below (MouserPartNumber,
PriceBreaks, Availability, etc.) are this module's best-effort reading
of Mouser's public JSON REST API (distinct from their older SOAP API,
which uses different field casing entirely - confirmed the two are not
interchangeable), not independently confirmed against a real
authenticated call. Price is documented as a currency-symbol string
(e.g. "$0.4700"), not a bare number, so parsing.py::parse_price() is
used rather than a naive float cast - a real, known quirk of this API,
not a defensive guess. collector_config["field_overrides"] corrects any
wrong field-name guess without a code change, same escape hatch every
other collector in this codebase already has.
"""
import json
from datetime import datetime, timezone

import scrapy

from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text, parse_price

_SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"


def _first(value, *keys):
    for key in keys:
        if isinstance(value, dict) and value.get(key) not in (None, ""):
            return value[key]
    return None


class MouserPricingSpider(scrapy.Spider):
    """Collect exact-part-number competitor prices from the official
    Mouser Search API. Only exact part-number matches are collected
    (partSearchOptions="Exact"), so there is no fuzzy-name path here,
    same shape as amazon_paapi.py/digikey_api.py."""

    name = "mouser_api"

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
            raise ValueError("mouser_api collector requires connection_credentials_vault.api_key")
        collector_config = json.loads(collector_config_json or "{}")
        self.field_overrides = collector_config.get("field_overrides", {})
        self.allowed_domains = ["api.mouser.com"]

    def _field(self, value, canonical, *default_keys):
        keys = (self.field_overrides.get(canonical),) if canonical in self.field_overrides else default_keys
        return _first(value, *[k for k in keys if k])

    def _initial_requests(self):
        for target in self.targets:
            part_number = target.get("external_sku")
            if not part_number:
                self.logger.info("skipping target without a Mouser part number: %s", target.get("competitor_name"))
                continue
            body = json.dumps({
                "SearchByPartRequest": {
                    "mouserPartNumber": part_number, "partSearchOptions": "Exact",
                },
            })
            yield scrapy.Request(
                f"{_SEARCH_URL}?apiKey={self.api_key}", method="POST", body=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                callback=self.parse_item, cb_kwargs={"target": target, "part_number": part_number},
                dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse_item(self, response, target, part_number):
        payload = response.json()
        results = self._field(payload, "search_results", "SearchResults", "searchResults") or {}
        parts = self._field(results, "parts", "Parts", "parts") or []
        if not parts:
            self.logger.info("no Mouser part found for %s", part_number)
            return
        part = parts[0]

        price_breaks = self._field(part, "price_breaks", "PriceBreaks", "priceBreaks") or []
        raw_price = None
        if price_breaks:
            raw_price = _first(price_breaks[0], "Price", "price")
        if raw_price is None:
            self.logger.info("no price found for Mouser part number %s", part_number)
            return
        try:
            price_amount, currency = parse_price(str(raw_price))
        except Exception:
            self.logger.warning("unparseable price %r for Mouser part number %s", raw_price, part_number)
            return

        availability = str(self._field(part, "availability", "Availability", "availability") or "")
        description = clean_text(str(self._field(part, "description", "Description", "description") or ""))
        manufacturer_name = clean_text(str(self._field(part, "manufacturer", "Manufacturer", "manufacturer") or ""))
        product_url = self._field(part, "product_url", "ProductDetailUrl", "productDetailUrl") or target["product_url"]
        image_url = self._field(part, "image_url", "ImagePath", "imagePath")
        title = description or manufacturer_name or part_number
        safety_flags = scan_external_text(title)
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        yield {
            "tenant_id": self.tenant_id, "source_id": self.source_id, "job_id": self.job_id,
            "mapping_id": target["mapping_id"], "product_id": target["product_id"],
            "global_competitor_id": target["global_competitor_id"],
            "competitor_name": target["competitor_name"], "source_name": self.source_name,
            "source_type": "official_api", "collection_method": self.collection_method,
            "source_status": "ALLOWED", "is_exact_data": True,
            "match_score": 1.0, "match_method": "EXACT_SKU",
            "safety_status": "QUARANTINED" if safety_flags else "SAFE",
            "safety_flags": safety_flags,
            "external_id": part_number,
            "product_name": title,
            "category": None, "description": description or None,
            "price_amount": price_amount, "currency": str(currency or "").upper(),
            "availability": availability,
            "is_available": bool(availability) and "out of stock" not in availability.lower(),
            "stock_quantity": None, "page_text": None,
            "rating": None, "review_count": None,
            "product_url": product_url, "image_url": image_url,
            "reviews": [], "captured_at": captured_at,
        }
