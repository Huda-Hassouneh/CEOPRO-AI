"""
Price sources. Each provider turns one ProductContext into PriceQuotes; none
decides whether a quote is good enough to keep (pipeline.py does, with
matching.py) and none raises for "nothing found" - only ProviderUnavailable
(not set up here) or ProviderError (set up but the call failed).

  open_prices     Open Food Facts' public Open Prices data. No key. Groceries
                  and packaged goods only; crowd-sourced shelf prices.
  web_offers      Any seller's public product page found through the
                  configured web search: reads its schema.org Product/Offer
                  data (price, currency, seller, star rating, review count).
                  Needs a search provider (market_scraper/web_search.py).
                  Honours robots.txt, public addresses only, no logins.
  serpapi_shopping  Google Shopping results through SerpAPI (paid, opt in with
                  SERPAPI_API_KEY): price, seller, rating, review count.

FLAGGED, NOT HIDDEN: the Open Prices and SerpAPI response field names below
come from the vendors' public documentation and have not been exercised
against a live key from this environment; parsing is tolerant (missing or
renamed fields yield no quote, never a crash or an invented value), and a
first real run should confirm them.
"""
import json
import logging
import os
import re
import time
from typing import Callable, List, Optional
from urllib.parse import quote, urlsplit

import httpx

from src.ai.research import page_reader
from src.market_scraper import web_search
from src.market_scraper.iso_countries import country_name
from src.market_scraper.network_security import UnsafeTargetError, resolve_public_addresses
from src.market_scraper.price_lookup import matching
from src.market_scraper.price_lookup.models import PriceQuote, ProductContext, ProviderError, ProviderUnavailable

logger = logging.getLogger("KEEL_PRICE_LOOKUP")
TIMEOUT = float(os.getenv("PRICE_LOOKUP_TIMEOUT_SECONDS", "15"))
USER_AGENT = os.getenv("MARKET_RESEARCH_USER_AGENT", "KEEL-MarketResearch/1.0")

# Currency a price symbol/word stands for when a listing shows no ISO code.
_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "د.أ": "JOD", "JD": "JOD", "SAR": "SAR", "AED": "AED", "ر.س": "SAR", "د.إ": "AED"}

JsonGet = Callable[[str, dict], dict]


def _json_get(url: str, params: dict, attempts: int = 2) -> dict:
    """GET JSON. One retry for a transient failure (timeout, connection error, 5xx):
    free public services such as Open Food Facts answer 503 now and then. A paid
    provider (SerpAPI) is paid from the company's Data Credits, once per attempt."""
    from src.market_scraper.provider_billing import metered_request

    return metered_request(url, lambda: _json_get_once(url, params, attempts))


def _json_get_once(url: str, params: dict, attempts: int) -> dict:
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            response = httpx.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
            if response.status_code >= 500 and attempt + 1 < attempts:
                time.sleep(1.5)
                continue
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(type(exc).__name__) from exc
    raise ProviderError(type(last).__name__ if last else "unreachable") from last


def _number(value) -> Optional[float]:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _rating(value) -> Optional[float]:
    number = _number(value)
    return round(number, 2) if number is not None and 0 <= number <= 5 else None


def _count(value) -> Optional[int]:
    number = _number(value)
    return int(number) if number is not None else None


def _older_than_limit(iso_date: str) -> bool:
    from datetime import date, timedelta
    try:
        seen = date.fromisoformat(iso_date)
    except ValueError:
        return False  # unparseable date: keep, the price itself is still real
    return seen < date.today() - timedelta(days=int(os.getenv("PRICE_LOOKUP_MAX_AGE_DAYS", "365")))


def currency_from_text(text: Optional[str]) -> Optional[str]:
    """ISO currency for a displayed price like "$12.99" / "JD 4.5"; None if unrecognised."""
    for symbol, code in _SYMBOLS.items():
        if symbol in (text or ""):
            return code
    match = re.search(r"\b[A-Z]{3}\b", text or "")
    return match.group() if match else None


# ---------------------------------------------------------------- Open Prices

# Open Food Facts' search-a-licious service; the legacy cgi/search.pl endpoint answers 503 under load.
OFF_SEARCH_URL = "https://search.openfoodfacts.org/search"
OPEN_PRICES_URL = "https://prices.openfoodfacts.org/api/v1/prices"


class OpenPrices:
    name = "open_prices"
    MAX_PRODUCTS = 3
    SEARCH_PAGE_SIZE = 20
    PRICES_PER_PRODUCT = 5

    def __init__(self, get: JsonGet = _json_get):
        self._get = get

    def available(self) -> bool:
        return True

    def _candidates(self, ctx: ProductContext) -> List[tuple]:
        """[(barcode, title)] worth a price query. An exact barcode needs no search and
        is trusted as the product itself; otherwise the name is searched and only hits
        whose title (brand + name + pack size) really matches our product are kept -
        the price service has no name filter, so every kept hit costs one call."""
        if ctx.barcode and 8 <= len(ctx.barcode) <= 14:
            return [(ctx.barcode, ctx.name)]
        # Search by the name's words only: a size in the query ("400g") matches unrelated products
        # that merely carry that size, and the size is checked below against each hit's own pack size.
        words = re.sub(r"\d+(?:[.,]\d+)?\s*(?:kg|g|mg|ml|cl|l|oz|lb|pcs|pc)\b", " ", ctx.name, flags=re.I).strip() or ctx.name
        found = self._get(OFF_SEARCH_URL, {"q": words, "page_size": self.SEARCH_PAGE_SIZE, "fields": "code,product_name,brands,quantity"})
        kept: List[tuple] = []
        for product in found.get("hits") or []:
            code, title = product.get("code"), product.get("product_name") or ""
            if not code or not title:
                continue
            brands = product.get("brands")
            brand = (brands[0] if isinstance(brands, list) and brands else str(brands or "").split(",")[0]).strip()
            title = f"{brand} {title}".strip() if brand and brand.lower() not in title.lower() else title
            if product.get("quantity"):
                title = f"{title} {product['quantity']}"  # the pack size is what tells 350g from 750g
            if matching.is_match(matching.match_score(ctx.name, title)):
                kept.append((code, title))
            if len(kept) >= self.MAX_PRODUCTS:
                break
        return kept

    def search(self, ctx: ProductContext) -> List[PriceQuote]:
        quotes: List[PriceQuote] = []
        for code, title in self._candidates(ctx):
            payload = self._get(OPEN_PRICES_URL, {"product_code": code, "order_by": "-date", "size": self.PRICES_PER_PRODUCT})
            for item in payload.get("items") or []:
                price, currency = _number(item.get("price")), (item.get("currency") or "").upper()
                if price is None or len(currency) != 3:
                    continue
                location = item.get("location") or {}
                country = (location.get("osm_address_country_code") or "").upper()
                if ctx.country_code and country and country != ctx.country_code.upper():
                    continue  # a price in another country is not this market's price
                seen_on = str(item.get("date") or "")[:10] or None
                if seen_on and _older_than_limit(seen_on):
                    continue  # a shelf price from years ago is not today's market
                quotes.append(PriceQuote(
                    provider=self.name, title=title, price=price, currency=currency,
                    seller=location.get("osm_name"), url=f"https://world.openfoodfacts.org/product/{quote(str(code))}",
                    observed_on=seen_on,
                ))
        return quotes


# ----------------------------------------------------------------- Web offers

_LD_JSON = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_META = re.compile(r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']', re.I)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _types(node: dict) -> set:
    raw = node.get("@type")
    return {raw} if isinstance(raw, str) else set(raw) if isinstance(raw, list) else set()


def extract_offers(html: str, page_url: str) -> List[PriceQuote]:
    """Priced schema.org Product/Offer entries on one page (JSON-LD first, then
    Open Graph product meta tags). Prices without a currency are dropped -
    a number with no unit is not a price."""
    quotes: List[PriceQuote] = []
    host = (urlsplit(page_url).hostname or "").removeprefix("www.")
    for raw in _LD_JSON.findall(html or ""):
        try:
            document = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(document):
            if "Product" not in _types(node):
                continue
            rating = node.get("aggregateRating") if isinstance(node.get("aggregateRating"), dict) else {}
            offers = node.get("offers")
            for offer in (offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []):
                price = _number(offer.get("price", offer.get("lowPrice")))
                currency = (offer.get("priceCurrency") or "").upper()
                if price is None or len(currency) != 3:
                    continue
                seller = offer.get("seller") if isinstance(offer.get("seller"), dict) else {}
                quotes.append(PriceQuote(
                    provider="web_offers", title=str(node.get("name") or ""), price=price, currency=currency,
                    seller=seller.get("name") or host, url=offer.get("url") or node.get("url") or page_url,
                    rating=_rating(rating.get("ratingValue")), review_count=_count(rating.get("reviewCount", rating.get("ratingCount"))),
                ))
    if not quotes:
        meta = {k.lower(): v for k, v in _META.findall(html or "")}
        price, currency = _number(meta.get("product:price:amount") or meta.get("og:price:amount")), (meta.get("product:price:currency") or meta.get("og:price:currency") or "").upper()
        if price is not None and len(currency) == 3 and (meta.get("og:title") or meta.get("twitter:title")):
            quotes.append(PriceQuote("web_offers", meta.get("og:title") or meta.get("twitter:title") or "", price, currency, seller=host, url=page_url))
    return quotes


def fetch_html(url: str, fetch=None, kinds=("html",)) -> Optional[str]:
    """The page's text, read the way page_reader.read() reads any page (public
    addresses only, robots.txt, size limit, no logins); None when it cannot be.
    kinds: content-type fragments accepted - HTML by default, ("xml",) for a feed."""
    fetch = fetch or page_reader._default_fetch
    current = url
    try:
        for _ in range(page_reader.MAX_REDIRECTS + 1):
            resolve_public_addresses(current)
            if not page_reader._robots_allows(current, fetch):
                return None
            response = fetch(current)
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                from urllib.parse import urljoin
                current = urljoin(current, response.headers["location"])
                continue
            break
        else:
            return None
    except (UnsafeTargetError, page_reader._TooLarge, httpx.HTTPError):
        return None
    content_type = (response.headers.get("content-type") or "").lower()
    if response.status_code >= 400 or not any(kind in content_type for kind in kinds):
        return None
    return response.text


class WebOffers:
    name = "web_offers"
    MAX_RESULTS = 8
    MAX_PAGES = 5

    def __init__(self, search=web_search.search, fetch_page: Callable[[str], Optional[str]] = fetch_html):
        self._search, self._fetch_page = search, fetch_page

    def available(self) -> bool:
        return web_search.is_configured()

    def search(self, ctx: ProductContext) -> List[PriceQuote]:
        query = f"{ctx.name} price" + (f" {country_name(ctx.country_code)}" if ctx.country_code else "")
        try:
            _provider, results = self._search(query, max_results=self.MAX_RESULTS, country=ctx.country_code)
        except web_search.SearchFailed as exc:
            if str(exc) == "not_configured":
                raise ProviderUnavailable("no web search provider is configured") from exc
            raise ProviderError("web search failed") from exc
        quotes: List[PriceQuote] = []
        seen_hosts = set()
        pages = 0
        for result in results:
            host = urlsplit(result.url).hostname or ""
            if not result.url.startswith(("http://", "https://")) or host in seen_hosts:
                continue
            seen_hosts.add(host)
            if pages >= self.MAX_PAGES:
                break
            pages += 1
            html = self._fetch_page(result.url)
            if html:
                quotes.extend(extract_offers(html, result.url))
        return quotes


# ------------------------------------------------------------------- SerpAPI

SERPAPI_URL = "https://serpapi.com/search.json"


class SerpApiShopping:
    name = "serpapi_shopping"
    MAX_RESULTS = 10

    def __init__(self, get: JsonGet = _json_get):
        self._get = get

    def available(self) -> bool:
        return bool(os.getenv("SERPAPI_API_KEY"))

    def search(self, ctx: ProductContext) -> List[PriceQuote]:
        key = os.getenv("SERPAPI_API_KEY")
        if not key:
            raise ProviderUnavailable("SERPAPI_API_KEY is not set")
        params = {"engine": "google_shopping", "q": ctx.name, "api_key": key}
        if ctx.country_code:
            params["gl"] = ctx.country_code.lower()
        payload = self._get(SERPAPI_URL, params)
        if payload.get("error"):
            raise ProviderError("SerpAPI: " + str(payload["error"])[:120].replace(key, "***"))
        quotes: List[PriceQuote] = []
        for item in (payload.get("shopping_results") or [])[: self.MAX_RESULTS]:
            price = _number(item.get("extracted_price"))
            currency = currency_from_text(item.get("price")) or ctx.currency
            if price is None or not currency or not item.get("title"):
                continue
            quotes.append(PriceQuote(
                provider=self.name, title=item["title"], price=price, currency=currency, seller=item.get("source"),
                url=item.get("product_link") or item.get("link"), rating=_rating(item.get("rating")), review_count=_count(item.get("reviews")),
            ))
        return quotes


PROVIDERS = {cls.name: cls for cls in (OpenPrices, WebOffers, SerpApiShopping)}
DEFAULT_ORDER = "open_prices,web_offers,serpapi_shopping"  # free first, paid last


def configured_order() -> List[str]:
    names = [n.strip() for n in os.getenv("PRICE_LOOKUP_PROVIDERS", DEFAULT_ORDER).split(",") if n.strip()]
    unknown = [n for n in names if n not in PROVIDERS]
    if unknown:
        logger.warning("ignoring unknown PRICE_LOOKUP_PROVIDERS entries %s", unknown)
    return [n for n in names if n in PROVIDERS]
