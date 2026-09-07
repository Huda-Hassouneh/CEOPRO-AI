"""
Real, credentialed smoke tests for every paid/official collector this
codebase has - ScrapeCreators, Apify (social_data_provider), Amazon
PA-API, Digi-Key, Mouser. Each one is SKIPPED (not failed) when its real
credentials aren't set in the environment - this script never fabricates
a "pass" with mock/fake credentials, since a fake key would just prove
the collector can call urllib, not that it actually works against the
real vendor. Given real credentials, it runs exactly ONE real API call
per vendor through that vendor's own real production spider code
(_initial_requests() builds the real signed/authenticated request; the
real parse_*/parse_item callback parses whatever comes back) - not a
reimplementation, so this proves the actual code path works, or shows
exactly how it fails.

This sandbox cannot run this script itself: no vendor credentials are
configured anywhere in this environment, and this sandbox's own network
egress is blocked to arbitrary third-party domains (the same restriction
documented throughout this session). This is exactly why it's a script
for you to run in your own environment with your own real keys, not
something this session can execute and report on directly.

Set only the env vars for the vendor(s) you want to test - anything
unset is skipped, never guessed:

  SCRAPE_CREATORS_API_KEY, SCRAPE_CREATORS_TEST_URL (a real public FB/IG/TikTok post URL)
  APIFY_API_TOKEN, APIFY_TEST_URL (a real public FB/IG/TikTok profile or post URL)
  AMAZON_PAAPI_ACCESS_KEY, AMAZON_PAAPI_SECRET_KEY, AMAZON_PAAPI_PARTNER_TAG, AMAZON_PAAPI_TEST_ASIN
  DIGIKEY_CLIENT_ID, DIGIKEY_CLIENT_SECRET, DIGIKEY_TEST_PART_NUMBER
  MOUSER_API_KEY, MOUSER_TEST_PART_NUMBER

Run from the repo root:
    python scripts/live_credential_smoke_tests.py
"""
import json
import os
import urllib.error
import urllib.request

from scrapy.http import Request, TextResponse

TEST_TARGET = {
    "mapping_id": "smoke-test", "product_id": "smoke-test", "global_competitor_id": "smoke-test",
    "product_url": "", "external_sku": "", "product_name": "smoke test", "competitor_name": "smoke test",
}


def _execute(request: Request) -> TextResponse:
    """Real HTTP call using the exact url/method/headers/body a real
    scrapy.Request already carries - bypasses Scrapy's engine (this
    script has no CrawlerProcess) but makes the identical real network
    call the engine would, then wraps the real response the same way
    every test fixture in this codebase already does."""
    req = urllib.request.Request(
        request.url, data=request.body or None, method=request.method,
        headers={k.decode(): v[0].decode() for k, v in request.headers.items()},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read()
    return TextResponse(url=request.url, request=request, body=body, encoding="utf-8")


def test_scrape_creators():
    api_key = os.getenv("SCRAPE_CREATORS_API_KEY")
    test_url = os.getenv("SCRAPE_CREATORS_TEST_URL")
    if not api_key or not test_url:
        print("[SKIP] scrape_creators - SCRAPE_CREATORS_API_KEY/SCRAPE_CREATORS_TEST_URL not set")
        return
    from src.market_scraper.spiders.scrape_creators import ScrapeCreatorsSpider

    spider = ScrapeCreatorsSpider(
        source_url="https://api.scrapecreators.com", source_name="ScrapeCreators smoke test",
        collection_method="OFFICIAL_API", targets_json=json.dumps([{**TEST_TARGET, "product_url": test_url}]),
        tenant_id="smoke", source_id="smoke", job_id="smoke",
        credentials_json=json.dumps({"api_key": api_key}),
    )
    request = next(iter(spider._initial_requests()))
    print(f"[RUN] scrape_creators -> {request.url}")
    try:
        response = _execute(request)
    except urllib.error.HTTPError as e:
        print(f"[FAIL] scrape_creators - HTTP {e.code}: {e.read()[:500]}")
        return
    results = list(spider.parse_post(response, **request.cb_kwargs))
    print(f"[{'PASS' if results else 'EMPTY'}] scrape_creators - {len(results)} record(s) parsed")
    for r in results[:1]:
        print(json.dumps(r, indent=2, default=str)[:1000])


def test_apify_social_data_provider():
    api_token = os.getenv("APIFY_API_TOKEN")
    test_url = os.getenv("APIFY_TEST_URL")
    if not api_token or not test_url:
        print("[SKIP] social_data_provider (Apify) - APIFY_API_TOKEN/APIFY_TEST_URL not set")
        return
    from src.market_scraper.spiders.social_data_provider import SocialDataProviderSpider

    spider = SocialDataProviderSpider(
        source_url="https://api.apify.com", source_name="Apify smoke test",
        collection_method="OFFICIAL_API", targets_json=json.dumps([{**TEST_TARGET, "product_url": test_url}]),
        tenant_id="smoke", source_id="smoke", job_id="smoke",
        credentials_json=json.dumps({"api_token": api_token}),
    )
    request = next(iter(spider._initial_requests()))
    print(f"[RUN] social_data_provider (Apify) -> {request.url}")
    try:
        response = _execute(request)
    except urllib.error.HTTPError as e:
        print(f"[FAIL] social_data_provider - HTTP {e.code}: {e.read()[:500]}")
        return
    results = list(spider.parse_dataset_items(response, **request.cb_kwargs))
    print(f"[{'PASS' if results else 'EMPTY'}] social_data_provider - {len(results)} record(s) parsed")
    for r in results[:1]:
        print(json.dumps(r, indent=2, default=str)[:1000])


def test_amazon_paapi():
    access_key = os.getenv("AMAZON_PAAPI_ACCESS_KEY")
    secret_key = os.getenv("AMAZON_PAAPI_SECRET_KEY")
    partner_tag = os.getenv("AMAZON_PAAPI_PARTNER_TAG")
    asin = os.getenv("AMAZON_PAAPI_TEST_ASIN")
    if not all((access_key, secret_key, partner_tag, asin)):
        print("[SKIP] amazon_paapi - AMAZON_PAAPI_ACCESS_KEY/SECRET_KEY/PARTNER_TAG/TEST_ASIN not all set")
        return
    from src.market_scraper.spiders.amazon_paapi import AmazonPricingSpider

    spider = AmazonPricingSpider(
        source_url="https://webservices.amazon.com/paapi5/getitems", source_name="Amazon PA-API smoke test",
        collection_method="OFFICIAL_API",
        targets_json=json.dumps([{**TEST_TARGET, "external_sku": asin, "product_url": f"https://www.amazon.com/dp/{asin}"}]),
        tenant_id="smoke", source_id="smoke", job_id="smoke",
        credentials_json=json.dumps({"access_key": access_key, "secret_key": secret_key, "partner_tag": partner_tag}),
    )
    request = next(iter(spider._initial_requests()))
    print(f"[RUN] amazon_paapi -> {request.url} (ASIN {asin})")
    try:
        response = _execute(request)
    except urllib.error.HTTPError as e:
        print(f"[FAIL] amazon_paapi - HTTP {e.code}: {e.read()[:500]}")
        return
    results = list(spider.parse_item(response, **request.cb_kwargs))
    print(f"[{'PASS' if results else 'EMPTY'}] amazon_paapi - {len(results)} record(s) parsed")
    for r in results[:1]:
        print(json.dumps(r, indent=2, default=str)[:1000])


def test_digikey():
    client_id = os.getenv("DIGIKEY_CLIENT_ID")
    client_secret = os.getenv("DIGIKEY_CLIENT_SECRET")
    part_number = os.getenv("DIGIKEY_TEST_PART_NUMBER")
    if not all((client_id, client_secret, part_number)):
        print("[SKIP] digikey_api - DIGIKEY_CLIENT_ID/CLIENT_SECRET/TEST_PART_NUMBER not all set")
        return
    from src.market_scraper.spiders.digikey_api import DigiKeyPricingSpider

    spider = DigiKeyPricingSpider(
        source_url="https://api.digikey.com/products/v4/search", source_name="Digi-Key smoke test",
        collection_method="OFFICIAL_API",
        targets_json=json.dumps([{**TEST_TARGET, "external_sku": part_number}]),
        tenant_id="smoke", source_id="smoke", job_id="smoke",
        credentials_json=json.dumps({"client_id": client_id, "client_secret": client_secret}),
    )
    try:
        request = next(iter(spider._initial_requests()))
    except Exception as e:
        print(f"[FAIL] digikey_api - could not obtain OAuth2 token: {e!r}")
        return
    print(f"[RUN] digikey_api -> {request.url}")
    try:
        response = _execute(request)
    except urllib.error.HTTPError as e:
        print(f"[FAIL] digikey_api - HTTP {e.code}: {e.read()[:1000]} "
              "(this is exactly the real response body that tells us if the field-name guesses need correcting)")
        return
    results = list(spider.parse_item(response, **request.cb_kwargs))
    print(f"[{'PASS' if results else 'EMPTY - check field_overrides against the raw response above'}] "
          f"digikey_api - {len(results)} record(s) parsed")
    for r in results[:1]:
        print(json.dumps(r, indent=2, default=str)[:1000])


def test_mouser():
    api_key = os.getenv("MOUSER_API_KEY")
    part_number = os.getenv("MOUSER_TEST_PART_NUMBER")
    if not all((api_key, part_number)):
        print("[SKIP] mouser_api - MOUSER_API_KEY/TEST_PART_NUMBER not all set")
        return
    from src.market_scraper.spiders.mouser_api import MouserPricingSpider

    spider = MouserPricingSpider(
        source_url="https://api.mouser.com/api/v1/search/partnumber", source_name="Mouser smoke test",
        collection_method="OFFICIAL_API",
        targets_json=json.dumps([{**TEST_TARGET, "external_sku": part_number}]),
        tenant_id="smoke", source_id="smoke", job_id="smoke",
        credentials_json=json.dumps({"api_key": api_key}),
    )
    request = next(iter(spider._initial_requests()))
    print(f"[RUN] mouser_api -> {request.url}")
    try:
        response = _execute(request)
    except urllib.error.HTTPError as e:
        print(f"[FAIL] mouser_api - HTTP {e.code}: {e.read()[:1000]} "
              "(this is exactly the real response body that tells us if the field-name guesses need correcting)")
        return
    results = list(spider.parse_item(response, **request.cb_kwargs))
    print(f"[{'PASS' if results else 'EMPTY - check field_overrides against the raw response above'}] "
          f"mouser_api - {len(results)} record(s) parsed")
    for r in results[:1]:
        print(json.dumps(r, indent=2, default=str)[:1000])


if __name__ == "__main__":
    for fn in (test_scrape_creators, test_apify_social_data_provider, test_amazon_paapi, test_digikey, test_mouser):
        try:
            fn()
        except Exception as e:
            print(f"[ERROR] {fn.__name__} raised an unexpected exception: {e!r}")
        print()
