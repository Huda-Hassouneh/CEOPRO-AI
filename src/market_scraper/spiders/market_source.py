"""Standards-based collectors for reviewed API, RSS, and JSON-LD sources."""

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import extruct
import scrapy

from src.ai.pricing.matching import similarity
from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text, parse_price

MATCH_THRESHOLD = 0.82
MAX_PAGE_TEXT_LENGTH = 50_000
HTML_SELECTOR_KEYS = {
    "product_name", "price", "currency", "category", "description",
    "availability", "image_url", "external_id", "rating", "review_count", "page_text",
    # Widget-review fallback (see MarketSourceSpider._widget_reviews) - only
    # reached when neither JSON-LD nor microdata produced any reviews.
    # widget_review_container selects each individual review's root element;
    # the other four are CSS selectors RELATIVE to that container, matching
    # a real reviewed widget's DOM on this specific source - never a
    # guessed vendor-wide selector, same "source-reviewed, not invented"
    # discipline as every other key in this set.
    "widget_review_container", "widget_review_text", "widget_reviewer_name",
    "widget_review_rating", "widget_review_date",
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


def _microdata_node_to_jsonld_shape(node):
    """
    extruct's microdata items come back as {"type": "http://schema.org/X",
    "properties": {...}} - not the flat {"@type": "X", ...} shape every
    parser in this file (_is_product, _first, _record, _reviews,
    _normalize_rating) already expects from JSON-LD. Converts recursively
    (a microdata item's own property can itself be a nested itemscope,
    same as JSON-LD nesting) so the SAME parsing logic runs unchanged
    against microdata - this is a shape adapter, not a second parser.
    """
    if not isinstance(node, dict):
        return node
    type_uri = node.get("type") or ""
    type_name = type_uri.rsplit("/", 1)[-1] if type_uri else None
    converted = {"@type": type_name} if type_name else {}
    for key, value in (node.get("properties") or {}).items():
        if isinstance(value, dict):
            converted[key] = _microdata_node_to_jsonld_shape(value)
        elif isinstance(value, list):
            converted[key] = [_microdata_node_to_jsonld_shape(v) for v in value]
        else:
            converted[key] = value
    return converted


def _extract_microdata_products(html_text):
    """
    Real fallback for a page that publishes schema.org Product markup as
    HTML microdata (itemscope/itemprop attributes) instead of, or in
    addition to, JSON-LD - a real, documented alternative schema.org
    serialization some review-widget SEO integrations (e.g. Bazaarvoice's
    "BVSEO" fallback markup) use specifically so search engines can index
    review content that otherwise only renders via client-side JS. extruct
    (github.com/scrapinghub/extruct) does the actual microdata parsing;
    this only walks its output and converts matching Product nodes to the
    shape the rest of this file's real parsing logic already expects.

    Returns [] on any parse failure (malformed HTML extruct can't handle)
    - never raises, matching parse_structured()'s existing degrade-to-
    HTML-selectors-then-error behavior when nothing structured is found.
    """
    try:
        data = extruct.extract(html_text, syntaxes=["microdata"], errors="log")
    except Exception:
        return []
    return [
        converted
        for raw_node in _walk_json(data.get("microdata") or [])
        if isinstance(raw_node, dict) and "properties" in raw_node
        for converted in [_microdata_node_to_jsonld_shape(raw_node)]
        if MarketSourceSpider._is_product(converted)
    ]


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
        if not products:
            # Real fallback, not a guess: some sites (notably review-widget
            # SEO integrations like Bazaarvoice's BVSEO markup) publish
            # schema.org data as HTML microdata instead of JSON-LD - same
            # standard, different serialization. Only tried when JSON-LD
            # found nothing, so a page with real JSON-LD never pays the
            # extra parse cost.
            products.extend(_extract_microdata_products(response.text))
        if not products and self.selectors:
            products.append(self._html_product(response))
        if not products:
            raise ValueError(f"no Product JSON-LD, microdata, or reviewed HTML selectors found at {response.url}")
        for product in products:
            matched_context = self._verify_context(product, context)
            if matched_context:
                yield self._record(product, matched_context, response.url, response=response)
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

    def _record(self, product, context, fallback_url, response=None):
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
        if not reviews and response is not None:
            # Neither JSON-LD nor microdata had review content - the real
            # remaining case a review-widget (Bazaarvoice/Yotpo/Trustpilot-
            # style) that renders plain HTML with no schema.org markup at
            # all produces. Only reachable when render_javascript=True
            # already rendered the widget's JS into `response`'s DOM
            # before parse_structured ran, and only when this source has
            # real, reviewed widget_review_* selectors configured (never a
            # guessed vendor selector - see _widget_reviews()'s docstring).
            reviews = self._widget_reviews(response)
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
            "rating": self._normalize_rating(aggregate) if aggregate else self._float_or_none(_first(product, "rating")),
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
            review_rating = self._normalize_rating(rating) if isinstance(rating, dict) else self._float_or_none(rating)
            records.append({
                "external_review_id": str(_first(review, "@id", "id") or f"{context['mapping_id']}:{index}"),
                "review_text": body,
                "reviewer_name": _first(author, "name") if isinstance(author, dict) else str(author),
                "review_rating": review_rating,
                "review_date": _first(review, "datePublished"),
                "safety_status": "QUARANTINED" if safety_flags else "SAFE",
                "safety_flags": safety_flags,
            })
        return records

    def _widget_reviews(self, response):
        """
        Last-resort review fallback: a client-rendered review widget
        (Bazaarvoice/Yotpo/Trustpilot-style) that renders plain HTML with
        NO schema.org markup at all - neither JSON-LD nor microdata sees
        anything, so there's no structured data to parse, only visible
        DOM text. Only usable with real, reviewed CSS selectors for THIS
        specific source's widget (self.selectors["widget_review_*"],
        validated at __init__ exactly like every other selector in this
        class) - this function never guesses a vendor's class names, and
        returns [] the moment the required selectors aren't configured.

        Requires the page to already be JS-rendered (render_javascript=
        True on this source) - a plain HTTP fetch's DOM never has the
        widget's content in it at all, selectors or not, since the
        widget's whole point is rendering itself client-side after load.

        Rating is parsed as a bare number (self._float_or_none), NOT
        rescaled the way _normalize_rating() rescales a JSON-LD
        aggregateRating - a CSS-extracted rating has no bestRating/
        worstRating scale to read, so a widget using a non-5 scale here
        needs that handled in how the selector's own text is written
        (e.g. a selector that already yields "4.5" not "90"), not
        something this function can infer automatically. A real,
        stated limitation, not a silent wrong answer.
        """
        container_selector = self.selectors.get("widget_review_container")
        text_selector = self.selectors.get("widget_review_text")
        if not container_selector or not text_selector:
            return []

        records = []
        for index, container in enumerate(response.css(container_selector)):
            body = self._css_value(container, text_selector)
            if not body:
                continue
            safety_flags = scan_external_text(body)
            reviewer_name = None
            if self.selectors.get("widget_reviewer_name"):
                reviewer_name = self._css_value(container, self.selectors["widget_reviewer_name"])
            review_rating = None
            if self.selectors.get("widget_review_rating"):
                review_rating = self._float_or_none(self._css_value(container, self.selectors["widget_review_rating"]))
            review_date = None
            if self.selectors.get("widget_review_date"):
                review_date = self._css_value(container, self.selectors["widget_review_date"])
            records.append({
                "external_review_id": f"widget:{index}",
                "review_text": body,
                "reviewer_name": reviewer_name,
                "review_rating": review_rating,
                "review_date": review_date,
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
    def _normalize_rating(rating_obj):
        """
        Schema.org's ratingValue can be on any scale - bestRating/worstRating
        default to 5/1 per spec when absent, but real sites routinely
        override them (confirmed live: impactbattery.com's aggregateRating
        is ratingValue=90 on a bestRating=100/worstRating=0 scale). Taking
        ratingValue at face value silently dropped every such record
        downstream - reviews.review_rating and this pipeline's own
        ValidateMarketRecordPipeline both enforce 0-5, and a bare "90"
        fails that check even though the underlying rating is genuinely a
        perfectly valid 4.5/5. Rescale here instead of assuming 0-5.
        """
        if not isinstance(rating_obj, dict):
            return None
        value = rating_obj.get("ratingValue")
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        try:
            best = float(rating_obj["bestRating"]) if rating_obj.get("bestRating") is not None else 5.0
            worst = float(rating_obj["worstRating"]) if rating_obj.get("worstRating") is not None else 0.0
        except (TypeError, ValueError):
            best, worst = 5.0, 0.0
        if best <= worst:
            return None
        normalized = (value - worst) / (best - worst) * 5.0
        return max(0.0, min(5.0, normalized))

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
