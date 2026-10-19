"""
What a competitor publishes about itself, read from its own website.

For one competitor with a website, KEEL finds the site's own pages most
likely to list products, a menu, services, prices or offers - from the
sitemaps robots.txt announces and from the homepage's links, scored by
words in the address and link text, in Arabic and English - and reads up to
MAX_PAGES of them (same site only, robots.txt honoured for every address,
public addresses only, size and time capped: enrich.py's fetch rules). It
keeps what the pages actually say:

- products and services with the price, currency, unit and any discount the
  site publishes: the store's own catalogue where the shop platform
  publishes one (Shopify /products.json, the WooCommerce Store API: highest
  confidence), schema.org Product / Offer / Menu / MenuItem data (high), or
  a name next to an amount in the page text (medium; Arabic-Indic digits
  and the region's currency signs and words are read),
- offers and promotions (sentences that announce a discount, sale, free
  delivery or similar),
- positioning and messaging (page title, description, main headings),
- social profiles it links to.

Every fact carries the page it came from and when it was read. A site that
yields nothing gets a reason (STATUS_*): unreachable, blocked by robots.txt,
an error page, no products/menu/price page found, prices not published, or
the page needs JavaScript that couldn't be run. Nothing is inferred here -
an amount printed without a currency is kept only on a menu/price page that
lists several, with the currency taken from the site's country and marked
as such.
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from html import unescape
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from src.market_scraper.market_discovery import enrich, menu_media
from src.market_scraper.market_discovery.http import USER_AGENT
from src.market_scraper.network_security import UnsafeTargetError

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
MAX_PAGES = int(os.getenv("DISCOVERY_INTEL_MAX_PAGES", "8"))
MAX_EXTRA_PAGES = MAX_PAGES  # older name
MAX_ITEMS = int(os.getenv("DISCOVERY_INTEL_MAX_ITEMS", "250"))
# "Load more": the owner asked for a deeper read of this one competitor.
DEEP_MAX_PAGES = int(os.getenv("DISCOVERY_INTEL_DEEP_MAX_PAGES", "24"))
DEEP_MAX_ITEMS = int(os.getenv("DISCOVERY_INTEL_DEEP_MAX_ITEMS", "600"))
DEEP_MAX_MEDIA = int(os.getenv("DISCOVERY_INTEL_DEEP_MAX_MEDIA", "15"))
MAX_SITEMAP_URLS = 600
PAGE_DELAY_SECONDS = float(os.getenv("DISCOVERY_INTEL_PAGE_DELAY_SECONDS", "0.4"))
RENDER_JS = os.getenv("DISCOVERY_RENDER_JS", "auto").lower()  # auto | false
CONFIDENCE_CATALOG = 0.95     # the shop platform's own product feed
CONFIDENCE_STRUCTURED = 0.9   # the site's own machine-readable data
CONFIDENCE_TEXT = 0.6         # read from the page text
CONFIDENCE_TEXT_NO_CURRENCY = 0.45
CONFIDENCE_HEADLINE = 0.8     # the site's own words, quoted

STATUS_PRICES = "prices_found"
STATUS_NO_PRICES = "no_price_published"
STATUS_NO_PAGE = "no_relevant_page"
STATUS_UNREACHABLE = "unreachable"
STATUS_ROBOTS = "blocked_by_robots"
STATUS_HTTP = "http_error"
STATUS_JS = "needs_javascript"
STATUS_FAILED = "extraction_failed"
STATUS_NOT_PUBLIC = "not_public"
STATUS_NO_WEBSITE = "no_website"
STATUS_NOT_OWN_SITE = "not_own_site"
STATUS_OTHER_BUSINESS = "other_business_site"


def own_site(url: str) -> bool:
    """A business's own website - not a social profile, a link shortener, a
    directory or a delivery/listing platform that lists many businesses."""
    from src.market_scraper.market_discovery.providers.web_search import NOT_A_BUSINESS

    lowered = (url or "").lower()
    host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
    return bool(host) and not enrich.on_host(lowered, enrich.NOT_OWN_SITE) and not enrich.on_host(
        lowered, NOT_A_BUSINESS + ("g.co", "g.page", "jeeran.com", "tiktok.com", "snapchat.com", "t.me", "carriage.", "deliveroo",
                                             "menu.app", "zomato", "elmenus.com", "hungerstation", "careem", "keeta",
                                             # table booking platforms: their pages list many businesses
                                             "sevenrooms.com", "opentable.", "eatapp.co", "quandoo.", "tablecheck.",
                                             "resy.com", "chope.co", "calendly.com")) and host.removeprefix("www.") not in _MAIL_HOSTS


# An email provider given as a website ("hotmail.com" from an address).
_MAIL_HOSTS = {"hotmail.com", "gmail.com", "yahoo.com", "outlook.com", "live.com", "msn.com", "icloud.com", "aol.com",
               "mail.com", "yandex.com", "proton.me", "protonmail.com", "gmx.com", "zoho.com"}

_PAGE_WORDS = re.compile(
    r"menu|food|dish|products?|shop|store|catalog(?:ue)?|collections?|prices?|pricing|plans?|packages?|services?|"
    r"offers?|deals?|promotions?|specials?|rates?|rooms?|tariffs?|order|delivery|category|categories|"
    r"منيو|المنيو|قائمة|الطعام|الأطباق|اطباق|منتجات|المنتجات|متجر|المتجر|الأسعار|أسعار|اسعار|خدمات|الخدمات|"
    r"عروض|العروض|تخفيضات|باقات|الباقات|الغرف|اطلب|تسوق|أصناف|الأصناف|الوجبات|وجبات", re.IGNORECASE)
_MENU_PAGE = re.compile(r"menu|price|pricing|rates|tariff|منيو|المنيو|قائمة|الأسعار|أسعار|اسعار|الوجبات", re.IGNORECASE)
_SKIP_PATHS = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|css|js|xml|json)$|/(cart|checkout|account|login|signin|"
                         r"register|wp-admin|my-account|wishlist|compare|feed|tag|author|blog|news)\b", re.IGNORECASE)
_ANCHOR = re.compile(r"<a\s[^>]*href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_HEADING = re.compile(r"<h([12])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK = re.compile(r"</?(p|div|li|tr|td|th|h[1-6]|br|section|article|span|a|button|dt|dd|label)[^>]*>", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)

# Arabic-Indic and Eastern Arabic-Indic digits, and the Arabic decimal and
# thousands separators, as plain ASCII.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")

def _abbr(first: str, second: str) -> str:
    """An Arabic two-letter currency abbreviation, written with a dot or a
    space between the letters ("د.أ", "ر س"): run together ("جم", "كجم")
    the same letters are a unit - grams, kilograms - not a currency."""
    return rf"{first}(?:\.\s?|\s){second}\.?"


# Currency signs and words as written on MENA sites -> ISO code, or a list
# of codes resolved by the site's country.
_CURRENCY_FORMS: List[Tuple[str, object]] = [
    (rf"{_abbr('د', 'أ')}|{_abbr('د', 'ا')}|JOD|JDs?\b", "JOD"),
    (rf"{_abbr('ر', 'س')}|SAR|SR\b|\u20c1", "SAR"),
    (rf"{_abbr('د', 'إ')}|AED|Dhs?\b|DHS\b", ["AED", "MAD"]),
    (rf"{_abbr('د', 'ك')}|KWD|KD\b", "KWD"),
    (rf"{_abbr('ر', 'ق')}|QAR|QR\b", "QAR"),
    (rf"{_abbr('د', 'ب')}|BHD|BD\b", "BHD"),
    (rf"{_abbr('ر', 'ع')}|OMR|RO\b", "OMR"),
    (rf"{_abbr('ج', 'م')}|EGP|L\.?E\b", "EGP"),
    (rf"{_abbr('د', 'م')}|MAD|DH\b", ["MAD", "AED"]),
    (rf"{_abbr('ل', 'ل')}|LBP", "LBP"),
    (rf"{_abbr('د', 'ع')}|IQD", "IQD"),
    (rf"{_abbr('د', 'ت')}|TND", "TND"),
    (rf"DZD|{_abbr('د', 'ج')}", "DZD"),
    (r"TRY|TL\b|₺", "TRY"),
    (r"USD|US\$|\$", "USD"),
    (r"EUR|€", "EUR"),
    (r"GBP|£", "GBP"),
    (r"دينار|دنانير", ["JOD", "KWD", "BHD", "IQD", "TND", "DZD", "LYD"]),
    (r"ريال|﷼", ["SAR", "QAR", "OMR", "YER"]),
    (r"درهم|دراهم", ["AED", "MAD"]),
    (r"جنيه|جنيهات", ["EGP", "SDG"]),
    (r"ليرة", ["LBP", "SYP", "TRY"]),
]
_CURRENCY = "|".join(f"(?:{form})" for form, _code in _CURRENCY_FORMS)
_COUNTRY_CURRENCY = {"JO": "JOD", "SA": "SAR", "AE": "AED", "KW": "KWD", "QA": "QAR", "BH": "BHD", "OM": "OMR",
                     "EG": "EGP", "MA": "MAD", "LB": "LBP", "IQ": "IQD", "TN": "TND", "DZ": "DZD", "LY": "LYD",
                     "SY": "SYP", "YE": "YER", "SD": "SDG", "PS": "ILS", "TR": "TRY", "US": "USD", "GB": "GBP"}
_TLD_COUNTRY = {"jo": "JO", "sa": "SA", "ae": "AE", "kw": "KW", "qa": "QA", "bh": "BH", "om": "OM", "eg": "EG",
                "ma": "MA", "lb": "LB", "iq": "IQ", "tn": "TN", "dz": "DZ", "ly": "LY", "sy": "SY", "ps": "PS", "tr": "TR"}
_THREE_DECIMALS = {"JOD", "KWD", "BHD", "OMR", "TND", "IQD", "LYD"}
_AMOUNT = r"\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,3})?|\d{1,7}(?:[.,]\d{1,3})?"
# A currency sign directly before or after an amount, not inside a word
# ("Pro 5" is not 5 Omani rials).
_PRICE = re.compile(rf"(?:(?<![A-Za-z؀-ۿ])(?P<c1>{_CURRENCY})\s?(?P<a1>{_AMOUNT})"
                    rf"|(?<![\d.,])(?P<a2>{_AMOUNT})\s?(?P<c2>{_CURRENCY}))(?![A-Za-z؀-ۿ])", re.IGNORECASE)
_RANGE = re.compile(rf"(?<![\d.,])(?P<low>{_AMOUNT})\s?(?:-|–|—|to|إلى|الى)\s?(?P<high>{_AMOUNT})\s?(?P<cur>{_CURRENCY})"
                    r"(?![A-Za-z\u0600-\u06ff])", re.IGNORECASE)
_BARE = re.compile(r"(?:^|\s)(?P<a>\d{1,4}(?:[.,]\d{1,3})?)\s*$")
_UNIT = re.compile(r"^\s*(?:/|per\s|لكل\s|لل|ل)?\s*(kg|كيلو|كغ|كجم|g|gm|غرام|جرام|piece|pc|pcs|قطعة|person|شخص|night|ليلة|"
                   r"month|شهر|year|سنة|hour|ساعة|session|جلسة|l|liter|لتر|ml)\b", re.IGNORECASE)
_PROMO = re.compile(
    r"\b(\d{1,2}\s?%\s?off|sale|discount|offer|deal|promo(?:tion)?|free (?:delivery|shipping)|buy \d+ get \d+|limited time|"
    r"special price|save \d+)\b|خصم|تخفيض|عرض|عروض|مجان[اًي]|توصيل مجاني|لفترة محدودة|اشتر[ِ]?\s?\d",
    re.IGNORECASE)
_NOT_A_PRODUCT = re.compile(
    r"^(sub\s?total|total|delivery|shipping|tax|vat|fee|min(imum)?|orders? (over|above|under|below)|cart|basket|"
    r"(regular|sale|unit|old|new|original|current|your|our) price|price|add to (cart|bag|basket)|buy now|order now|"
    r"per|approx(imately)?|around|about|up to|over|under|less than|more than|above|below|only|and|or|with|for|"
    r"الإجمالي|المجموع|التوصيل|الشحن|الضريبة|رسوم|الحد الأدنى|السلة|السعر|سعر|أضف|اضف|اطلب الآن|"
    r"أقل من|اقل من|أكثر من|اكثر من|حتى|فقط|حوالي|تقريبا)(?![A-Za-z\u0600-\u06ff])", re.IGNORECASE)
# Conditions, not things for sale: "orders over 100 SAR", "4 SAR for orders under 50".
_THRESHOLD = re.compile(r"\b(orders?|purchases?|spend|minimum)\b.*\b(over|above|under|below|more|less)\b|"
                        r"للطلبات|الطلبات|للطلب|لطلبات|الحد الأدنى|عند الشراء|للمشتريات", re.IGNORECASE)
# Fees, captions and buttons wherever they sit in the label.
_NOT_AN_ITEM_ANYWHERE = re.compile(
    r"\b(shipping|delivery (charge|fee|cost)s?|wish ?list|add to|highest price|lowest price|price is|deadline|"
    r"in stock|out of stock|per page|fees?|up to|special rate|starts? (from|at))\b|رسوم التوصيل|قيمة الطلب|سعر التوصيل|الشحن|قائمة الأمنيات|أضف إلى|اضف الى|"
    r"\"\w+\"\s*:|[{}\[\]<>=]|\b\d{1,2}:\d{2}\b", re.IGNORECASE)
# A label that is only a caption, a size, a period or an option group: the
# price belongs to the line above ("Margherita" / "Large 6 JD").
_CAPTION = re.compile(
    r"^(from|starting( at| from)?|price|prices|only|now|was|new|sale|add-?ons?|extras?|options?|spicy|"
    r"monthly|yearly|annually|weekly|daily|per (month|year|night|person)|month|year|"
    r"small|medium|large|regular|xl|xxl|single|double|family|half|full|"
    r"صغير|وسط|متوسط|كبير|عائلي|نص|نصف|كامل|سنجل|دبل|اضافات|إضافات|شهري|سنوي|يبدأ من|ابتداء من)$", re.IGNORECASE)
# A sentence whose amount was cut out of its end: "rooms start from .",
# "a special rate of" - a caption, not an item.
_DANGLING = re.compile(r"\b(from|of|at|for|is|are|to|by|only|من|بـ|ب|على|فقط)\s*[.:]?$", re.IGNORECASE)
_SIZE = re.compile(r"^(small|medium|large|regular|xl|xxl|single|double|family|half|full|"
                   r"صغير|وسط|متوسط|كبير|عائلي|نص|نصف|كامل|سنجل|دبل)$", re.IGNORECASE)
# Template placeholder text - a theme demo, not the business's prices.
_PLACEHOLDER = re.compile(r"\b(lorem|ipsum|dolor sit|consectetur|adipiscing|molestie|fringilla|vestibulum|"
                          r"product (name|title)|item name|sample product|demo product)\b", re.IGNORECASE)
_FROM = re.compile(r"^(from|starting( at| from)?|يبدأ من|ابتداء[ًا]? من|من)\s", re.IGNORECASE)
_PHONE_LIKE = re.compile(r"(?:\+|00)\d{6,}|\d{3}[\s-]\d{3}[\s-]\d{3,4}")
_DATE_LIKE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b(19|20)\d{2}\b")


class PageUnavailable(Exception):
    """A page that answered with no usable HTML: reason is STATUS_*."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: Optional[str], limit: int = 200) -> Optional[str]:
    if not text:
        return None
    text = _SPACE.sub(" ", unescape(_TAG.sub(" ", str(text)))).strip()
    return text[:limit] or None


def ascii_digits(text: str) -> str:
    return (text or "").translate(_DIGITS)


def site_country(url: str, fallback: Optional[str] = None) -> Optional[str]:
    tld = (urlsplit(url).hostname or "").rsplit(".", 1)[-1].lower()
    return _TLD_COUNTRY.get(tld) or (fallback or None)


def _currency(raw: Optional[str], country: Optional[str] = None) -> Optional[str]:
    """A currency sign, code or word as an ISO code. Signs shared by several
    currencies (ريال, دينار, درهم) are resolved by the site's country."""
    text = (raw or "").strip()
    if not text:
        return None
    if re.fullmatch(r"[A-Za-z]{3}", text) and text.upper() in set(_COUNTRY_CURRENCY.values()) | {"EUR", "USD", "GBP"}:
        return text.upper()
    local = _COUNTRY_CURRENCY.get((country or "").upper())
    for form, code in _CURRENCY_FORMS:
        if re.fullmatch(form, text, re.IGNORECASE):
            if isinstance(code, list):
                return local if local in code else code[0]
            return code
    return None


def _number(value, currency: Optional[str] = None) -> Optional[float]:
    """"3.500", "3,50", "1,250", "1 250.75", "٣٫٥" -> a number. A comma before
    exactly three digits is a thousands separator, except in currencies
    written with three decimals (3,500 JD is three and a half dinars)."""
    text = ascii_digits(str(value if value is not None else "")).strip().replace(" ", " ")
    if not text:
        return None
    if re.fullmatch(r"\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?", text) and not (currency in _THREE_DECIMALS and re.fullmatch(r"\d{1,3},\d{3}", text)):
        text = re.sub(r"[,\s]", "", text)
    else:
        text = text.replace(" ", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if 0 < number < 10_000_000 else None


def _offers(node: dict, country: Optional[str] = None) -> List[dict]:
    offers = node.get("offers") or []
    offers = [offers] if isinstance(offers, dict) else offers
    out = []
    for offer in offers if isinstance(offers, list) else []:
        if not isinstance(offer, dict):
            continue
        currency = _currency(offer.get("priceCurrency"), country)
        low = _number(offer.get("price") if offer.get("price") is not None else offer.get("lowPrice"), currency)
        if low is None:
            spec = offer.get("priceSpecification")
            spec = spec[0] if isinstance(spec, list) and spec else spec
            if isinstance(spec, dict):
                currency = currency or _currency(spec.get("priceCurrency"), country)
                low = _number(spec.get("price"), currency)
        if low is not None:
            high = _number(offer.get("highPrice"), currency)
            out.append({"price": low, "currency": currency, **({"price_max": high} if high and high > low else {})})
    return out


def structured_products(html: str, country: Optional[str] = None) -> List[dict]:
    """schema.org Product / Offer / Menu / MenuItem / Service entries on a page."""
    out = []
    for block in enrich._JSON_LD.findall(html):  # noqa: SLF001 - same JSON-LD pattern
        try:
            data = json.loads(unescape(block.strip()))
        except ValueError:
            continue
        stack = enrich._schema_nodes(data)  # noqa: SLF001
        section = None
        while stack:
            node = stack.pop(0)
            if not isinstance(node, dict):
                continue
            types = set(enrich._types(node))  # noqa: SLF001
            if "MenuSection" in types:
                section = _clean(node.get("name"), 80)
            for key in ("hasMenu", "hasMenuSection", "hasMenuItem", "itemListElement", "hasOfferCatalog", "item",
                        "makesOffer", "offers" if "Menu" in types else "_"):
                nested = node.get(key)
                for child in nested if isinstance(nested, list) else [nested] if isinstance(nested, dict) else []:
                    if isinstance(child, dict):
                        stack.append(child)
            if not types & {"Product", "MenuItem", "Service", "Offer", "IndividualProduct", "ProductModel", "Room", "HotelRoom"}:
                continue
            raw_name = node.get("name") if isinstance(node.get("name"), str) else (
                (node.get("itemOffered") or {}).get("name") if isinstance(node.get("itemOffered"), dict) else None)
            name = _clean(raw_name, 120)
            if not name:
                continue
            offers = _offers(node, country)
            if not offers and _number(node.get("price")):
                offers = [{"price": _number(node.get("price")), "currency": _currency(node.get("priceCurrency"), country)}]
            item = {"name": name, "type": "service" if types & {"Service", "Room", "HotelRoom"} else "product",
                    "price": offers[0]["price"] if offers else None, "currency": offers[0]["currency"] if offers else None,
                    "description": _clean(node.get("description") if isinstance(node.get("description"), str) else None, 200)}
            if offers and offers[0].get("price_max"):
                item["price_max"] = offers[0]["price_max"]
            if section:
                item["section"] = section
            out.append(item)
    return out


def visible_text_lines(html: str) -> List[str]:
    text = _BLOCK.sub("\n", _SCRIPT.sub(" ", html))
    lines = []
    for line in unescape(_TAG.sub(" ", text)).split("\n"):
        line = _SPACE.sub(" ", line).strip()
        if 1 <= len(line) <= 220:
            lines.append(line)
    return lines


def _label(label: Optional[str]) -> Optional[str]:
    return label.strip(" -–—:|•·/*") if label else label


def _label_ok(label: Optional[str]) -> bool:
    return bool(label and 2 <= len(label) <= 90 and re.search(r"[A-Za-z؀-ۿ]{2}", label)
                and not _NOT_A_PRODUCT.search(label) and not _PROMO.search(label) and not _PHONE_LIKE.search(label)
                and not _THRESHOLD.search(label) and not _PLACEHOLDER.search(label)
                and not _NOT_AN_ITEM_ANYWHERE.search(label) and not _CAPTION.match(label) and not _DANGLING.search(label)
                and not re.fullmatch(_CURRENCY, label.strip(), re.IGNORECASE))


def _with_item_above(label: Optional[str], lines: List[str], index: int) -> Optional[str]:
    """A size ("Large", "كبير") names a variant of the item on the line above."""
    if label and _SIZE.match(label) and index > 0:
        above = _label(lines[index - 1])
        if above and not _PRICE.search(above) and not _BARE.search(above) and _label_ok(above):
            return f"{above} - {label}"
    return label


def text_prices(lines: List[str], country: Optional[str] = None, menu_page: bool = False) -> List[dict]:
    """A name followed by an amount on the same line, or on the next line
    when the amount stands alone ("Kunafa" / "3.50 JD"). With menu_page, an
    amount printed without a currency counts when the page lists several,
    in the site country's currency, marked currency_inferred."""
    lines = [ascii_digits(line) for line in lines]
    out, bare = [], []
    for index, line in enumerate(lines):
        matches = list(_PRICE.finditer(line))
        if not matches:
            if menu_page:
                bare_match = _BARE.search(line)
                label = _label(line[:bare_match.start()].strip(" -:|•·.")) if bare_match else None
                if bare_match and not label and index > 0 and not _BARE.search(lines[index - 1]) and not _PRICE.search(lines[index - 1]):
                    label = _label(lines[index - 1])
                label = _with_item_above(label, lines, index)
                if bare_match and _label_ok(label) and not _DATE_LIKE.search(line):
                    amount = _number(bare_match.group("a"))
                    if amount is not None:
                        bare.append({"name": label[:90], "price": amount})
            continue
        first = matches[0]
        currency = _currency(first.group("c1") or first.group("c2"), country)
        amounts = [_number(m.group("a1") or m.group("a2"), currency) for m in matches]
        stripped = _PRICE.sub(" ", line)
        span = _RANGE.search(line)
        if span:  # "45 - 60 JD": one price range, not a product called "Room 45"
            currency = _currency(span.group("cur"), country)
            amounts = [_number(span.group("low"), currency), _number(span.group("high"), currency)]
            stripped = line[:span.start()] + " " + line[span.end():]
        amounts = [a for a in amounts if a is not None]
        if not amounts:
            continue
        unit = _UNIT.match(line[(span or first).end():])
        if unit:
            stripped = stripped.replace(unit.group(0).strip(), " ")
        label = _label(_SPACE.sub(" ", stripped)) if len(line) > len((span or first).group(0)) + 2 else None
        if not label and index > 0 and not _PRICE.search(lines[index - 1]):
            label = _label(lines[index - 1])
        label = _with_item_above(label, lines, index)
        if not _label_ok(label):
            continue
        item = {"name": label[:90], "price": min(amounts), "currency": currency}
        if len(amounts) > 1 and max(amounts) != min(amounts):
            if _PROMO.search(line) or re.search(r"was|before|instead|بدلا|كان", line, re.IGNORECASE):
                item["original_price"] = max(amounts)
            else:
                item["price_max"] = max(amounts)
        if unit:
            item["unit"] = unit.group(1).lower()
        if _FROM.search(label):
            item["price_context"] = "from"
        out.append(item)
    # Bare amounts only count as a price list, not as a stray number.
    local = _COUNTRY_CURRENCY.get((country or "").upper())
    # One amount repeated for every line is a placeholder or an add-on
    # price, not a price list.
    values = [item["price"] for item in bare]
    if menu_page and local and len(bare) >= 3 and max(values.count(v) for v in values) * 2 <= len(values):
        for item in bare:
            out.append({**item, "currency": local, "currency_inferred": True})
    return out


def promotions(lines: List[str]) -> List[str]:
    seen, out = set(), []
    for line in lines:
        if _PROMO.search(line) and 8 <= len(line) <= 200 and line.lower() not in seen:
            seen.add(line.lower())
            out.append(line)
    return out[:10]


def headlines(html: str) -> List[str]:
    out = []
    for _level, inner in _HEADING.findall(_SCRIPT.sub(" ", html)):
        text = _clean(inner, 160)
        if text and text not in out:
            out.append(text)
    return out[:6]


def _same_site(url: str, base_url: str) -> bool:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    return bool(host) and host == (urlsplit(base_url).hostname or "").removeprefix("www.")


def _score(url: str, label: str = "") -> int:
    return len(_PAGE_WORDS.findall(f"{urlsplit(url).path} {label}"))


_GENERIC_SEGMENT = re.compile(r"^(home|index|main|default|welcome|start|site|web|[a-z]{2}(?:[-_][a-z]{2})?)$", re.IGNORECASE)


def path_scope(url: str) -> str:
    """The part of a host that belongs to this business. A website given as
    host/<name> (a store on a shared platform: take.app/onepieceburger) owns
    only the pages under /<name>, not the platform's other stores."""
    segment = urlsplit(url).path.strip("/").split("/", 1)[0]
    if not segment or "." in segment or _GENERIC_SEGMENT.match(segment):
        return "/"
    return f"/{segment}/"


def candidate_pages(html: str, base_url: str, extra: Optional[List[str]] = None, limit: Optional[int] = None) -> List[str]:
    """The site's own pages most likely to list products, a menu, prices or
    offers: homepage links (address + link text) and sitemap addresses."""
    home = urlsplit(base_url)
    scope = path_scope(base_url)
    scored: Dict[str, int] = {}
    links = [(urljoin(base_url, href.strip()), _clean(label, 80) or "") for href, label in _ANCHOR.findall(html)]
    links += [(url, "") for url in extra or []]
    for link, label in links:
        parts = urlsplit(link)
        if parts.scheme not in ("http", "https") or not _same_site(link, base_url):
            continue
        if not f"{parts.path.rstrip('/')}/".startswith(scope):
            continue
        if _SKIP_PATHS.search(parts.path) or parts.path.rstrip("/") in ("", home.path.rstrip("/")):
            continue
        score = _score(link, label)
        if score:
            clean = parts._replace(fragment="", query="").geturl()
            # Shallow pages first: /menu before /menu/item-123.
            depth = clean.rstrip("/").count("/") - 2
            scored[clean] = max(scored.get(clean, 0), score * 10 - depth)
    ranked = sorted(scored, key=lambda url: -scored[url])
    return ranked[:limit or MAX_PAGES]


def sitemap_urls(robots_text: Optional[str], base_url: str, fetch_text: Callable[[str], Optional[str]]) -> List[str]:
    """Page addresses from the sitemaps robots.txt names (or /sitemap.xml),
    following a sitemap index one level, product/menu/page sitemaps first."""
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_text or "") or [urljoin(base_url, "/sitemap.xml")]
    urls: List[str] = []
    for sitemap in maps[:3]:
        if not _same_site(sitemap, base_url):
            continue
        body = fetch_text(sitemap)
        if not body:
            continue
        locs = _LOC.findall(body)
        if "<sitemapindex" in body.lower():
            children = sorted(locs, key=lambda u: -len(re.findall(r"product|menu|page|service|shop|categor", u, re.I)))[:3]
            for child in children:
                child_body = fetch_text(child) if _same_site(child, base_url) else None
                urls.extend(_LOC.findall(child_body or ""))
        else:
            urls.extend(locs)
        if len(urls) >= MAX_SITEMAP_URLS:
            break
    return [unescape(u) for u in urls[:MAX_SITEMAP_URLS]]


def shopify_products(payload: dict, page_url: str, currency: Optional[str]) -> List[dict]:
    """A Shopify store's own /products.json: every product, its variants'
    prices and compare-at (before discount) prices."""
    out = []
    base = f"{urlsplit(page_url).scheme}://{urlsplit(page_url).netloc}"
    for product in (payload or {}).get("products") or []:
        variants = [v for v in product.get("variants") or [] if isinstance(v, dict)]
        prices = [p for p in (_number(v.get("price")) for v in variants) if p is not None]
        if not product.get("title") or not prices:
            continue
        item = {"name": _clean(product["title"], 120), "type": "product", "price": min(prices), "currency": currency,
                "source_url": f"{base}/products/{product.get('handle')}" if product.get("handle") else page_url}
        if max(prices) > min(prices):
            item["price_max"] = max(prices)
        compare = [c for c in (_number(v.get("compare_at_price")) for v in variants) if c is not None]
        if compare and max(compare) > min(prices):
            item["original_price"] = max(compare)
        if product.get("product_type"):
            item["section"] = _clean(product["product_type"], 60)
        if not currency:
            item["currency_inferred"] = True
        out.append(item)
    return out


def woocommerce_products(payload, page_url: str) -> List[dict]:
    """The WooCommerce Store API's public product list (prices in minor units)."""
    out = []
    for product in payload if isinstance(payload, list) else []:
        prices = product.get("prices") or {}
        minor = int(prices.get("currency_minor_unit") or 0)
        price = _number(prices.get("price"))
        if not product.get("name") or price is None:
            continue
        price /= 10 ** minor
        item = {"name": _clean(product["name"], 120), "type": "product", "price": round(price, 3),
                "currency": _currency(prices.get("currency_code")), "source_url": product.get("permalink") or page_url}
        regular = _number(prices.get("regular_price"))
        if regular and regular / 10 ** minor > price:
            item["original_price"] = round(regular / 10 ** minor, 3)
        categories = product.get("categories") or []
        if categories and isinstance(categories[0], dict) and categories[0].get("name"):
            item["section"] = _clean(categories[0]["name"], 60)
        out.append(item)
    return out


def read_page(html: str, url: str, country: Optional[str] = None, max_items: int = MAX_ITEMS) -> dict:
    """Every fact on one page, each tagged with the page. Pure function."""
    retrieved = _now()
    lines = visible_text_lines(html)
    home = enrich.parse_homepage(html, url)
    title = home.get("title") or ""
    menu_page = bool(_MENU_PAGE.search(f"{urlsplit(url).path} {title}"))
    fact = lambda kind, confidence, **value: {"kind": kind, "source_url": value.pop("source_url", None) or url,  # noqa: E731
                                              "retrieved_at": retrieved, "confidence": confidence, **value}
    facts = []
    # A page still showing its theme's placeholder text is a demo: its
    # prices are the template's, not the business's.
    placeholder = sum(1 for line in lines if _PLACEHOLDER.search(line)) >= 2 or any("lorem ipsum" in line.lower() for line in lines)
    structured = [] if placeholder else structured_products(html, country)
    for item in structured[:max_items]:
        facts.append(fact("product", CONFIDENCE_STRUCTURED, **item))
    known = {p["name"].lower() for p in structured}
    for item in ([] if placeholder else text_prices(lines, country, menu_page))[:max_items]:
        if item["name"].lower() not in known:
            known.add(item["name"].lower())
            confidence = CONFIDENCE_TEXT_NO_CURRENCY if item.get("currency_inferred") else CONFIDENCE_TEXT
            facts.append(fact("product", confidence, type="product", **item))
    for text in promotions(lines):
        facts.append(fact("promotion", CONFIDENCE_HEADLINE, text=text))
    messages = [m for m in [home.get("title"), home.get("description"), *headlines(html)] if m]
    for text in dict.fromkeys(messages):
        facts.append(fact("message", CONFIDENCE_HEADLINE, text=text))
    for link in home.get("social") or []:
        facts.append(fact("social", CONFIDENCE_STRUCTURED, url=link))
    return {"facts": facts, "pages": candidate_pages(html, url), "text_chars": sum(len(line) for line in lines),
            "relevant": menu_page or _score(url, title) > 0}


# --- fetching ----------------------------------------------------------------

class _Site:
    """One site's fetches: robots.txt read once, polite spacing, the same
    public-address and size rules as enrich.py."""

    def __init__(self, homepage: str):
        self.homepage = homepage
        self.client = httpx.Client(timeout=enrich.TIMEOUT, follow_redirects=False)
        self.robots: Optional[RobotFileParser] = None
        self.robots_text: Optional[str] = None
        self._last = 0.0

    def _get(self, url: str, accept: str) -> httpx.Response:
        wait = PAGE_DELAY_SECONDS - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        response = enrich._safe_get(self.client, url)  # noqa: SLF001
        if response is None:
            raise PageUnavailable(STATUS_HTTP)
        return response

    def load_robots(self) -> None:
        response = self._get(urljoin(self.homepage, "/robots.txt"), "text/plain")
        parser = RobotFileParser()
        if response.status_code >= 500:
            parser.disallow_all = True
        elif response.status_code < 400:
            self.robots_text = response.text
            parser.parse(response.text.splitlines())
        else:
            parser.parse([])
        self.robots = parser

    def allowed(self, url: str) -> bool:
        if self.robots is None:
            self.load_robots()
        return self.robots.can_fetch(USER_AGENT, url)

    def text(self, url: str, kinds=("html",)) -> str:
        if not self.allowed(url):
            raise PageUnavailable(STATUS_ROBOTS)
        response = self._get(url, "*/*")
        if response.status_code >= 400:
            raise PageUnavailable(STATUS_HTTP)
        content_type = response.headers.get("content-type", "")
        if content_type and not any(kind in content_type for kind in kinds):
            raise PageUnavailable(STATUS_HTTP)
        return response.text

    def media(self, url: str) -> Optional[Tuple[bytes, str]]:
        """A menu PDF / picture: (bytes, content type), or None when robots.txt
        disallows it, it can't be fetched, or it is larger than the cap (a
        cut-off file would only be misread)."""
        if not self.allowed(url):
            return None
        wait = PAGE_DELAY_SECONDS - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        response = enrich._safe_get(self.client, url, max_bytes=menu_media.MEDIA_MAX_BYTES,  # noqa: SLF001
                                    accept="application/pdf,image/*")
        if response is None or response.status_code >= 400 or len(response.content) >= menu_media.MEDIA_MAX_BYTES:
            return None
        return response.content, response.headers.get("content-type", "")

    def close(self) -> None:
        self.client.close()


def _render(url: str) -> Optional[str]:
    """The page after its JavaScript ran (a headless browser), when one is
    installed and DISCOVERY_RENDER_JS isn't false. None otherwise."""
    if RENDER_JS == "false":
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    executable = next((p for p in (os.getenv("KEEL_CHROMIUM_PATH"), "/opt/pw-browsers/chromium", "/usr/bin/google-chrome",
                                   "/usr/bin/chromium") if p and os.path.exists(p)), None)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**({"executable_path": executable} if executable else {}))
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="networkidle", timeout=20000)
                return page.content()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - rendering is a best effort
        logger.info("rendering %s failed: %s", urlsplit(url).hostname, type(exc).__name__)
        return None


def names_the_business(names: List[str], url: str, html: str) -> Optional[bool]:
    """Whether a website is the named business's: one of the distinctive
    words of its name (English or Arabic) in the address, title or text.
    None when the name has no distinctive word or the page too little text
    to tell - then the site is read as usual."""
    from src.market_scraper.market_discovery.offerings import _word_in, normalize, tokens
    from src.market_scraper.market_discovery.relevance import _GENERAL

    words = {t for name in names or [] for t in tokens(name or "") if len(t) >= 3 and t not in _GENERAL}
    visible = _SPACE.sub(" ", unescape(_TAG.sub(" ", _SCRIPT.sub(" ", html)))).strip()
    if not words or len(visible) < 300:
        return None
    host = normalize((urlsplit(url).hostname or "").removeprefix("www.").replace(".", " ").replace("-", " "))
    joined = host.replace(" ", "")
    text = normalize(visible)
    text_words = list(set(text.split()))
    for word in words:
        if word.isascii() and (word in joined or _word_in(word, host.split())):
            return True
        if word in text or _word_in(word, text_words):
            return True
    return False


def _status(out: dict) -> str:
    products = [f for f in out["facts"] if f["kind"] == "product"]
    if any(p.get("price") is not None for p in products):
        return STATUS_PRICES
    if products or out["relevant_pages"]:
        return STATUS_NO_PRICES
    if out.get("needs_js"):
        return STATUS_JS
    return STATUS_NO_PAGE


def collect(website: str, fetch: Optional[Callable[[str], Optional[str]]] = None, country: Optional[str] = None,
            render: Optional[Callable[[str], Optional[str]]] = None, names: Optional[List[str]] = None,
            fetch_media: Optional[Callable[[str], Optional[Tuple[bytes, str]]]] = None,
            ocr: Optional[Callable] = None, deep: bool = False) -> dict:
    """Reads a competitor's site. Returns {"facts", "pages_read", "pages_blocked",
    "pages_failed", "status", "error", "platform"}; `fetch` (tests) returns a
    page's text, or None for a page that can't be read. With `names` (the
    business's names), a site that is plainly another business's - a wrong
    link in the public listing - is not read (STATUS_OTHER_BUSINESS).
    Menu PDFs and pictures found on the pages are read too (menu_media.py):
    `fetch_media` (tests) returns (bytes, content type) for such a file and
    `ocr` reads a picture; the outcome is in out["media"]. deep=True reads
    more pages, items and menu files (the owner's "load more")."""
    max_pages = DEEP_MAX_PAGES if deep else MAX_PAGES
    max_items = DEEP_MAX_ITEMS if deep else MAX_ITEMS
    max_media = DEEP_MAX_MEDIA if deep else menu_media.MAX_MEDIA_FILES
    url = website if "://" in website else f"https://{website}"
    if not own_site(url):  # a profile or directory page is not what the business publishes about itself
        return {"facts": [], "pages_read": [], "pages_blocked": 0, "pages_failed": 0, "error": STATUS_NOT_OWN_SITE,
                "status": STATUS_NOT_OWN_SITE, "platform": None, "relevant_pages": 0, "needs_js": False}
    country = site_country(url, country)
    out = {"facts": [], "pages_read": [], "pages_blocked": 0, "pages_failed": 0, "error": None, "status": None,
           "platform": None, "relevant_pages": 0, "needs_js": False,
           "media": {"found": 0, "read": 0, "skipped_no_ocr": 0, "ocr_available": None}}
    site = None
    if fetch is None:
        site = _Site(url)

        def fetch(target, kinds=("html",)):
            try:
                return site.text(target, kinds)
            except PageUnavailable as exc:
                if exc.reason == STATUS_ROBOTS:
                    out["pages_blocked"] += 1
                return None
    render = render if render is not None else (_render if site is not None else (lambda _u: None))
    def fetch_any(target):
        """Sitemaps and catalogues: one that can't be fetched is skipped."""
        try:
            return fetch(target, ("xml", "json", "text", "html")) if site is not None else fetch(target)
        except (httpx.HTTPError, UnsafeTargetError, UnicodeDecodeError, OSError):
            return None
    try:
        try:
            html = fetch(url)
        except UnsafeTargetError as exc:
            out["error"] = out["status"] = STATUS_UNREACHABLE if "DNS" in str(exc) else STATUS_NOT_PUBLIC
            return out
        except (httpx.HTTPError, UnicodeDecodeError, OSError):
            out["error"] = out["status"] = STATUS_UNREACHABLE
            return out
        if html is None:
            blocked = out["pages_blocked"] or site is None
            out["pages_blocked"] = max(out["pages_blocked"], 1)
            out["error"] = "not_allowed" if blocked else STATUS_HTTP
            out["status"] = STATUS_ROBOTS if blocked else STATUS_HTTP
            return out
        first = read_page(html, url, country, max_items)
        if first["text_chars"] < 300 and "<script" in html.lower():
            rendered = render(url)
            if rendered:
                first = read_page(rendered, url, country, max_items)
                html = rendered
            else:
                out["needs_js"] = True
        if names and names_the_business(names, url, html) is False:
            out["error"] = out["status"] = STATUS_OTHER_BUSINESS
            return out
        out["facts"].extend(first["facts"])
        out["pages_read"].append(url)
        media_urls: List[str] = []

        def note_media(page_html: str, page_url: str, relevant: bool) -> None:
            for link in menu_media.media_links(page_html, page_url, relevant, _same_site, max_media):
                if link not in media_urls:
                    media_urls.append(link)
        note_media(html, url, first.get("relevant", False))
        # The shop platform's own catalogue, when it publishes one (for the
        # whole host: not when the business owns only a path on it).
        lowered = html.lower() if path_scope(url) == "/" else ""
        if "cdn.shopify.com" in lowered or "shopify.theme" in lowered:
            out["platform"] = "shopify"
            body = fetch_any(urljoin(url, "/products.json?limit=250"))
            currency = (re.findall(r'"currency"\s*:\s*\{\s*"active"\s*:\s*"([A-Z]{3})"', html)
                        or re.findall(r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Z]{3})"', html) or [None])[0]
            items = shopify_products(_json(body), url, currency or _COUNTRY_CURRENCY.get(country or ""))
            out["facts"].extend(_catalog_facts(items, max_items))
        elif "woocommerce" in lowered or "wp-content/plugins/woocommerce" in lowered:
            out["platform"] = "woocommerce"
            body = fetch_any(urljoin(url, "/wp-json/wc/store/v1/products?per_page=100"))
            out["facts"].extend(_catalog_facts(woocommerce_products(_json(body), url), max_items))
        # The pages most likely to list products, a menu, prices or offers.
        robots_text = site.robots_text if site is not None else fetch_any(urljoin(url, "/robots.txt"))
        from_sitemaps = sitemap_urls(robots_text, url, fetch_any)
        pages = candidate_pages(html, url, from_sitemaps, max_pages)
        out["relevant_pages"] = 0
        for page in pages:
            if len(out["pages_read"]) > max_pages:
                break
            try:
                page_html = fetch(page)
            except (httpx.HTTPError, UnsafeTargetError, UnicodeDecodeError, OSError):
                out["pages_failed"] += 1
                continue
            if page_html is None:
                out["pages_failed"] += 1
                continue
            result = read_page(page_html, page, country, max_items)
            if result["text_chars"] < 300 and "<script" in page_html.lower():
                rendered = render(page)
                if rendered:
                    result = read_page(rendered, page, country, max_items)
                else:
                    out["needs_js"] = True
            out["relevant_pages"] += 1
            out["facts"].extend(f for f in result["facts"] if f["kind"] != "social")
            out["pages_read"].append(page)
            note_media(page_html, page, result.get("relevant", False))
        _read_media_files(out, media_urls, fetch_media if fetch_media is not None else (site.media if site is not None else None),
                          country, ocr, max_media, max_items)
    except Exception:  # noqa: BLE001 - one site's odd page never stops a scan
        logger.exception("reading %s failed", urlsplit(url).hostname)
        out["error"] = out["status"] = STATUS_FAILED
    finally:
        if site is not None:
            site.close()
    out["facts"] = _dedupe(out["facts"])
    out["status"] = out["status"] or _status(out)
    return out


def _read_media_files(out: dict, urls: List[str], fetch_media, country: Optional[str], ocr: Optional[Callable],
                      max_media: int = menu_media.MAX_MEDIA_FILES, max_items: int = MAX_ITEMS) -> None:
    """Reads the menu files found on the pages and merges their prices into
    out["facts"] (corroborating page facts where they agree)."""
    out["media"]["found"] = len(urls)
    if not urls or fetch_media is None:
        return
    out["media"]["ocr_available"] = ocr is not None or menu_media.ocr_available()
    retrieved, media = _now(), []
    for link in urls[:max_media]:
        try:
            got = fetch_media(link)
        except (httpx.HTTPError, UnsafeTargetError, OSError):
            got = None
        if not got:
            continue
        lines, method = menu_media.read_media(got[0], got[1], ocr=ocr, ocr_ready=out["media"]["ocr_available"])
        if method == "skipped_no_ocr":
            out["media"]["skipped_no_ocr"] += 1
        if not lines:
            continue
        found = menu_media.media_facts(lines, method, link, retrieved, country, text_prices, max_items)
        if found:
            out["media"]["read"] += 1
            media.extend(found)
    if media:
        out["facts"] = menu_media.corroborate(media, out["facts"])
        out["pages_read"].extend(dict.fromkeys(f["source_url"] for f in media))


def _json(body: Optional[str]):
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def _catalog_facts(items: List[dict], max_items: int = MAX_ITEMS) -> List[dict]:
    retrieved = _now()
    return [{"kind": "product", "source_url": item.pop("source_url"), "retrieved_at": retrieved,
             "confidence": CONFIDENCE_CATALOG, **item} for item in items[:max_items]]


def _dedupe(facts: List[dict]) -> List[dict]:
    """One entry per product name / message / link, keeping the most confident;
    the same product at two different prices is kept twice (a conflict to show)."""
    best = {}
    for fact in facts:
        if fact["kind"] == "product":
            key = ("product", fact["name"].lower(), fact.get("price"), fact.get("currency"))
        elif fact["kind"] == "social":
            key = ("social", fact["url"].rstrip("/").lower())
        else:
            key = (fact["kind"], fact["text"].lower())
        if key not in best or fact["confidence"] > best[key]["confidence"]:
            best[key] = fact
    return list(best.values())
