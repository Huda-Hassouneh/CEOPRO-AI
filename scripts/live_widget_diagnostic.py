"""
Live diagnostic for the JS-widget review fallback (market_source.py's
_extract_microdata_products / _widget_reviews). Renders a real product
page with a real headless browser (so any client-side review widget gets
its chance to run, exactly like render_javascript=True does in
production via scrapy-playwright), then runs the SAME real extraction
functions this codebase's spider uses - not a reimplementation - against
the rendered HTML:

  1. JSON-LD (already existed)
  2. Microdata via extruct (this sprint's new fallback)
  3. If still nothing: scans the rendered DOM for known review-widget
     vendor signatures and prints a real snippet of the surrounding HTML,
     so the actual CSS selectors needed for widget_review_container/
     widget_review_text/etc. (market_source.py's third fallback) can be
     read off real markup - never guessed.

This script does NOT know or invent Bazaarvoice/Yotpo/Trustpilot's
current CSS class names - nobody in this session has inspected their
live DOM. What it prints is real, from the actual rendered page; turning
that into a reviewed collector_config selector set is a separate, human
step, same discipline as every other HTML selector in this codebase.

Run from the repo root (needs `playwright install chromium` done once,
and normal outbound internet - this sandbox's own network egress is
blocked to arbitrary third-party domains, which is exactly why this is
a script for you to run, not something this session could execute
itself):

    python scripts/live_widget_diagnostic.py https://www.sparkfun.com/arduino-uno-r3.html
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright

from src.market_scraper.spiders.market_source import (
    MarketSourceSpider, _extract_microdata_products, _walk_json,
)

REVIEW_WIDGET_SIGNATURES = {
    "Bazaarvoice": ["bazaarvoice", "bvapi", "bv-content"],
    "Yotpo": ["yotpo"],
    "PowerReviews": ["powerreviews", "pr-review"],
    "Okendo": ["okendo"],
    "Judge.me": ["judge.me", "jdgm-"],
    "Stamped.io": ["stamped.io", "stamped-"],
    "Junip": ["junip"],
    "Trustpilot": ["trustpilot"],
    "Reviews.io": ["reviews.io"],
}

_LD_JSON_BLOCK_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE,
)


def render(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent="CEOPRO-MarketResearchBot/1.0")
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()
        return html


def extract_jsonld_products(html: str) -> list:
    products = []
    for raw in _LD_JSON_BLOCK_RE.findall(html):
        try:
            document = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        products.extend(node for node in _walk_json(document) if MarketSourceSpider._is_product(node))
    return products


def find_widget_snippets(html: str, context_chars: int = 400) -> dict:
    lowered = html.lower()
    found = {}
    for vendor, signatures in REVIEW_WIDGET_SIGNATURES.items():
        for sig in signatures:
            idx = lowered.find(sig.lower())
            if idx != -1:
                start = max(0, idx - context_chars // 2)
                end = min(len(html), idx + context_chars // 2)
                found[vendor] = html[start:end]
                break
    return found


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/live_widget_diagnostic.py <product_url>")
        raise SystemExit(1)
    url = sys.argv[1]

    print(f"Rendering (real headless browser, JS executed): {url}")
    html = render(url)
    print(f"Rendered HTML length: {len(html)} chars\n")

    jsonld_products = extract_jsonld_products(html)
    print(f"JSON-LD Product nodes found: {len(jsonld_products)}")
    for p in jsonld_products:
        reviews = p.get("review") or p.get("reviews")
        print(f"  - {p.get('name')!r}: review data present = {bool(reviews)}")

    microdata_products = _extract_microdata_products(html)
    print(f"\nMicrodata Product nodes found: {len(microdata_products)}")
    for p in microdata_products:
        reviews = p.get("review") or p.get("reviews")
        print(f"  - {p.get('name')!r}: review data present = {bool(reviews)}")

    any_reviews = any((p.get("review") or p.get("reviews")) for p in jsonld_products + microdata_products)
    if any_reviews:
        print("\nStructured review data found after JS rendering - no widget_review_* selectors needed for this page.")
        return

    print("\nNo structured review data in either JSON-LD or microdata, even after full JS rendering.")
    print("Scanning rendered DOM for known review-widget vendor signatures...\n")
    snippets = find_widget_snippets(html)
    if not snippets:
        print("No known vendor signature found either - this page likely just has no reviews, "
              "or uses an unrecognized system. Re-run live_deep_crawl_validation.py's "
              "detect_review_keyword_hints()-style check for a broader (noisier) sweep.")
        return

    for vendor, snippet in snippets.items():
        print(f"[{vendor}] real rendered-DOM snippet around the first match:")
        print(f"  ...{snippet}...\n")
    print(
        "Read the real class/id names above and configure widget_review_container/"
        "widget_review_text/widget_reviewer_name/widget_review_rating/widget_review_date "
        "in this source's collector_config[\"selectors\"] - market_source.py's "
        "_widget_reviews() will then pick them up automatically."
    )


if __name__ == "__main__":
    main()
