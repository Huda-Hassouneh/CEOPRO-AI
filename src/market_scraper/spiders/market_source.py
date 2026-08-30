"""Standards-based collectors for reviewed API, RSS, and JSON-LD sources."""

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import scrapy

from src.ai.pricing.matching import similarity
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text, parse_price

MATCH_THRESHOLD = 0.82
MAX_PAGE_TEXT_LENGTH = 50_000
HTML_SELECTOR_KEYS = {
    "product_name", "price", "currency", "category", "description",
    "availability", "image_url", "external_id", "rating", "review_count", "page_text",
}


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _first(value, *keys):
    for key in keys:
        if isinstance(value, dict) and value.get(key) not in (None, ""):
            return value[key]
    return None


class MarketSourceSpider(scrapy.Spider):
    """Collect only reviewed standard formats; custom HTML needs a source spider."""

    name = "market_source"

    def __init__(
        self,
        source_url,
        source_name,
        collection_method,
        targets_json,
        tenant_id,
        source_id,
        job_id,
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
        self.render_javascript = str(render_javascript).lower() == "true"
        self.collector_config = json.loads(collector_config_json)
        selectors = self.collector_config.get("selectors", {})
        if not isinstance(selectors, dict) or set(selectors) - HTML_SELECTOR_KEYS:
            raise ValueError("collector selectors contain unsupported fields")
        if any(not isinstance(value, str) for value in selectors.values()):
            raise ValueError("collector selectors must be CSS selector strings")
        self.selectors = selectors
        hosts = {urlsplit(source_url).hostname}
        hosts.update(urlsplit(target["product_url"]).hostname for target in self.targets)
        if None in hosts or len(hosts) != 1:
            raise ValueError("source and mapped targets must share one reviewed host")
        self.allowed_domains = list(hosts)

    async def start(self):
        for request in self._initial_requests():
            yield request

    def start_requests(self):
        yield from self._initial_requests()

    def _initial_requests(self):
        if self.collection_method in {"OFFICIAL_API", "RSS"}:
            callback = self.parse_api if self.collection_method == "OFFICIAL_API" else self.parse_rss
            yield scrapy.Request(self.source_url, callback=callback)
            return
        for target in self.targets:
            meta = {"playwright": True} if self.render_javascript else {}
            yield scrapy.Request(
                target["product_url"], callback=self.parse_structured,
                cb_kwargs={"context": target}, meta=meta, dont_filter=True,
            )

    def parse_api(self, response):
        payload = response.json()
        candidates = payload if isinstance(payload, list) else _first(payload, "products", "items", "data")
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not isinstance(candidates, list):
            raise ValueError("API response must contain a products/items/data list")
        for candidate in candidates:
            context = self._match_target(candidate)
            if context:
                yield self._record(candidate, context, response.url)

    def parse_rss(self, response):
        for entry in response.xpath("//*[local-name()='item' or local-name()='entry']"):
            entry_url = entry.xpath("string(./*[local-name()='link'][1]/@href)").get()
            entry_url = entry_url or clean_text(
                entry.xpath("string(./*[local-name()='link'][1])").get()
            )
            candidate = {
                "name": clean_text(entry.xpath("string(./*[local-name()='title'][1])").get()),
                "url": entry_url,
                "description": clean_text(entry.xpath("string(./*[local-name()='description' or local-name()='summary'][1])").get()),
                "price": clean_text(entry.xpath("string(.//*[local-name()='price'][1])").get()),
                "currency": clean_text(entry.xpath("string(.//*[local-name()='currency'][1])").get()),
                "sku": clean_text(entry.xpath("string(.//*[local-name()='sku' or local-name()='id'][1])").get()),
            }
            context = self._match_target(candidate)
            if context:
                yield self._record(candidate, context, candidate["url"] or response.url)

    def parse_structured(self, response, context):
        products = []
        for raw in response.css("script[type='application/ld+json']::text").getall():
            try:
                document = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                self.logger.warning("invalid JSON-LD ignored at %s", response.url)
                continue
            products.extend(node for node in _walk_json(document) if self._is_product(node))
        if not products and self.selectors:
            products.append(self._html_product(response))
        if not products:
            raise ValueError(f"no Product JSON-LD or reviewed HTML selectors found at {response.url}")
        for product in products:
            matched_context = self._verify_context(product, context)
            if matched_context:
                yield self._record(product, matched_context, response.url)
                return
        raise ValueError(f"collected product did not meet the {MATCH_THRESHOLD:.2f} mapping threshold")

    def _html_product(self, response):
        """Extract one product with source-reviewed selectors, never guessed selectors."""
        values = {key: self._css_value(response, selector) for key, selector in self.selectors.items()}
        page_text = values.pop("page_text", None)
        return {
            "name": values.get("product_name"), "price": values.get("price"),
            "currency": values.get("currency"), "category": values.get("category"),
            "description": values.get("description"), "availability": values.get("availability"),
            "image": values.get("image_url"), "sku": values.get("external_id"),
            "rating": values.get("rating"), "review_count": values.get("review_count"),
            "page_text": page_text,
        }

    @staticmethod
    def _css_value(response, selector):
        selected = response.css(selector)
        values = selected.getall()
        return clean_text(" ".join(values)) if values else None

    @staticmethod
    def _is_product(node):
        node_type = node.get("@type") if isinstance(node, dict) else None
        return node_type == "Product" or isinstance(node_type, list) and "Product" in node_type

    def _match_target(self, candidate):
        best = None
        best_score = 0.0
        for target in self.targets:
            matched = self._verify_context(candidate, target)
            if matched and matched["match_score"] > best_score:
                best, best_score = matched, matched["match_score"]
                if matched["match_method"] == "EXACT_SKU":
                    return matched
        return best

    @staticmethod
    def _verify_context(candidate, target):
        sku = str(_first(candidate, "sku", "id", "external_id", "product_id") or "").strip().lower()
        target_sku = str(target.get("external_sku") or "").strip().lower()
        if sku and target_sku and sku == target_sku:
            return {**target, "match_score": 1.0, "match_method": "EXACT_SKU"}
        name = clean_text(str(_first(candidate, "name", "title", "product_name") or ""))
        target_name = target.get("product_name") or ""
        score = similarity(name, target_name) if name and target_name else 0.0
        if score < MATCH_THRESHOLD:
            return None
        return {**target, "match_score": score, "match_method": "FUZZY_NAME"}

    def _record(self, product, context, fallback_url):
        offers = _first(product, "offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_value = _first(offers, "price", "lowPrice") or _first(product, "price", "price_amount")
        currency = _first(offers, "priceCurrency") or _first(product, "currency")
        try:
            price_amount = float(str(price_value).replace(",", ""))
        except (TypeError, ValueError):
            price_amount, parsed_currency = parse_price(str(price_value or ""))
            currency = currency or parsed_currency
        aggregate = _first(product, "aggregateRating") or {}
        reviews = self._reviews(_first(product, "review", "reviews"), context)
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        candidate_url = str(_first(product, "url") or fallback_url)
        page_text = (clean_text(str(_first(product, "page_text") or "")) or "")[:MAX_PAGE_TEXT_LENGTH]
        external_text = "\n".join(str(value or "") for value in (
            _first(product, "name", "title", "product_name"),
            _first(product, "category"),
            _first(product, "description", "summary"),
            page_text,
        ))
        safety_flags = scan_external_text(external_text)
        availability = str(_first(offers, "availability") or _first(product, "availability") or "")
        if urlsplit(candidate_url).hostname not in self.allowed_domains:
            candidate_url = fallback_url
        record = {
            "tenant_id": self.tenant_id, "source_id": self.source_id, "job_id": self.job_id,
            "mapping_id": context["mapping_id"], "product_id": context["product_id"],
            "global_competitor_id": context["global_competitor_id"],
            "competitor_name": context["competitor_name"], "source_name": self.source_name,
            "source_type": "public_market_source", "collection_method": self.collection_method,
            "source_status": "ALLOWED", "is_exact_data": True,
            "match_score": context["match_score"], "match_method": context["match_method"],
            "safety_status": "QUARANTINED" if safety_flags else "SAFE",
            "safety_flags": safety_flags,
            "external_id": str(_first(product, "sku", "productID", "id") or "") or None,
            "product_name": clean_text(str(_first(product, "name", "title", "product_name") or "")),
            "category": clean_text(str(_first(product, "category") or "")),
            "description": clean_text(str(_first(product, "description", "summary") or "")),
            "price_amount": price_amount, "currency": str(currency or "").upper(),
            "availability": availability,
            "is_available": "outofstock" not in availability.lower(),
            "stock_quantity": None, "page_text": page_text or None,
            "rating": self._float_or_none(_first(aggregate, "ratingValue") or _first(product, "rating")),
            "review_count": self._int_or_none(
                _first(aggregate, "reviewCount", "ratingCount") or _first(product, "review_count")
            ),
            "product_url": candidate_url,
            "image_url": self._image_url(_first(product, "image")),
            "reviews": reviews, "captured_at": captured_at,
        }
        canonical = json.dumps(record, sort_keys=True, default=str)
        record["content_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return record

    def _reviews(self, value, context):
        values = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        records = []
        for index, review in enumerate(values):
            body = clean_text(str(_first(review, "reviewBody", "description") or ""))
            if not body:
                continue
            rating = _first(review, "reviewRating") or {}
            author = _first(review, "author") or {}
            safety_flags = scan_external_text(body)
            records.append({
                "external_review_id": str(_first(review, "@id", "id") or f"{context['mapping_id']}:{index}"),
                "review_text": body,
                "reviewer_name": _first(author, "name") if isinstance(author, dict) else str(author),
                "review_rating": self._float_or_none(_first(rating, "ratingValue") if isinstance(rating, dict) else rating),
                "review_date": _first(review, "datePublished"),
                "safety_status": "QUARANTINED" if safety_flags else "SAFE",
                "safety_flags": safety_flags,
            })
        return records

    @staticmethod
    def _image_url(image):
        if isinstance(image, list):
            image = image[0] if image else None
        return _first(image, "url") if isinstance(image, dict) else image

    @staticmethod
    def _float_or_none(value):
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_or_none(value):
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
