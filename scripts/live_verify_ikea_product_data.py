"""
Live audit for Ikea: does market_source.py's real parsing (JSON-LD ->
microdata -> reviewed HTML selectors) actually find price/rating/review
data on a real Ikea product page, and does robots.txt even permit
fetching it? No dedicated Ikea spider exists in this codebase and Ikea
isn't in RETAILER_DOMAINS_BY_VERTICAL - the only path that could ever
work for Ikea today is the generic `standards` collector
(market_source.py), and nobody has verified it actually works there.
"Assuming it works" was flagged as the real risk; this is the real check.

Note on scope: Amazon is NOT included here on purpose. Amazon already
has a real, legitimate path - the official PA-API collector
(amazon_paapi.py), smoke-tested by live_credential_smoke_tests.py with
real credentials. Generically scraping amazon.com product pages directly
(bypassing PA-API) is both unnecessary (a real official API already
exists) and the same ToS-risk category this codebase has consistently
avoided for every other platform with an API alternative - so it isn't
built or verified here, by design, not by oversight.

Reuses the exact same real production functions live_deep_crawl_
validation.py already proved out this session (_extract_microdata_
products, _walk_json, MarketSourceSpider._is_product/_normalize_rating/
_reviews) plus discovery.py's real robots.txt check - not a
reimplementation.

Run from the repo root (needs normal outbound internet - this sandbox's
own egress is blocked to third-party domains, same restriction as every
other live-verify script this session):

    python scripts/live_verify_ikea_product_data.py https://www.ikea.com/us/en/p/some-product-12345678/
"""
import json
import re
import sys
import urllib.request

from src.market_scraper.discovery import _fetch_robots_allows
from src.market_scraper.spiders.market_source import (
    MarketSourceSpider, _extract_microdata_products, _walk_json,
)

_USER_AGENT = "CEOPRO-MarketResearchBot/1.0"
_LD_JSON_BLOCK_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE,
)
_SPIDER = MarketSourceSpider.__new__(MarketSourceSpider)


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  FETCH FAILED: {e!r}")
        return None


def extract_jsonld_products(html: str) -> list:
    products = []
    for raw in _LD_JSON_BLOCK_RE.findall(html):
        try:
            document = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        products.extend(node for node in _walk_json(document) if MarketSourceSpider._is_product(node))
    return products


def report(url: str):
    print(f"Checking robots.txt for: {url}")
    allowed = _fetch_robots_allows(url)
    print(f"  robots.txt allows this path: {allowed}")
    if allowed is not True:
        print("  STOPPING: not fetching a robots.txt-disallowed (or unreadable) page.")
        return

    html = _fetch(url)
    if not html:
        return

    jsonld_products = extract_jsonld_products(html)
    microdata_products = _extract_microdata_products(html)
    print(f"\n  JSON-LD Product nodes: {len(jsonld_products)}")
    print(f"  Microdata Product nodes: {len(microdata_products)}")

    for label, products in (("JSON-LD", jsonld_products), ("microdata", microdata_products)):
        for product in products:
            offers = product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price") or offers.get("lowPrice")
            currency = offers.get("priceCurrency")
            aggregate = product.get("aggregateRating") or {}
            rating = MarketSourceSpider._normalize_rating(aggregate) if aggregate else None
            reviews = _SPIDER._reviews(product.get("review") or product.get("reviews"), {"mapping_id": "audit"})
            print(f"\n  --- {label} product: {product.get('name')!r} ---")
            print(f"    price: {price} {currency}")
            print(f"    rating (normalized 0-5): {rating}")
            print(f"    reviews with text: {len(reviews)}")
            for r in reviews[:2]:
                print(f"      - {r['review_text'][:100]!r} (rating={r['review_rating']})")

    if not jsonld_products and not microdata_products:
        print("\n  NEITHER JSON-LD NOR MICRODATA FOUND ANY PRODUCT DATA ON THIS PAGE.")
        print("  This means the generic `standards` collector cannot collect from Ikea as-is for this page -")
        print("  either Ikea doesn't publish structured product data here, or it needs render_javascript=True")
        print("  + a reviewed widget_review_* / HTML selector set, same as the SparkFun/Trustpilot case this session.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/live_verify_ikea_product_data.py <ikea_product_url>")
        raise SystemExit(1)
    report(sys.argv[1])
