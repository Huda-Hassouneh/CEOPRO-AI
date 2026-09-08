"""
Official Digi-Key Product Information API v4 collector - price and
availability for an exact Digi-Key part number.

Real, confirmed-from-Digi-Key's-own-published-documentation structural
elements (developer.digikey.com/documentation): OAuth2 client-credentials
token exchange at POST https://api.digikey.com/v1/oauth2/token
(client_id/client_secret/grant_type=client_credentials as form data,
response has access_token/expires_in/token_type), the real endpoint GET
https://api.digikey.com/products/v4/search/{productNumber}/productdetails,
and the real required headers (X-DIGIKEY-Client-Id, X-DIGIKEY-Locale-Site/
-Language/-Currency).

Honest, flagged limit - same category as this PR's own note on scrape_
creators.py's Instagram/TikTok field names: the exact JSON response FIELD
NAMES below (UnitPrice, QuantityAvailable, ProductDescription, etc.) are
this module's best-effort reading of Digi-Key's public documentation, not
independently confirmed against a real authenticated call - no
credentials are configured anywhere in this environment, and Digi-Key's
own full response schema wasn't reachable to double-check field-by-field.
_first() (multi-candidate-key lookup, same pattern market_source.py
already uses) is used deliberately everywhere a field is read, so a
close-but-not-exact guess degrades to trying the next candidate name
rather than silently reading nothing - this needs a real credentialed
smoke test before being trusted with real spend/inventory decisions;
collector_config["field_overrides"] (same escape hatch scrape_creators.py
already established) corrects any wrong guess without a code change.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import scrapy

from src.market_scraper.content_safety import scan_external_text
from src.market_scraper.parsing import clean_text

_PRODUCTION_HOST = "api.digikey.com"
# Real, confirmed-from-Digi-Key's-own-docs sandbox: same response
# STRUCTURE as production (real field names, fake data), free self-
# registration, no production-app approval gate - the actual way to
# verify this module's field-name guesses without needing production
# credentials. collector_config["use_sandbox"]=True switches to it.
#
# IMPORTANT, previously wrong in this file's own comments: a Sandbox app
# is a SEPARATE registration from a Production app on developer.digikey.com
# (Digi-Key's own docs: "A Developer creates Sandbox applications, and
# Sandbox apps are only available to the developer creating them") - it
# gets its OWN client_id/client_secret, not the production app's. Passing
# production credentials against sandbox-api.digikey.com (or vice versa)
# is exactly what produces a 401 Unauthorized from fetch_access_token()
# below - register a Sandbox app specifically to get sandbox credentials.
_SANDBOX_HOST = "sandbox-api.digikey.com"
_TOKEN_FETCH_TIMEOUT = 15


def _token_url(host: str) -> str:
    return f"https://{host}/v1/oauth2/token"


def _product_details_url(host: str, product_number: str) -> str:
    return f"https://{host}/products/v4/search/{product_number}/productdetails"


def _first(value, *keys):
    for key in keys:
        if isinstance(value, dict) and value.get(key) not in (None, ""):
            return value[key]
    return None


def fetch_access_token(client_id: str, client_secret: str, host: str = _PRODUCTION_HOST) -> dict:
    """
    Real OAuth2 client-credentials token exchange - stdlib only, same
    "no extra dependency for a pure network call" discipline as
    amazon_paapi.py's own AWS SigV4 implementation. Returns the raw
    {"access_token", "expires_in", "token_type"} response; caching/expiry
    is the caller's job (this function always makes a real call). Pass
    host=_SANDBOX_HOST to exchange against Digi-Key's real sandbox instead
    - but note a Sandbox app is registered separately from a Production
    app and gets its own client_id/client_secret (see _SANDBOX_HOST above);
    a 401 here usually means production credentials were passed against
    the sandbox host, or vice versa.
    """
    body = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(
        _token_url(host), data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=_TOKEN_FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


class DigiKeyPricingSpider(scrapy.Spider):
    """Collect exact-part-number competitor prices from the official
    Product Information API v4. Only exact Digi-Key part numbers are
    collected (ProductDetails is a single-item lookup, not a search), so
    there is no fuzzy-name path here, same shape as amazon_paapi.py."""

    name = "digikey_api"

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
        self.client_id = credentials.get("client_id")
        self.client_secret = credentials.get("client_secret")
        if not all((self.client_id, self.client_secret)):
            raise ValueError(
                "digikey_api collector requires connection_credentials_vault.client_id/client_secret"
            )
        collector_config = json.loads(collector_config_json or "{}")
        self.locale_site = collector_config.get("locale_site", "US")
        self.locale_language = collector_config.get("locale_language", "en")
        self.locale_currency = collector_config.get("locale_currency", "USD")
        self.field_overrides = collector_config.get("field_overrides", {})
        # Real Digi-Key sandbox (sandbox-api.digikey.com) - same response
        # STRUCTURE as production per Digi-Key's own docs, free self-
        # registration, no approval gate. Set True to verify this
        # module's field-name guesses for real before trusting it with
        # production spend, without needing a production app.
        self.host = _SANDBOX_HOST if collector_config.get("use_sandbox") else _PRODUCTION_HOST
        self.allowed_domains = [self.host]
        self._access_token = None
        self._token_expires_at = 0.0

    def _field(self, value, canonical, *default_keys):
        keys = (self.field_overrides.get(canonical),) if canonical in self.field_overrides else default_keys
        return _first(value, *[k for k in keys if k])

    def _bearer_token(self) -> str:
        if self._access_token is None or time.monotonic() >= self._token_expires_at:
            token_response = fetch_access_token(self.client_id, self.client_secret, host=self.host)
            self._access_token = token_response["access_token"]
            # Refresh a little early rather than exactly at expiry, so a
            # slow request in flight never straddles the boundary.
            self._token_expires_at = time.monotonic() + max(0, int(token_response.get("expires_in", 0)) - 30)
        return self._access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._bearer_token()}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "X-DIGIKEY-Locale-Site": self.locale_site,
            "X-DIGIKEY-Locale-Language": self.locale_language,
            "X-DIGIKEY-Locale-Currency": self.locale_currency,
            "Accept": "application/json",
        }

    def _initial_requests(self):
        for target in self.targets:
            part_number = target.get("external_sku")
            if not part_number:
                self.logger.info("skipping target without a Digi-Key part number: %s", target.get("competitor_name"))
                continue
            url = _product_details_url(self.host, urllib.parse.quote(part_number, safe=""))
            yield scrapy.Request(
                url, headers=self._headers(), callback=self.parse_item,
                cb_kwargs={"target": target, "part_number": part_number}, dont_filter=True,
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
        # The response envelope wraps the product under "Product" in some
        # documented examples and returns it at the top level in others -
        # genuinely unconfirmed without a live call, so both are tried.
        product = _first(payload, "Product") or payload
        if not product:
            self.logger.info("no product data for Digi-Key part number %s", part_number)
            return

        price_value = self._field(
            product, "price", "UnitPrice", "unitPrice",
        )
        if price_value is None:
            standard_pricing = self._field(product, "standard_pricing", "StandardPricing", "standardPricing") or []
            if standard_pricing:
                price_value = _first(standard_pricing[0], "UnitPrice", "unitPrice")
        if price_value is None:
            self.logger.info("no price found for Digi-Key part number %s", part_number)
            return

        quantity_available = self._field(product, "quantity_available", "QuantityAvailable", "quantityAvailable")
        description = clean_text(str(
            self._field(product, "description", "ProductDescription", "DetailedDescription", "description") or ""
        ))
        manufacturer = self._field(product, "manufacturer", "Manufacturer", "manufacturer") or {}
        manufacturer_name = clean_text(str(_first(manufacturer, "Value", "Name", "name") or "")) if isinstance(manufacturer, dict) else clean_text(str(manufacturer))
        product_url = self._field(product, "product_url", "ProductUrl", "productUrl") or target["product_url"]
        title = description or manufacturer_name or part_number
        safety_flags = scan_external_text(title)
        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            price_amount = float(str(price_value).replace(",", ""))
        except (TypeError, ValueError):
            self.logger.warning("unparseable price %r for Digi-Key part number %s", price_value, part_number)
            return

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
            "price_amount": price_amount, "currency": self.locale_currency.upper(),
            "availability": str(quantity_available) if quantity_available is not None else "",
            "is_available": bool(quantity_available) if quantity_available is not None else True,
            "stock_quantity": int(quantity_available) if isinstance(quantity_available, (int, float)) else None,
            "page_text": None, "rating": None, "review_count": None,
            "product_url": product_url, "image_url": None,
            "reviews": [], "captured_at": captured_at,
        }
