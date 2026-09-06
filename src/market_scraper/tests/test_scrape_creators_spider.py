import json

import pytest
from scrapy.http import Request, TextResponse

from src.market_scraper.spiders.scrape_creators import ScrapeCreatorsSpider, _platform_for
from src.market_scraper.spiders.social_data_provider import PaidProviderNotConfiguredError

TARGET_FB = {
    "mapping_id": "mapping-1", "product_id": "product-1",
    "global_competitor_id": "competitor-1",
    "product_url": "https://www.facebook.com/examplebrand/posts/1206903601483960",
    "external_sku": None, "product_name": "Trail Shoe", "competitor_name": "Example Retail",
}

CREDENTIALS = json.dumps({"api_key": "sc-test-key-123"})

POST_RESPONSE = {"success": True, "id": "1206903601483960", "description": "Snack recipe post"}

# The exact real payload the user pulled from ScrapeCreators' own docs
# (Facebook comments endpoint) - trimmed to 2 of the 10 comments for
# test brevity, field shapes kept identical.
COMMENTS_PAGE_1 = {
    "success": True,
    "credits_remaining": 49999299370,
    "credits_charged": 1,
    "comments": [
        {
            "id": "Y29tbWVudDoxMjA2OTAzNjAxNDgzOTYwXzc3OTIzNDI4MTE0NjkzNQ==",
            "text": "Do 1/2 mini Oreos and 1/2 peanut butter ritz Bitz, otherwise the same recipe. It's the BEST",
            "created_at": "2025-09-01T01:10:40.000Z",
            "reply_count": 1,
            "reaction_count": 95,
            "reactions": {
                "thankful": 0, "like": 79, "love": 4, "care": 0, "haha": 1,
                "wow": 11, "sad": 0, "anger": 0, "pride": 0, "confused": 0,
            },
            "author": {
                "id": "pfbid02SdzVLPYTHY2eGMdrwFrLw54sVZdguAGnLUj4RPL3HxFtG2D4PBBjptiMEwpB21Ehl",
                "name": "Robin Bergsagel", "gender": "FEMALE", "short_name": "Robin",
            },
        },
        {
            "id": "Y29tbWVudDoxMjA2OTAzNjAxNDgzOTYwXzEyODEyNTE3NjM3NTEwODM=",
            "text": "Sabrina Cox Jasmin Cox okay but hear me out, dark chocolate chips",
            "created_at": "2025-09-01T01:31:04.000Z",
            "reply_count": 3,
            "reaction_count": 45,
            "reactions": {
                "thankful": 0, "like": 37, "love": 6, "care": 0, "haha": 0,
                "wow": 1, "sad": 0, "anger": 1, "pride": 0, "confused": 0,
            },
            "author": {
                "id": "pfbid02616R2TFi1idG4Ek5teDkCRbr2ikn3gyXnyAZreGVsyiNPPCeWuk12xmQuaczZoRl",
                "name": "Brittani Crosby", "gender": "FEMALE", "short_name": "Brittani",
            },
        },
    ],
    "cursor": "MToxNzc2NDYxMjMwOgF......",
    "has_next_page": True,
}

COMMENTS_PAGE_2 = {**COMMENTS_PAGE_1, "comments": [], "has_next_page": False, "cursor": None}


def spider(targets=None, credentials=CREDENTIALS, collector_config=None):
    return ScrapeCreatorsSpider(
        source_url="https://api.scrapecreators.com",
        source_name="ScrapeCreators", collection_method="OFFICIAL_API",
        targets_json=json.dumps(targets if targets is not None else [TARGET_FB]),
        tenant_id="tenant-1", source_id="source-1", job_id="job-1",
        credentials_json=credentials,
        collector_config_json=json.dumps(collector_config or {}),
    )


def json_response(url, payload):
    request = Request(url=url)
    return TextResponse(url=url, request=request, body=json.dumps(payload).encode(), encoding="utf-8")


def test_missing_api_key_is_rejected_before_any_request():
    with pytest.raises(PaidProviderNotConfiguredError, match="api_key"):
        ScrapeCreatorsSpider(
            source_url="https://api.scrapecreators.com",
            source_name="ScrapeCreators", collection_method="OFFICIAL_API",
            targets_json=json.dumps([TARGET_FB]), tenant_id="t", source_id="s", job_id="j",
        )


@pytest.mark.parametrize("url,expected", [
    ("https://www.facebook.com/examplebrand/posts/1", "facebook"),
    ("https://www.instagram.com/p/abc/", "instagram"),
    ("https://www.tiktok.com/@brand/video/1", "tiktok"),
    ("https://examplebrand.com", None),
])
def test_platform_for_recognizes_known_social_hosts(url, expected):
    assert _platform_for(url) == expected


def test_initial_requests_use_x_api_key_header_not_a_url_token():
    requests = list(spider()._initial_requests())
    assert len(requests) == 1
    request = requests[0]
    assert request.headers[b"x-api-key"] == b"sc-test-key-123"
    assert "api_key" not in request.url and "token" not in request.url
    assert request.url.startswith("https://api.scrapecreators.com/v1/facebook/post/?")
    assert "url=" in request.url


def test_initial_requests_skip_targets_with_no_recognized_social_url():
    unmapped = {**TARGET_FB, "mapping_id": "mapping-2", "product_url": "https://example.com/store"}
    requests = list(spider([TARGET_FB, unmapped])._initial_requests())
    assert len(requests) == 1


def test_parse_post_issues_a_comments_request_by_default():
    requests = list(spider().parse_post(
        json_response("https://api.scrapecreators.com/v1/facebook/post/", POST_RESPONSE),
        TARGET_FB, "facebook", TARGET_FB["product_url"],
    ))
    assert len(requests) == 1
    request = requests[0]
    assert request.headers[b"x-api-key"] == b"sc-test-key-123"
    assert request.url.startswith("https://api.scrapecreators.com/v1/facebook/post/comments?")


def test_fetch_comments_false_yields_the_item_directly():
    no_comments = spider(collector_config={"fetch_comments": False})
    results = list(no_comments.parse_post(
        json_response("https://api.scrapecreators.com/v1/facebook/post/", POST_RESPONSE),
        TARGET_FB, "facebook", TARGET_FB["product_url"],
    ))
    assert len(results) == 1
    assert isinstance(results[0], dict)
    assert results[0]["reviews"] == []


def test_parse_post_stops_on_reported_failure():
    results = list(spider().parse_post(
        json_response("https://api.scrapecreators.com/v1/facebook/post/", {"success": False}),
        TARGET_FB, "facebook", TARGET_FB["product_url"],
    ))
    assert results == []


def test_comments_pagination_follows_cursor_until_has_next_page_false():
    page_1_results = list(spider().parse_comments_page(
        json_response("https://api.scrapecreators.com/v1/facebook/post/comments", COMMENTS_PAGE_1),
        TARGET_FB, "facebook", POST_RESPONSE, TARGET_FB["product_url"], [], 1, 0,
    ))
    assert len(page_1_results) == 1
    next_request = page_1_results[0]
    assert "cursor=" in next_request.url

    final_item = list(spider().parse_comments_page(
        json_response("https://api.scrapecreators.com/v1/facebook/post/comments", COMMENTS_PAGE_2),
        TARGET_FB, "facebook", POST_RESPONSE, TARGET_FB["product_url"],
        next_request.cb_kwargs["accumulated"], next_request.cb_kwargs["page"],
        next_request.cb_kwargs["post_credits_spent"],
    ))[0]
    assert len(final_item["reviews"]) == 2


def test_comments_pagination_respects_max_comment_pages():
    bounded = spider(collector_config={"max_comment_pages": 1})
    results = list(bounded.parse_comments_page(
        json_response("https://api.scrapecreators.com/v1/facebook/post/comments", COMMENTS_PAGE_1),
        TARGET_FB, "facebook", POST_RESPONSE, TARGET_FB["product_url"], [], 1, 0,
    ))
    assert len(results) == 1
    assert isinstance(results[0], dict)  # final item, not another request
    assert len(results[0]["reviews"]) == 2


def test_comments_pagination_stops_at_per_post_credit_budget():
    bounded = spider(collector_config={"max_credits_per_post": 1})
    results = list(bounded.parse_comments_page(
        json_response("https://api.scrapecreators.com/v1/facebook/post/comments", COMMENTS_PAGE_1),
        TARGET_FB, "facebook", POST_RESPONSE, TARGET_FB["product_url"], [], 1, 0,
    ))
    # COMMENTS_PAGE_1 itself charges 1 credit (credits_charged: 1), which
    # already meets max_credits_per_post=1 - must stop here even though
    # has_next_page is True and page < max_comment_pages.
    assert len(results) == 1
    assert isinstance(results[0], dict)
    assert len(results[0]["reviews"]) == 2


def test_run_wide_credit_budget_stops_further_targets():
    two_targets = [TARGET_FB, {**TARGET_FB, "mapping_id": "mapping-2", "product_url": "https://www.facebook.com/other/posts/2"}]
    tight = spider(two_targets, collector_config={"max_credits_per_run": 1})
    # Simulate the first target having already spent the entire run budget.
    tight.credits_spent = 1
    requests = list(tight._initial_requests())
    assert requests == []


def test_parse_post_degrades_to_posts_only_when_run_budget_already_spent():
    tight = spider(collector_config={"max_credits_per_run": 1})
    tight.credits_spent = 1
    results = list(tight.parse_post(
        json_response("https://api.scrapecreators.com/v1/facebook/post/", POST_RESPONSE),
        TARGET_FB, "facebook", TARGET_FB["product_url"],
    ))
    assert len(results) == 1
    assert results[0]["reviews"] == []


def test_missing_credits_charged_field_defaults_to_one():
    spider_instance = spider()
    spider_instance._record_credits({"success": True})
    assert spider_instance.credits_spent == 1


def test_real_facebook_payload_maps_reaction_count_and_reply_count_correctly():
    """The exact payload structure pulled from ScrapeCreators' own docs."""
    item = list(spider().parse_comments_page(
        json_response("https://api.scrapecreators.com/v1/facebook/post/comments", COMMENTS_PAGE_2),
        TARGET_FB, "facebook", POST_RESPONSE, TARGET_FB["product_url"], [], 1, 0,
    ))
    # COMMENTS_PAGE_2 has no comments and has_next_page=False -> final item directly.
    assert item[0]["reviews"] == []

    real_item = list(spider().parse_comments_page(
        json_response("https://api.scrapecreators.com/v1/facebook/post/comments", {**COMMENTS_PAGE_1, "has_next_page": False}),
        TARGET_FB, "facebook", POST_RESPONSE, TARGET_FB["product_url"], [], 1, 0,
    ))[0]
    first = real_item["reviews"][0]
    assert first["review_text"].startswith("Do 1/2 mini Oreos")
    assert first["reviewer_name"] == "Robin Bergsagel"
    assert first["like_count"] == 95  # reaction_count, the confirmed real field name
    assert first["reply_count"] == 1
    assert first["review_date"] == "2025-09-01T01:10:40.000Z"
    assert first["reactions"]["anger"] == 0
    assert first["reactions"]["haha"] == 1


def test_field_overrides_apply_a_different_platform_field_name():
    custom = spider(collector_config={"field_overrides": {"facebook": {"comment_like_count": ["custom_likes"]}}})
    comment = {"id": "c1", "text": "hi", "custom_likes": 7}
    reviews = custom._build_reviews([comment], "facebook")
    assert reviews[0]["like_count"] == 7
