from unittest.mock import patch

from src.market_scraper.sitemap_discovery import (
    _discover_sitemap_urls, _parse_sitemap, _slug_text, discover_products_via_sitemap,
)

URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.test/products/arduino-uno-r3.html</loc></url>
  <url><loc>https://example.test/blog/how-to-solder</loc></url>
  <url><loc>https://example.test/products/raspberry-pi-4-model-b</loc></url>
</urlset>
"""

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.test/sitemap-products.xml</loc></sitemap>
  <sitemap><loc>https://example.test/sitemap-blog.xml</loc></sitemap>
</sitemapindex>
"""


def test_slug_text_strips_extension_and_splits_on_separators():
    assert _slug_text("https://example.test/products/arduino-uno-r3.html") == "arduino uno r3"


def test_slug_text_handles_trailing_slash():
    assert _slug_text("https://example.test/products/raspberry-pi-4/") == "raspberry pi 4"


def test_parse_sitemap_urlset_returns_page_urls_only():
    child_sitemaps, page_urls = _parse_sitemap(URLSET_XML, "https://example.test/sitemap.xml")
    assert child_sitemaps == []
    assert page_urls == [
        "https://example.test/products/arduino-uno-r3.html",
        "https://example.test/blog/how-to-solder",
        "https://example.test/products/raspberry-pi-4-model-b",
    ]


def test_parse_sitemap_index_returns_child_sitemaps_only():
    child_sitemaps, page_urls = _parse_sitemap(SITEMAP_INDEX_XML, "https://example.test/sitemap.xml")
    assert page_urls == []
    assert child_sitemaps == [
        "https://example.test/sitemap-products.xml",
        "https://example.test/sitemap-blog.xml",
    ]


def test_parse_sitemap_malformed_xml_returns_empty_not_raises():
    assert _parse_sitemap("<not valid xml", "https://example.test/sitemap.xml") == ([], [])


def test_discover_sitemap_urls_prefers_robots_txt_declared_sitemaps():
    robots_txt = "User-agent: *\nDisallow: /admin\nSitemap: https://example.test/sitemap-a.xml\nSitemap: https://example.test/sitemap-b.xml\n"
    with patch("src.market_scraper.sitemap_discovery._fetch", return_value=robots_txt):
        urls = _discover_sitemap_urls("example.test")
    assert urls == ["https://example.test/sitemap-a.xml", "https://example.test/sitemap-b.xml"]


def test_discover_sitemap_urls_falls_back_to_conventional_path():
    with patch("src.market_scraper.sitemap_discovery._fetch", return_value="User-agent: *\nDisallow:\n"):
        urls = _discover_sitemap_urls("example.test")
    assert urls == ["https://example.test/sitemap.xml"]


def test_returns_empty_list_when_robots_disallows_the_domain():
    with patch("src.market_scraper.sitemap_discovery._fetch_robots_allows", return_value=False):
        candidates = discover_products_via_sitemap("example.test", "Arduino Uno")
    assert candidates == []


def test_finds_and_scores_real_product_urls_over_unrelated_pages():
    with patch("src.market_scraper.sitemap_discovery._fetch_robots_allows", return_value=True), \
         patch("src.market_scraper.sitemap_discovery._discover_sitemap_urls", return_value=["https://example.test/sitemap.xml"]), \
         patch("src.market_scraper.sitemap_discovery._fetch", return_value=URLSET_XML):
        candidates = discover_products_via_sitemap("example.test", "Arduino Uno R3")

    urls = [c.url for c in candidates]
    assert "https://example.test/products/arduino-uno-r3.html" in urls
    assert "https://example.test/blog/how-to-solder" not in urls


def test_follows_a_sitemap_index_into_its_child_sitemaps():
    responses = {
        "https://example.test/sitemap.xml": SITEMAP_INDEX_XML,
        "https://example.test/sitemap-products.xml": URLSET_XML,
        "https://example.test/sitemap-blog.xml": "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"></urlset>",
    }
    with patch("src.market_scraper.sitemap_discovery._fetch_robots_allows", return_value=True), \
         patch("src.market_scraper.sitemap_discovery._discover_sitemap_urls", return_value=["https://example.test/sitemap.xml"]), \
         patch("src.market_scraper.sitemap_discovery._fetch", side_effect=lambda url: responses.get(url)), \
         patch("src.market_scraper.sitemap_discovery.time.sleep"):
        candidates = discover_products_via_sitemap("example.test", "Raspberry Pi 4")

    assert any(c.url == "https://example.test/products/raspberry-pi-4-model-b" for c in candidates)


def test_max_sitemaps_to_fetch_bounds_a_runaway_sitemap_index():
    # A sitemap index that always points to more child sitemaps, never a urlset -
    # without a bound this would loop forever.
    def infinite_index(url):
        return f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>{url}?p=2</loc></sitemap>
        </sitemapindex>"""

    with patch("src.market_scraper.sitemap_discovery._fetch_robots_allows", return_value=True), \
         patch("src.market_scraper.sitemap_discovery._discover_sitemap_urls", return_value=["https://example.test/sitemap.xml"]), \
         patch("src.market_scraper.sitemap_discovery._fetch", side_effect=infinite_index), \
         patch("src.market_scraper.sitemap_discovery.time.sleep"):
        candidates = discover_products_via_sitemap("example.test", "Anything", max_sitemaps_to_fetch=5)

    assert candidates == []


def test_limit_caps_the_number_of_returned_candidates():
    many_urls_xml = "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(
        f"<url><loc>https://example.test/products/arduino-uno-r3-variant-{i}</loc></url>" for i in range(10)
    ) + "</urlset>"
    with patch("src.market_scraper.sitemap_discovery._fetch_robots_allows", return_value=True), \
         patch("src.market_scraper.sitemap_discovery._discover_sitemap_urls", return_value=["https://example.test/sitemap.xml"]), \
         patch("src.market_scraper.sitemap_discovery._fetch", return_value=many_urls_xml):
        candidates = discover_products_via_sitemap("example.test", "Arduino Uno R3", limit=3)

    assert len(candidates) == 3
