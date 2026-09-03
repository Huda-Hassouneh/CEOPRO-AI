"""Official Amazon Product Advertising API v5 collector - price and availability."""

import hashlib
import hmac
import json
from datetime import datetime, timezone

import scrapy

from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text

_REGION = "us-east-1"
_HOST = "webservices.amazon.com"
_SERVICE = "ProductAdvertisingAPI"
_URI = "/paapi5/getitems"
_TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.GetItems"


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, _REGION)
    k_service = _hmac_sha256(k_region, _SERVICE)
    return _hmac_sha256(k_service, "aws4_request")


def sigv4_headers(payload: str, access_key: str, secret_key: str, now=None) -> dict:
    """Build the AWS Signature Version 4 headers PA-API requires (stdlib only)."""
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_headers = (
        "content-encoding:amz-1.0\n"
        "content-type:application/json; charset=utf-8\n"
        f"host:{_HOST}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{_TARGET}\n"
    )
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    canonical_request = f"POST\n{_URI}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    credential_scope = f"{date_stamp}/{_REGION}/{_SERVICE}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    signature = hmac.new(
        _signing_key(secret_key, date_stamp), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "content-encoding": "amz-1.0",
        "content-type": "application/json; charset=utf-8",
        "x-amz-date": amz_date,
        "x-amz-target": _TARGET,
        "Authorization": authorization,
    }


class AmazonPricingSpider(scrapy.Spider):
    """Collect exact-ASIN competitor prices from the official PA-API v5.

    Signing (AWS Signature Version 4, stdlib hmac/hashlib only, no extra
    dependency) is pure computation done before scrapy.Request is built; the
    actual network I/O still goes through Scrapy's downloader (and
    PublicNetworkBoundaryMiddleware) exactly like any other collector. Only
    exact-ASIN matches are collected - PA-API's GetItems returns that exact
    item or nothing, so there is no fuzzy-name path here.
    """

    name = "amazon_paapi"

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
        self.access_key = credentials.get("access_key")
        self.secret_key = credentials.get("secret_key")
        self.partner_tag = credentials.get("partner_tag")
        if not all((self.access_key, self.secret_key, self.partner_tag)):
            raise ValueError(
                "amazon_paapi collector requires connection_credentials_vault."
                "access_key/secret_key/partner_tag"
            )
        collector_config = json.loads(collector_config_json or "{}")
        self.marketplace = collector_config.get("marketplace", "www.amazon.com")
        self.allowed_domains = [_HOST]

    def _initial_requests(self):
        for target in self.targets:
            asin = target.get("external_sku")
            if not asin:
                self.logger.info("skipping target without an ASIN: %s", target.get("competitor_name"))
                continue
            payload = json.dumps({
                "ItemIds": [asin],
                "Resources": [
                    "Offers.Listings.Price",
                    "Offers.Listings.Availability.Message",
                    "ItemInfo.Title",
                ],
                "PartnerTag": self.partner_tag,
                "PartnerType": "Associates",
                "Marketplace": self.marketplace,
            })
            headers = sigv4_headers(payload, self.access_key, self.secret_key)
            yield scrapy.Request(
                f"https://{_HOST}{_URI}", method="POST", headers=headers, body=payload,
                callback=self.parse_item, cb_kwargs={"target": target, "asin": asin}, dont_filter=True,
            )

    def start_requests(self):
        """Compatibility entry point for Scrapy versions before 2.13."""
        yield from self._initial_requests()

    async def start(self):
        """Async entry point used by modern Scrapy versions."""
        for request in self._initial_requests():
            yield request

    def parse_item(self, response, target, asin):
        payload = response.json()
        items = payload.get("ItemsResult", {}).get("Items") or []
        if not items:
            self.logger.info("no PA-API item for ASIN %s", asin)
            return
        item = items[0]
        listings = item.get("Offers", {}).get("Listings") or []
        if not listings:
            self.logger.info("no active offer listing for ASIN %s", asin)
            return
        listing = listings[0]
        price_info = listing.get("Price") or {}
        if "Amount" not in price_info:
            return
        title = clean_text(
            (item.get("ItemInfo", {}).get("Title", {}) or {}).get("DisplayValue")
        ) or target.get("product_name") or asin
        availability_message = (listing.get("Availability") or {}).get("Message", "")
        safety_flags = scan_external_text(title)
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        yield {
            "tenant_id": self.tenant_id, "source_id": self.source_id, "job_id": self.job_id,
            "mapping_id": target["mapping_id"], "product_id": target["product_id"],
            "global_competitor_id": target["global_competitor_id"],
            "competitor_name": target["competitor_name"], "source_name": self.source_name,
            "source_type": "official_api", "source_platform": "amazon", "collection_method": self.collection_method,
            "source_status": "ALLOWED", "is_exact_data": True,
            "match_score": 1.0, "match_method": "EXACT_SKU",
            "safety_status": "QUARANTINED" if safety_flags else "SAFE",
            "safety_flags": safety_flags,
            "external_id": asin,
            "product_name": title,
            "category": None, "description": None,
            "price_amount": float(price_info["Amount"]),
            "currency": str(price_info.get("Currency") or "").upper(),
            "availability": availability_message,
            "is_available": "unavailable" not in availability_message.lower(),
            "stock_quantity": None, "page_text": None,
            "rating": None, "review_count": None,
            "product_url": item.get("DetailPageURL") or target["product_url"],
            "image_url": None,
            "reviews": [], "captured_at": captured_at,
        }
