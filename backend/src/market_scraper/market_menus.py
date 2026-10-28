"""
Menus and prices a competitor publishes OUTSIDE its own website.

The website reader (market_discovery/intel.py) and the social post reader
(social_content.py) only see what the business put on its own site and
profiles. Most restaurants, cafes and shops also publish their full menu -
with every price - on delivery and menu platforms, and photos of the printed
menu end up on Google Maps and across the web. This module reads those:

  delivery     The competitor's listing on delivery / menu platforms
               (Talabat, Careem, HungerStation, Jahez, Keeta, Deliveroo, Uber
               Eats, Zomato, elmenus, Noon, Wolt, Glovo, Restaurant Guru...),
               found through the configured web search and read like any page
               (robots.txt honoured, public addresses only, size capped). The
               platform's own embedded menu data (Next.js / Nuxt state,
               schema.org Menu) gives every item with its price, the price
               before a discount, its section and its options; the page text
               is the fallback, and menu pictures on the listing are OCR'd.
               The listing's fees (delivery fee, minimum order, service fee)
               are kept too, tagged type="fee" so they never match a product.
  maps_photos  Photos on the competitor's own Google Maps listing (Places API
               photos, by its place id): a photo is kept only when OCR / vision
               finds a price list in it. Needs GOOGLE_PLACES_API_KEY and the
               same Places terms approval as reviews
               (PLACES_TERMS_APPROVAL_REFERENCE).
  web_photos   Menu pictures published anywhere on the web (image search:
               Tavily / Brave / SearXNG). A picture is kept only when it names
               the business (its title, its page address or the text read from
               it) AND shows a price list.

Every fact carries channel, platform, the page it came from and when it was
read. A delivery listing whose page names the business (verified) feeds
automatic price matching like the website does - it is the business's own
price list on that platform (offerings.competitor_items); a listing only
partly matching the name, and every photo-derived price, waits for the
owner's confirmation. Delivery prices are often higher than in-store prices,
so every delivery fact says price_context="delivery_app".

Nothing here raises for "nothing found": each source reports a status
(STATUS_*) so the owner sees why it is empty.
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from html import unescape
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlsplit

import httpx

from src.market_scraper import web_search
from src.market_scraper.market_discovery import intel, menu_media
from src.market_scraper.network_security import UnsafeTargetError

logger = logging.getLogger("KEEL_MARKET_MENUS")

CHANNEL_DELIVERY = "delivery"
CHANNEL_MAPS_PHOTOS = "maps_photos"
CHANNEL_WEB_PHOTOS = "web_photos"
CHANNELS = (CHANNEL_DELIVERY, CHANNEL_MAPS_PHOTOS, CHANNEL_WEB_PHOTOS)

STATUS_OK = "ok"
STATUS_NOTHING = "nothing_found"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_APPROVAL_MISSING = "approval_missing"
STATUS_NO_PLACE = "no_place_id"
STATUS_FAILED = "failed"

LISTINGS_STANDARD, LISTINGS_DEEP = int(os.getenv("MARKET_MENUS_LISTINGS", "3")), int(os.getenv("MARKET_MENUS_LISTINGS_DEEP", "8"))
SEARCHES_STANDARD, SEARCHES_DEEP = 2, 4
MAPS_PHOTOS_STANDARD, MAPS_PHOTOS_DEEP = int(os.getenv("MARKET_MENUS_MAPS_PHOTOS", "6")), int(os.getenv("MARKET_MENUS_MAPS_PHOTOS_DEEP", "15"))
WEB_PHOTOS_STANDARD, WEB_PHOTOS_DEEP = int(os.getenv("MARKET_MENUS_WEB_PHOTOS", "6")), int(os.getenv("MARKET_MENUS_WEB_PHOTOS_DEEP", "15"))
MAX_ITEMS = int(os.getenv("MARKET_MENUS_MAX_ITEMS", "400"))
# A photo is a menu only when it carries a price list, not one stray number.
MIN_PRICED_LINES = 3

CONFIDENCE_PLATFORM_DATA = 0.8   # the platform's own menu data for this listing
CONFIDENCE_PLATFORM_TEXT = 0.6   # the listing's page text
CONFIDENCE_UNVERIFIED_PENALTY = 0.15  # the listing only partly names the business
CONFIDENCE_WEB_PHOTO_PENALTY = 0.05   # a picture found by image search, vs one on the business's own listing

# (host pattern, platform name). A host matches when it is the domain or a subdomain of it; a pattern ending in
# "." matches any country domain (deliveroo.ae, deliveroo.co.uk).
PLATFORMS: Tuple[Tuple[str, str], ...] = (
    ("talabat.com", "Talabat"), ("careem.com", "Careem"), ("hungerstation.com", "HungerStation"), ("jahez.net", "Jahez"),
    ("keeta.com", "Keeta"), ("mrsool.co", "Mrsool"), ("thechefz.co", "The Chefz"), ("toyou.io", "ToYou"),
    ("noon.com", "Noon Food"), ("deliveroo.", "Deliveroo"), ("ubereats.com", "Uber Eats"), ("zomato.com", "Zomato"),
    ("elmenus.com", "elmenus"), ("otlob.com", "Otlob"), ("trycarriage.com", "Carriage"), ("wolt.com", "Wolt"),
    ("glovoapp.com", "Glovo"), ("foodpanda.", "foodpanda"), ("doordash.com", "DoorDash"), ("grubhub.com", "Grubhub"),
    ("just-eat.", "Just Eat"), ("lieferando.", "Lieferando"), ("swiggy.com", "Swiggy"), ("instashop.com", "InstaShop"),
    ("restaurantguru.com", "Restaurant Guru"), ("sirved.com", "Sirved"), ("menupages.com", "MenuPages"),
    ("allmenus.com", "Allmenus"), ("menuwithprice.com", "Menu With Price"), ("tripadvisor.", "Tripadvisor"),
)
_SEARCH_PLATFORM_WORDS = "talabat OR careem OR hungerstation OR jahez OR keeta OR deliveroo OR zomato OR elmenus OR \"uber eats\""

# Platform menu data: the keys platforms use for an item's name and price (tried loosely - field names differ per
# platform and change; a missing field yields no item, never an invented one).
_NAME_KEYS = ("name", "title", "itemName", "item_name", "nameEn", "name_en", "displayName", "display_name", "dishName")
_PRICE_KEYS = ("price", "finalPrice", "final_price", "priceAfterDiscount", "discountedPrice", "discounted_price",
               "sellingPrice", "selling_price", "unitPrice", "unit_price", "displayPrice", "priceValue", "price_value")
_OLD_PRICE_KEYS = ("oldPrice", "old_price", "originalPrice", "original_price", "priceBeforeDiscount", "price_before_discount",
                   "strikethroughPrice", "strikethrough_price", "wasPrice", "was_price", "compareAtPrice", "basePrice")
_CURRENCY_KEYS = ("currency", "currencyCode", "currency_code", "currencySymbol")
_OPTION_LISTS = ("options", "choices", "variations", "variants", "sizes", "modifiers", "choiceSections", "toppings")
_FEES = {"deliveryFee": "Delivery fee", "delivery_fee": "Delivery fee", "deliveryCharge": "Delivery fee",
         "delivery_charge": "Delivery fee", "minimumOrder": "Minimum order", "minimum_order": "Minimum order",
         "minOrderAmount": "Minimum order", "min_order_amount": "Minimum order", "minimumOrderAmount": "Minimum order",
         "serviceFee": "Service fee", "service_fee": "Service fee", "smallOrderFee": "Small order fee"}
# Objects that describe a place, not a dish (a restaurant card on the listing).
_NOT_AN_ITEM_KEYS = ("address", "latitude", "lat", "geo", "deliveryTime", "delivery_time", "rating", "reviewsCount", "cuisines")
_STATE_SCRIPTS = (
    re.compile(r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<script[^>]+type=[\"']application/json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"window\.__(?:INITIAL_STATE|PRELOADED_STATE|APOLLO_STATE|NUXT_DATA)__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.IGNORECASE | re.DOTALL),
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def platform_of(url: str) -> Optional[str]:
    """The platform name for a delivery / menu platform address, None for any other site."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for pattern, name in PLATFORMS:
        if pattern.endswith("."):
            if host.startswith(pattern) or f".{pattern}" in f".{host}":
                return name
        elif host == pattern or host.endswith("." + pattern):
            return name
    return None


# --- whose listing is it -------------------------------------------------------

def _distinctive(names: Iterable[str]) -> List[str]:
    from src.market_scraper.market_discovery.offerings import tokens
    from src.market_scraper.market_discovery.relevance import _GENERAL

    words = []
    for name in names:
        for token in tokens(name or ""):
            if len(token) >= 3 and token not in _GENERAL and token not in words:
                words.append(token)
    return words


def names_business(names: List[str], *texts: Optional[str]) -> Optional[bool]:
    """True when every distinctive word of one of the business's names is in the texts (a page title, an address,
    a picture's caption), False when none is, None when only some are (a partial match: kept, but unverified)."""
    from src.market_scraper.market_discovery.offerings import _word_in, normalize, tokens

    joined = " ".join(normalize(unescape(t or "").replace("-", " ").replace("_", " ").replace("/", " ")) for t in texts)
    seen = tokens(joined)
    squashed = joined.replace(" ", "")
    best = False
    for name in names:
        words = _distinctive([name])
        if not words:
            continue
        hits = sum(1 for w in words if _word_in(w, seen) or (w.isascii() and len(w) >= 4 and w in squashed))
        if hits == len(words):
            return True
        if hits:
            best = None
    return best


# --- the platform's menu data ---------------------------------------------------

def _amount(value, currency: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """(price, currency) from a platform's price field: a number, a string ("JOD 3.500", "3,50"), or an object
    ({"amount": .., "currency": ..}, {"fractional": 2500, "code": "AED"}, {"formatted": "AED 25.00"})."""
    if isinstance(value, bool) or value is None:
        return None, currency
    if isinstance(value, (int, float)):
        return (float(value), currency) if 0 < value < 1_000_000 else (None, currency)
    if isinstance(value, dict):
        code = next((value.get(k) for k in ("currency", "code", "currencyCode", "currency_code") if isinstance(value.get(k), str)), None)
        currency = intel._currency(code) or currency  # noqa: SLF001
        if isinstance(value.get("fractional"), (int, float)):
            return _amount(value["fractional"] / 100, currency)
        for key in ("amount", "value", "price", "formatted", "display", "text"):
            if key in value:
                found = _amount(value[key], currency)
                if found[0] is not None:
                    return found
        return None, currency
    if isinstance(value, str):
        text = intel.ascii_digits(value).strip()
        match = intel._PRICE.search(text)  # noqa: SLF001
        if match:
            code = intel._currency(match.group("c1") or match.group("c2")) or currency  # noqa: SLF001
            return intel._number(match.group("a1") or match.group("a2"), code), code  # noqa: SLF001
        if re.fullmatch(r"\d{1,7}(?:[.,]\d{1,3})?", text):
            return intel._number(text, currency), currency  # noqa: SLF001
    return None, currency


def _text(value) -> Optional[str]:
    if isinstance(value, str):
        return intel._clean(value, 120)  # noqa: SLF001
    if isinstance(value, dict):  # {"en": "...", "ar": "..."}
        for key in ("en", "ar", "text", "value", "name"):
            if isinstance(value.get(key), str):
                return intel._clean(value[key], 120)  # noqa: SLF001
    return None


def _first(node: dict, keys) -> Tuple[Optional[str], object]:
    for key in keys:
        if key in node and node[key] not in (None, "", [], {}):
            return key, node[key]
    return None, None


def _state_blobs(html: str) -> List[object]:
    blobs, seen = [], set()
    for pattern in _STATE_SCRIPTS:
        for raw in pattern.findall(html):
            raw = raw.strip()
            if len(raw) < 20 or raw[0] not in "{[" or raw in seen:
                continue
            seen.add(raw)
            try:
                blobs.append(json.loads(raw))
            except ValueError:
                continue
    return blobs


def platform_items(html: str, country: Optional[str] = None, max_items: int = MAX_ITEMS) -> Tuple[List[dict], List[dict]]:
    """(items, fees) from the listing's embedded state. An item is an object with a name and a price that does
    not describe a place; its options ("Large", "Extra cheese") become "Item - Option" entries priced as shown,
    marked price_context="option". Pure function."""
    default_currency = intel._COUNTRY_CURRENCY.get((country or "").upper())  # noqa: SLF001
    items: List[dict] = []
    fees: Dict[str, dict] = {}
    seen = set()

    def page_currency(blob) -> Optional[str]:
        text = json.dumps(blob)[:2_000_000]
        for code in re.findall(r'"(?:currency|currencyCode|currency_code)"\s*:\s*"([A-Za-z]{3})"', text):
            found = intel._currency(code)  # noqa: SLF001
            if found:
                return found
        return None

    def walk(node, currency, section, parent, depth):
        if depth > 40 or len(items) >= max_items:
            return
        if isinstance(node, list):
            for child in node:
                walk(child, currency, section, parent, depth + 1)
            return
        if not isinstance(node, dict):
            return
        _k, code = _first(node, _CURRENCY_KEYS)
        currency = (intel._currency(code, country) if isinstance(code, str) else None) or currency  # noqa: SLF001
        for key, label in _FEES.items():
            if key in node and label not in fees:
                amount, fee_currency = _amount(node[key], currency)
                if amount is not None:
                    fees[label] = {"name": label, "price": amount, "currency": fee_currency, "type": "fee"}
        _nk, raw_name = _first(node, _NAME_KEYS)
        name = _text(raw_name)
        _pk, raw_price = _first(node, _PRICE_KEYS)
        price, item_currency = _amount(raw_price, currency) if raw_price is not None else (None, currency)
        is_item = bool(name and price is not None and not any(k in node for k in _NOT_AN_ITEM_KEYS))
        if is_item:
            full = f"{parent} - {name}" if parent and name.lower() not in parent.lower() else name
            key = (full.lower(), price)
            if key not in seen:
                seen.add(key)
                item = {"name": full[:90], "price": price, "currency": item_currency or default_currency, "type": "product"}
                if not item_currency and default_currency:
                    item["currency_inferred"] = True
                _ok, raw_old = _first(node, _OLD_PRICE_KEYS)
                old, _c = _amount(raw_old, item_currency) if raw_old is not None else (None, None)
                if old and old > price:
                    item["original_price"] = old
                    item["discount_percent"] = round(100 * (old - price) / old, 1)
                description = _text(node.get("description"))
                if description:
                    item["description"] = description[:200]
                if section:
                    item["section"] = section[:60]
                if parent:
                    item["price_context"] = "option"
                if node.get("isAvailable") is False or node.get("available") is False or node.get("soldOut") is True:
                    item["available"] = False
                items.append(item)
        elif name and any(isinstance(node.get(k), list) for k in ("items", "products", "dishes", "menuItems", "menu_items")):
            section = name  # a menu category holding items
        for key, child in node.items():
            if isinstance(child, (dict, list)):
                walk(child, currency, section, name if is_item and key in _OPTION_LISTS else (None if is_item else parent),
                     depth + 1)

    for blob in _state_blobs(html):
        walk(blob, page_currency(blob) or default_currency, None, None, 0)
    return items, list(fees.values())


def listing_title(html: str) -> str:
    """The listing's own heading (h1, else the page title) - normally the restaurant's name on the platform."""
    for pattern in (_H1, _TITLE):
        match = pattern.search(html or "")
        if match:
            text = intel._clean(_TAG.sub(" ", match.group(1)), 200)  # noqa: SLF001
            if text:
                return text
    return ""


def read_listing(html: str, url: str, names: List[str], country: Optional[str] = None,
                 max_items: int = MAX_ITEMS) -> dict:
    """Everything one platform listing says about the business: {"platform", "url", "verified", "facts",
    "media_links"}. verified is True when the listing's heading or address names the business, None when only
    partly; False means it is another business's listing and nothing is kept. Pure function."""
    platform = platform_of(url) or (urlsplit(url).hostname or "")
    title = listing_title(html)
    verified = names_business(names, title, urlsplit(url).path)
    out = {"platform": platform, "url": url, "verified": verified, "title": title, "facts": [], "media_links": []}
    if verified is False:
        return out
    retrieved = _now()
    penalty = 0 if verified else CONFIDENCE_UNVERIFIED_PENALTY
    base = {"channel": CHANNEL_DELIVERY, "platform": platform, "listing_verified": bool(verified),
            "price_context": "delivery_app"}

    def fact(confidence, extracted_by, item):
        context = item.pop("price_context", None)
        return {"kind": "product", "source_url": url, "retrieved_at": retrieved, "confidence": round(confidence - penalty, 3),
                "extracted_by": extracted_by, **base, **({"option": True} if context == "option" else {}),
                **({"price_context": context} if context and context != "option" else {}), **item}

    items, fees = platform_items(html, country, max_items)
    source = "platform_data"
    if len(items) < 3:  # no usable embedded state: schema.org menu data, then the page text
        structured = [i for i in intel.structured_products(html, country) if i.get("price") is not None]
        if len(structured) >= len(items):
            items, source = structured, "structured"
        if len(items) < 3:
            text_items = intel.text_prices(intel.visible_text_lines(html), country, True)
            if len(text_items) > len(items):
                items, source = text_items, "page_text"
    confidence = CONFIDENCE_PLATFORM_TEXT if source == "page_text" else CONFIDENCE_PLATFORM_DATA
    out["facts"] = [fact(confidence, source, dict(item)) for item in items[:max_items]]
    out["facts"] += [fact(confidence, source, {**fee, "name": f"{fee['name']} ({platform})"}) for fee in fees]
    for text in intel.promotions(intel.visible_text_lines(html)):
        out["facts"].append({"kind": "promotion", "source_url": url, "retrieved_at": retrieved,
                             "confidence": round(intel.CONFIDENCE_HEADLINE - penalty, 3), "text": text, **base})
    # Menu pictures the listing shows (named "menu" in the file name or alt text; dish photos are not read).
    out["media_links"] = menu_media.media_links(html, url, False, None, 4)
    return out


# --- fetching ----------------------------------------------------------------

def fetch_page(url: str) -> Optional[str]:
    """A public page, robots.txt honoured, size capped; rendered with a headless browser when it is drawn by
    JavaScript (DISCOVERY_RENDER_JS). None when it can't be read."""
    site = intel._Site(url)  # noqa: SLF001
    try:
        html = site.text(url)
    except (intel.PageUnavailable, httpx.HTTPError, UnsafeTargetError, UnicodeDecodeError, OSError):
        return None
    finally:
        site.close()
    if html and len(intel.visible_text_lines(html)) < 15 and "<script" in html.lower() and not _state_blobs(html):
        return intel._render(url) or html  # noqa: SLF001
    return html


def fetch_media(url: str) -> Optional[Tuple[bytes, str]]:
    """A picture on any public site: robots.txt honoured, size capped."""
    if not url.startswith(("http://", "https://")):
        return None
    site = intel._Site(url)  # noqa: SLF001
    try:
        return site.media(url)
    except (intel.PageUnavailable, httpx.HTTPError, UnsafeTargetError, OSError):
        return None
    finally:
        site.close()


def _photo_facts(data: Tuple[bytes, str], source_url: str, image_url: str, channel: str, country: Optional[str],
                 ocr, vision, ocr_ready: bool, counts: dict, extra: Optional[dict] = None) -> Tuple[List[dict], List[str]]:
    """(facts, lines) for one picture; facts only when the picture holds a price list."""
    lines, method = menu_media.read_media(data[0], data[1], ocr=ocr, ocr_ready=ocr_ready, vision=vision)
    if method == "skipped_no_ocr":
        counts["images_skipped_no_ocr"] += 1
        return [], []
    found = menu_media.media_facts(lines, method, source_url, _now(), country, intel.text_prices) if lines else []
    if len(found) < MIN_PRICED_LINES:
        return [], lines
    counts["images_read"] += 1
    penalty = CONFIDENCE_WEB_PHOTO_PENALTY if channel == CHANNEL_WEB_PHOTOS else 0
    return [{**f, "confidence": round(f["confidence"] - penalty, 3), "channel": channel, "image_url": image_url,
             **(extra or {})} for f in found], lines


# --- the three sources -----------------------------------------------------------

def _queries(competitor: dict, deep: bool) -> List[str]:
    name, city = competitor.get("name") or "", competitor.get("city") or ""
    queries = [f"\"{name}\" {city} {_SEARCH_PLATFORM_WORDS}".strip(), f"\"{name}\" {city} menu prices".strip()]
    if competitor.get("name_ar"):
        queries.append(f"منيو \"{competitor['name_ar']}\" {city}".strip())
    queries.append(f"\"{name}\" {city} منيو اسعار".strip())
    return queries[:SEARCHES_DEEP if deep else SEARCHES_STANDARD]


def delivery_listings(competitor: dict, deep: bool = False, search=None, fetch=fetch_page, media=fetch_media,
                      ocr=None, vision=None, ocr_ready: bool = False, counts: Optional[dict] = None) -> dict:
    """The competitor's listings on delivery / menu platforms. {"status", "facts", "listings"}."""
    counts = counts if counts is not None else {"images_read": 0, "images_skipped_no_ocr": 0, "searches": 0}
    search = search or web_search.search
    names = [n for n in (competitor.get("name"), competitor.get("name_ar")) if n]
    if not names:
        return {"status": STATUS_NOTHING, "facts": [], "listings": []}
    urls: List[str] = []
    try:
        for query in _queries(competitor, deep):
            counts["searches"] += 1
            _provider, results = search(query, max_results=10, country=competitor.get("country"))
            for result in results:
                url = result.url.split("#")[0]
                if platform_of(url) and url not in urls and names_business(names, result.title, url) is not False:
                    urls.append(url)
    except web_search.SearchFailed as exc:
        if not urls:
            return {"status": STATUS_NOT_CONFIGURED if str(exc) == "not_configured" else STATUS_FAILED, "facts": [], "listings": []}
    facts, listings, platforms_seen = [], [], set()
    for url in urls[:LISTINGS_DEEP if deep else LISTINGS_STANDARD]:
        platform = platform_of(url)
        if platform in platforms_seen and not deep:
            continue  # one listing per platform unless "load more"
        html = fetch(url)
        if not html:
            listings.append({"platform": platform, "url": url, "status": "unreadable", "items": 0})
            continue
        listing = read_listing(html, url, names, competitor.get("country"))
        if listing["verified"] is False:
            listings.append({"platform": platform, "url": url, "status": "other_business", "items": 0})
            continue
        platforms_seen.add(platform)
        facts.extend(listing["facts"])
        for image_url in listing["media_links"][:2]:
            data = media(image_url)
            if data:
                found, _lines = _photo_facts(data, url, image_url, CHANNEL_DELIVERY, competitor.get("country"), ocr, vision,
                                             ocr_ready, counts, {"platform": platform, "listing_verified": False,
                                                                 "price_context": "delivery_app"})
                facts.extend(found)
        listings.append({"platform": platform, "url": url, "verified": bool(listing["verified"]), "status": "read",
                         "items": sum(1 for f in listing["facts"] if f["kind"] == "product" and f.get("type") != "fee")})
    status = STATUS_OK if any(f["kind"] == "product" for f in facts) else STATUS_NOTHING
    return {"status": status, "facts": facts, "listings": listings}


PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
PLACES_MEDIA_URL = "https://places.googleapis.com/v1/{photo}/media"


def _places_get(url: str, key: str, params: Optional[dict] = None, field_mask: Optional[str] = None) -> dict:
    from src.market_scraper.provider_billing import metered_request

    headers = {"X-Goog-Api-Key": key, **({"X-Goog-FieldMask": field_mask} if field_mask else {})}

    def send():
        response = httpx.get(url, params=params, headers=headers, timeout=20)  # the key in a header, never the URL
        response.raise_for_status()
        return response.json()
    return metered_request(url, send)


def place_photo_urls(place_id: str, key: str, limit: int, get: Callable = _places_get) -> List[str]:
    """Short-lived addresses of up to `limit` photos on the place's Google Maps listing."""
    details = get(PLACES_DETAILS_URL.format(place_id=quote(place_id, safe="")), key, None, "photos")
    out = []
    for photo in (details.get("photos") or [])[:limit]:
        name = photo.get("name") if isinstance(photo, dict) else None
        if not name or not name.startswith("places/"):
            continue
        media = get(PLACES_MEDIA_URL.format(photo=name), key, {"maxWidthPx": 1600, "skipHttpRedirect": "true"})
        if isinstance(media.get("photoUri"), str) and media["photoUri"].startswith("https://"):
            out.append(media["photoUri"])
    return out


def maps_photos(competitor: dict, deep: bool = False, photo_urls: Callable = place_photo_urls, media=None,
                ocr=None, vision=None, ocr_ready: bool = False, counts: Optional[dict] = None) -> dict:
    """Menu photos on the competitor's own Google Maps listing. {"status", "facts", "photos"}."""
    from src.market_scraper import social_content

    counts = counts if counts is not None else {"images_read": 0, "images_skipped_no_ocr": 0, "searches": 0}
    key = (os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    if not competitor.get("place_id"):
        return {"status": STATUS_NO_PLACE, "facts": [], "photos": 0}
    if not key:
        return {"status": STATUS_NOT_CONFIGURED, "facts": [], "photos": 0}
    if not os.getenv("PLACES_TERMS_APPROVAL_REFERENCE", "").strip():
        return {"status": STATUS_APPROVAL_MISSING, "facts": [], "photos": 0}
    try:
        urls = photo_urls(competitor["place_id"], key, MAPS_PHOTOS_DEEP if deep else MAPS_PHOTOS_STANDARD)
    except Exception as exc:  # noqa: BLE001 - HTTP error, refused budget: reported, never raised
        logger.warning("Google Maps photos failed: %s", type(exc).__name__)
        return {"status": STATUS_FAILED, "facts": [], "photos": 0}
    listing = f"https://www.google.com/maps/place/?q=place_id:{quote(competitor['place_id'], safe='')}"
    facts, started = [], time.monotonic()
    for image_url in urls:
        if time.monotonic() - started > menu_media.TIME_BUDGET_SECONDS:
            break
        data = (media or social_content.fetch_image)(image_url)
        if data:
            # The listing, not the photo address, is the source: photo addresses expire.
            found, _lines = _photo_facts(data, listing, image_url, CHANNEL_MAPS_PHOTOS, competitor.get("country"),
                                         ocr, vision, ocr_ready, counts, {"platform": "Google Maps"})
            facts.extend(found)
    return {"status": STATUS_OK if facts else STATUS_NOTHING, "facts": facts, "photos": len(urls)}


def web_photos(competitor: dict, deep: bool = False, image_search=None, media=fetch_media, ocr=None, vision=None,
               ocr_ready: bool = False, counts: Optional[dict] = None) -> dict:
    """Menu pictures of the competitor published anywhere on the web. {"status", "facts", "pictures"}."""
    counts = counts if counts is not None else {"images_read": 0, "images_skipped_no_ocr": 0, "searches": 0}
    image_search = image_search or web_search.image_search
    names = [n for n in (competitor.get("name"), competitor.get("name_ar")) if n]
    if not names:
        return {"status": STATUS_NOTHING, "facts": [], "pictures": 0}
    city = competitor.get("city") or ""
    queries = [f"\"{names[0]}\" {city} menu".strip(), f"منيو {names[-1]} {city}".strip()]
    found: List[web_search.ImageResult] = []
    try:
        for query in queries[:2 if deep else 1]:
            counts["searches"] += 1
            _provider, results = image_search(query, max_results=15, country=competitor.get("country"))
            known = {f.image_url for f in found}
            found.extend(r for r in results if r.image_url not in known)
    except web_search.SearchFailed as exc:
        if not found:
            return {"status": STATUS_NOT_CONFIGURED if str(exc) == "not_configured" else STATUS_FAILED, "facts": [], "pictures": 0}
    budget = WEB_PHOTOS_DEEP if deep else WEB_PHOTOS_STANDARD
    named = {r.image_url: names_business(names, r.title, r.page_url, r.image_url) for r in found}
    found.sort(key=lambda r: named[r.image_url] is not True)  # pictures whose caption or address names the business first
    facts, read, started = [], 0, time.monotonic()
    for picture in found:
        if read >= budget or time.monotonic() - started > menu_media.TIME_BUDGET_SECONDS:
            break
        if named[picture.image_url] is False and not deep:
            continue  # most likely another business's menu; "load more" also tries these, judged by their own text
        read += 1
        data = media(picture.image_url)
        if not data:
            continue
        source = picture.page_url if (picture.page_url or "").startswith(("http://", "https://")) else picture.image_url
        scratch = {"images_read": 0, "images_skipped_no_ocr": 0}
        candidate, lines = _photo_facts(data, source, picture.image_url, CHANNEL_WEB_PHOTOS, competitor.get("country"),
                                        ocr, vision, ocr_ready, scratch)
        counts["images_skipped_no_ocr"] += scratch["images_skipped_no_ocr"]
        if not candidate or (named[picture.image_url] is not True and names_business(names, " ".join(lines)) is not True):
            continue  # no price list, or the picture never says whose menu it is
        counts["images_read"] += 1
        facts.extend({**f, "platform": platform_of(source) or (urlsplit(source).hostname or "")} for f in candidate)
    return {"status": STATUS_OK if facts else STATUS_NOTHING, "facts": facts, "pictures": read}


def collect(competitor: dict, deep: bool = False, search=None, image_search=None, fetch=fetch_page, media=fetch_media,
            photo_urls: Callable = place_photo_urls, maps_media=None, ocr=None) -> dict:
    """All three sources for one competitor (the dict competitor_enrichment loads: name, city, country, place_id;
    name_ar when known). {"by_channel": {channel: facts}, "sources": {channel: status}, "listings",
    "images_read", "images_skipped_no_ocr", "searches"}."""
    counts = {"images_read": 0, "images_skipped_no_ocr": 0, "searches": 0}
    vision = menu_media.vision_engine()
    ocr_ready = ocr is not None or menu_media.ocr_available()
    common = {"ocr": ocr, "vision": vision, "ocr_ready": ocr_ready, "counts": counts}
    out = {"by_channel": {}, "sources": {}, "listings": []}
    runs = (
        (CHANNEL_DELIVERY, lambda: delivery_listings(competitor, deep, search, fetch, media, **common)),
        (CHANNEL_MAPS_PHOTOS, lambda: maps_photos(competitor, deep, photo_urls, maps_media, **common)),
        (CHANNEL_WEB_PHOTOS, lambda: web_photos(competitor, deep, image_search, media, **common)),
    )
    for channel, run in runs:
        try:
            result = run()
        except Exception:  # noqa: BLE001 - one source failing never stops the others
            logger.exception("reading %s menus failed", channel)
            result = {"status": STATUS_FAILED, "facts": []}
        out["by_channel"][channel] = result["facts"]
        out["sources"][channel] = result["status"]
        out["listings"].extend(result.get("listings") or [])
    out.update(counts)
    return out
