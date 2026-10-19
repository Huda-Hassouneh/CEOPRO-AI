import json

from scrapy.http import HtmlResponse, Request

from src.market_scraper.spiders.books_to_scrape import BooksToScrapeSpider


DETAIL_HTML = b"""
<html><body>
<ul class="breadcrumb"><li>Home</li><li>Books</li><li><a>Travel</a></li><li>Book</li></ul>
<div class="item active"><img src="../../media/cache/book.jpg"></div>
<div class="product_main">
  <h1>A Light in the Attic</h1><p class="price_color">\xc2\xa351.77</p>
  <p class="instock availability"> <i class="icon-ok"></i> In stock (22 available) </p>
  <p class="star-rating Three"></p>
</div>
<div id="product_description"></div><p>A useful description.</p>
<table class="table table-striped">
  <tr><th>UPC</th><td>a897fe39b1053632</td></tr>
  <tr><th>Availability</th><td>In stock (22 available)</td></tr>
  <tr><th>Number of reviews</th><td>3</td></tr>
</table>
</body></html>
"""


def response_for(url, body):
    request = Request(url=url)
    return HtmlResponse(url=url, request=request, body=body, encoding="utf-8")


def test_parse_product_emits_normalized_market_record():
    spider = BooksToScrapeSpider()
    response = response_for(
        "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        DETAIL_HTML,
    )
    listing = {
        "product_name": "fallback",
        "price_text": "\u00a351.77",
        "availability_text": "In stock",
        "rating_classes": ["star-rating", "Two"],
        "image_url": "https://books.toscrape.com/fallback.jpg",
    }

    record = list(spider.parse_product(response, listing))[0]

    assert record["external_id"] == "a897fe39b1053632"
    assert record["product_name"] == "A Light in the Attic"
    assert record["category"] == "Travel"
    assert record["price_amount"] == 51.77
    assert record["currency"] == "GBP"
    assert record["stock_quantity"] == 22
    assert record["is_available"] is True
    assert record["rating"] == 3
    assert record["review_count"] == 3
    assert record["product_url"] == response.url
    assert record["captured_at"].endswith("Z")


def test_mapped_target_carries_tenant_and_mapping_lineage():
    target = {
        "mapping_id": "mapping-1",
        "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "external_sku": "external-1",
        "competitor_name": "Demo Competitor",
        "product_id": "product-1",
        "global_competitor_id": "competitor-1",
        "product_name": "A Light in the Attic",
    }
    spider = BooksToScrapeSpider(
        targets_json=json.dumps([target]),
        tenant_id="tenant-1",
        source_id="source-1",
        job_id="job-1",
    )
    request = list(spider._initial_requests())[0]
    response = response_for(target["product_url"], DETAIL_HTML)
    record = list(spider.parse_product(response, request.cb_kwargs["listing"], target))[0]

    assert request.dont_filter is True
    assert record["tenant_id"] == "tenant-1"
    assert record["source_id"] == "source-1"
    assert record["job_id"] == "job-1"
    assert record["mapping_id"] == "mapping-1"
    assert record["competitor_name"] == "Demo Competitor"
    assert record["match_score"] >= 0.82
    assert record["match_method"] == "FUZZY_NAME"
    assert record["safety_status"] == "SAFE"


def test_spider_rejects_unapproved_start_domain():
    try:
        BooksToScrapeSpider(start_url="https://example.com/")
    except ValueError as exc:
        assert "approved" in str(exc)
    else:
        raise AssertionError("unapproved domain was accepted")
