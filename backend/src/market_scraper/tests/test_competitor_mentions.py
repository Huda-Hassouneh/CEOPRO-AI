"""Offline tests for competitor_mentions.py (feeds, news search, YouTube comments, deeper Google reviews)
and the enrichment glue that stores them. Network and database are mocked."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.market_scraper import competitor_enrichment as ce
from src.market_scraper import competitor_mentions as cm
from src.market_scraper import web_search

NOW = datetime.now(timezone.utc)
RECENT = (NOW - timedelta(days=3)).strftime("%a, %d %b %Y %H:%M:%S +0000")
OLD = (NOW - timedelta(days=900)).strftime("%a, %d %b %Y %H:%M:%S +0000")


@pytest.fixture(autouse=True)
def _no_real_redis_for_the_youtube_cap(monkeypatch):
    from src.market_scraper import youtube_quota
    monkeypatch.setattr(youtube_quota, "take_search", lambda limit=None: True)


def _rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate><description>{s}</description></item>" for t, l, d, s in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title>{body}</channel></rss>'


# ---- own website feed ---------------------------------------------------------------------

def test_feeds_are_discovered_from_the_homepage_then_from_conventional_paths():
    html = '<head><link rel="alternate" type="application/rss+xml" href="/blog/rss.xml"></head>'
    urls = cm.discover_feed_urls(html, "https://rival.example/")
    assert urls[0] == "https://rival.example/blog/rss.xml" and "https://rival.example/feed" in urls
    assert len(urls) == len(set(urls))


def test_rss_and_atom_entries_are_parsed_with_dates_and_plain_text_summaries():
    items = cm.parse_feed(_rss(("New menu", "/news/1", RECENT, "<p>Try our <b>new</b> burger &amp; fries</p>")), "https://rival.example/feed")
    assert items[0]["url"] == "https://rival.example/news/1" and items[0]["summary"] == "Try our new burger & fries"
    assert items[0]["published_at"].startswith(str(NOW.year))
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Opening</title><link rel="alternate" href="https://rival.example/a"/>'
            '<published>2026-10-01T10:00:00Z</published><summary>Soon</summary></entry></feed>')
    parsed = cm.parse_feed(atom, "https://rival.example/")
    assert parsed[0]["title"] == "Opening" and parsed[0]["url"] == "https://rival.example/a" and parsed[0]["summary"] == "Soon"


def test_a_feed_with_a_doctype_or_entities_or_bad_xml_is_refused_not_expanded():
    bomb = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title><link>https://x.example/1</link></item></channel></rss>'
    assert cm.parse_feed(bomb, "https://x.example") == []
    assert cm.parse_feed("<rss><channel><item>", "https://x.example") == []
    assert cm.parse_feed("", "https://x.example") == []
    assert cm.parse_feed(_rss(("Odd", "javascript:alert(1)", RECENT, "")), "https://x.example") == []


def _fetcher(pages):
    def fetch(url, kinds=("html",)):
        return pages.get(url)
    return fetch


def test_own_site_news_keeps_recent_items_on_the_competitors_own_site_newest_first():
    pages = {
        "https://rival.example": "<html><head></head></html>",
        "https://rival.example/feed": _rss(
            ("Older", "https://rival.example/a", (NOW - timedelta(days=30)).strftime("%a, %d %b %Y %H:%M:%S +0000"), ""),
            ("Newest", "https://rival.example/b", RECENT, "Hello"),
            ("Ancient", "https://rival.example/c", OLD, ""),
            ("Elsewhere", "https://other.example/d", RECENT, ""),
        ),
    }
    items, reason = cm.read_own_site_news("https://rival.example", _fetcher(pages))
    assert reason is None and [i["title"] for i in items] == ["Newest", "Older"]
    assert items[0]["source_domain"] == "rival.example" and "_published" not in items[0]


def test_own_site_news_says_why_there_is_none():
    assert cm.read_own_site_news("https://rival.example", _fetcher({})) == ([], "SITE_UNREACHABLE")
    assert cm.read_own_site_news("https://rival.example", _fetcher({"https://rival.example": "<html></html>"})) == ([], "NO_FEED")


# ---- news search -----------------------------------------------------------------------------

def _search(results):
    return lambda query, max_results, country: ("brave", results)


def test_news_search_keeps_only_results_that_really_name_the_competitor_and_are_recent():
    results = [
        web_search.Result("https://news.example/a", "Rival Burger opens third branch", "", RECENT),
        web_search.Result("https://news.example/b", "Burger prices rise", "Many places, incl. Rival Burger, raised prices", None),
        web_search.Result("https://news.example/c", "Another restaurant opens", "nothing relevant", RECENT),
        web_search.Result("https://news.example/d", "Rival Burger old story", "", OLD),
        web_search.Result("ftp://news.example/e", "Rival Burger", "", RECENT),
    ]
    items = cm.web_news("Rival Burger", "JO", _search(results))
    assert [i["url"] for i in items] == ["https://news.example/a", "https://news.example/b"]
    assert items[1]["published_at"] is None and items[0]["source_domain"] == "news.example"


def test_news_search_reports_a_missing_setup_by_raising():
    def none_configured(query, max_results, country):
        raise web_search.SearchFailed("not_configured")
    with pytest.raises(web_search.SearchFailed):
        cm.web_news("Rival", None, none_configured)


def test_the_news_modes_of_each_provider_are_requested_and_read(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "brave")
    seen = {}

    def fetch(method, url, *, params=None, json=None, headers=None):
        seen.update(url=url, params=params)
        return {"results": [{"url": "https://n.example/1", "title": "Rival", "description": "d", "page_age": "2026-10-10T00:00:00"}]}
    provider, results = web_search.search_news("Rival", 5, "jo", fetch=fetch)
    assert provider == "brave" and seen["url"] == web_search.BRAVE_NEWS_URL
    assert results[0].published == "2026-10-10T00:00:00" and results[0].snippet == "d"
    monkeypatch.setenv("WEB_SEARCH_PROVIDERS", "google_cse")
    monkeypatch.setenv("GOOGLE_CUSTOM_SEARCH_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_CUSTOM_SEARCH_CX", "cx")
    with pytest.raises(web_search.SearchFailed):  # a Google CSE key has no news mode
        web_search.search_news("Rival", 5, None, fetch=fetch)


# ---- YouTube ---------------------------------------------------------------------------------------

def _yt(search_items, threads_by_video):
    calls = []

    def get(url, params, secret=None):
        calls.append(url)
        if url == cm.YOUTUBE_SEARCH_URL:
            return 200, {"items": search_items}
        video = params["videoId"]
        value = threads_by_video[video]
        return value if isinstance(value, tuple) else (200, value)
    get.calls = calls
    return get


def _video(video_id, title, channel="Some Channel"):
    return {"id": {"videoId": video_id}, "snippet": {"title": title, "channelTitle": channel}}


def _thread(comment_id, text, likes, replies=()):
    return {
        "snippet": {"totalReplyCount": len(replies), "topLevelComment": {"id": comment_id, "snippet": {
            "textOriginal": text, "authorDisplayName": "Sam", "likeCount": likes, "publishedAt": "2026-10-01T10:00:00Z"}}},
        "replies": {"comments": [{"id": rid, "snippet": {"textOriginal": rt, "authorDisplayName": "Lee", "likeCount": 0, "publishedAt": "2026-10-02T10:00:00Z"}} for rid, rt in replies]},
    }


def test_youtube_comments_come_only_from_videos_naming_the_competitor_with_likes_and_replies():
    get = _yt(
        [_video("v1", "Rival Burger review"), _video("v2", "Best pasta in town"), _video("v3", "Visit", channel="Rival Burger Official")],
        {"v1": {"items": [_thread("c1", "Terrible service and very long waits", 400, replies=[("r1", "Same here, we waited too")])]}, "v3": {"items": []}},
    )
    comments = cm.youtube_comments("Rival Burger", "Amman", "KEY", get=get)
    assert [(c["external_id"], c["parent_external_id"], c["likes"]) for c in comments] == [("c1", None, 400), ("r1", "c1", 0)]
    assert comments[0]["url"].startswith("https://www.youtube.com/watch?v=v1")
    assert get.calls.count(cm.YOUTUBE_COMMENTS_URL) == 2  # v2 does not name the competitor: never read


def test_youtube_skips_a_video_with_comments_off_and_classifies_key_and_quota_errors_without_leaking_the_key():
    off = (403, {"error": {"errors": [{"reason": "commentsDisabled"}], "message": "disabled"}})
    get = _yt([_video("v1", "Rival Burger"), _video("v2", "Rival Burger 2")], {"v1": off, "v2": {"items": [_thread("c9", "Nice food and friendly staff there", 1)]}})
    assert [c["external_id"] for c in cm.youtube_comments("Rival Burger", None, "KEY", get=get)] == ["c9"]

    def failing(status, reason, message="boom KEY"):
        return lambda url, params, secret=None: (status, {"error": {"errors": [{"reason": reason}], "message": message}})
    with pytest.raises(cm.SourceError) as quota:
        cm.youtube_comments("Rival Burger", None, "KEY", get=failing(403, "quotaExceeded"))
    assert quota.value.code == cm.QUOTA_EXHAUSTED
    with pytest.raises(cm.SourceError) as bad:
        cm.youtube_comments("Rival Burger", None, "KEY", get=failing(400, "keyInvalid"))
    assert bad.value.code == cm.CREDENTIALS_REJECTED and "KEY" not in bad.value.detail
    with pytest.raises(cm.SourceError) as other:
        cm.youtube_comments("Rival Burger", None, "KEY", get=failing(500, "backendError"))
    assert other.value.code == cm.PROVIDER_ERROR


# ---- deeper Google reviews --------------------------------------------------------------------------------

def test_apify_reviews_handle_both_output_shapes_and_keep_likes_and_the_owner_reply():
    nested = [{"title": "Rival", "reviews": [
        {"reviewId": "a1", "name": "Sam", "text": "Cold food", "stars": 1, "likesCount": 12, "publishedAtDate": "2026-09-01T10:00:00Z",
         "responseFromOwnerText": "Sorry!", "responseFromOwnerDate": "2026-09-02T10:00:00Z"},
        {"reviewId": "a2", "name": "Lee", "text": "", "stars": 5},
    ]}]
    flat = [{"reviewId": "b1", "reviewerName": "Omar", "text": "Great", "stars": 5, "likesCount": 0}]
    review = cm.apify_google_reviews("PID", "TOKEN", post=lambda url, params, body: nested)[0]
    assert (review["external_id"], review["likes"], review["rating"], review["owner_reply"]) == ("a1", 12, 1.0, "Sorry!")
    assert len(cm.apify_google_reviews("PID", "TOKEN", post=lambda *a: nested)) == 1  # the empty-text review is dropped
    assert cm.apify_google_reviews("PID", "TOKEN", post=lambda *a: flat)[0]["author"] == "Omar"
    assert cm.apify_google_reviews("PID", "TOKEN", post=lambda *a: {"unexpected": True}) == []


# ---- enrichment glue ---------------------------------------------------------------------------------------

def _competitor(**o):
    base = {"name": "Rival Burger", "website_url": "https://rival.example", "city": "Amman", "visibility": "PRIVATE", "owner_tenant_id": "t1"}
    base.update(o)
    return base


def _news(own=((), None), web=("ok", [])):
    stack = [patch.object(ce.direct_search, "_robots_allowed_cached", return_value=True),
             patch.object(ce.mentions, "read_own_site_news", return_value=own)]
    if web[0] == "ok":
        stack.append(patch.object(ce.mentions, "web_news", return_value=web[1]))
    else:
        stack.append(patch.object(ce.mentions, "web_news", side_effect=web_search.SearchFailed(web[0])))
    return stack


def _run_news(competitor, own, web):
    conn = MagicMock()
    patches = _news(own, web)
    for p in patches:
        p.start()
    try:
        with patch.object(ce, "_save_news") as save:
            return ce._news_outcome(conn, "t1", "c1", competitor), save
    finally:
        for p in patches:
            p.stop()


ITEM = {"url": "https://rival.example/a", "title": "T"}


def test_news_outcome_combines_own_site_and_search_and_records_the_confidence():
    (status, code, _d, items, confidence), save = _run_news(_competitor(), ([ITEM], None), ("ok", [ITEM, ITEM]))
    assert (status, code, items, confidence) == (ce.STATUS_SUCCEEDED, None, 3, 1.0)
    assert [c.args[4] for c in save.call_args_list] == ["own_site", "web_search"]
    (status, _c, _d, items, confidence), _ = _run_news(_competitor(), ((), "NO_FEED"), ("ok", [ITEM]))
    assert (status, items, confidence) == (ce.STATUS_SUCCEEDED, 1, 0.6)


def test_news_outcome_explains_every_way_of_finding_nothing():
    assert _run_news(_competitor(), ((), "NO_FEED"), ("ok", []))[0][:2] == (ce.STATUS_FAILED, ce.NO_NEWS)
    assert _run_news(_competitor(), ((), "NO_FEED"), ("unreachable", None))[0][:2] == (ce.STATUS_FAILED, ce.PROVIDER_ERROR)
    assert _run_news(_competitor(), ((), "NO_FEED"), ("not_configured", None))[0][:2] == (ce.STATUS_FAILED, ce.NO_FEED)
    assert _run_news(_competitor(), ((), "SITE_UNREACHABLE"), ("not_configured", None))[0][:2] == (ce.STATUS_FAILED, ce.SITE_UNREACHABLE)
    assert _run_news(_competitor(), ((), "NO_FEED"), ("not_configured", None))[0][0] == ce.STATUS_FAILED
    no_site = _run_news(_competitor(website_url=None), ((), None), ("not_configured", None))[0]
    assert no_site[:2] == (ce.STATUS_BLOCKED, ce.NO_CREDENTIALS) and "BRAVE_SEARCH_API_KEY" in no_site[2]


def test_a_site_that_disallows_robots_is_not_read_for_its_feed():
    with patch.object(ce.direct_search, "_robots_allowed_cached", return_value=False), \
         patch.object(ce.mentions, "read_own_site_news") as read, \
         patch.object(ce.mentions, "web_news", side_effect=web_search.SearchFailed("not_configured")):
        outcome = ce._news_outcome(MagicMock(), "t1", "c1", _competitor())
    read.assert_not_called()
    assert outcome[:2] == (ce.STATUS_BLOCKED, ce.ROBOTS_DISALLOWED)


def test_comments_are_blocked_until_a_key_the_operators_approval_and_an_actor_exist(monkeypatch):
    for name in ("YOUTUBE_API_KEY", "EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "SCRAPER_ACTOR_USER_ID", "AI_SERVICE_ACTOR_USER_ID"):
        monkeypatch.delenv(name, raising=False)
    assert ce._comments_outcome(MagicMock(), "t1", "c1", _competitor(), "u")[:2] == (ce.STATUS_BLOCKED, ce.NO_CREDENTIALS)
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    assert ce._comments_outcome(MagicMock(), "t1", "c1", _competitor(), "u")[:2] == (ce.STATUS_BLOCKED, ce.PLATFORM_APPROVAL_MISSING)
    monkeypatch.setenv("EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "ops-1")
    assert ce._comments_outcome(MagicMock(), "t1", "c1", _competitor(), None)[:2] == (ce.STATUS_FAILED, ce.SERVICE_MISCONFIGURED)


def test_comments_are_stored_with_thirty_day_retention_and_sentiment_is_requested(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setenv("EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "ops-1")
    comments = [{"external_id": "c1", "parent_external_id": None, "author": "Sam", "text": "x", "likes": 3, "published_at": None, "reply_count": 0}]
    with patch.object(ce.mentions, "youtube_comments", return_value=comments), \
         patch.object(ce, "_review_source", return_value="src") as source, \
         patch.object(ce, "_save_comments", return_value=1) as save, \
         patch.object(ce, "_request_sentiment_analysis") as analysis:
        outcome = ce._comments_outcome(MagicMock(), "t1", "c1", _competitor(), "actor")
    assert outcome[:4] == (ce.STATUS_SUCCEEDED, None, None, 1)
    assert source.call_args.kwargs["retention_days"] == 30 and source.call_args.kwargs["collector_key"] == "youtube_comments"
    assert save.call_args.args[4] == "YouTube"
    analysis.assert_called_once_with("t1")


def test_no_matching_video_and_provider_errors_are_distinct_outcomes(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setenv("EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "ops-1")
    with patch.object(ce.mentions, "youtube_comments", return_value=[]):
        assert ce._comments_outcome(MagicMock(), "t1", "c1", _competitor(), "a")[:2] == (ce.STATUS_FAILED, ce.NO_VIDEOS)
    with patch.object(ce.mentions, "youtube_comments", side_effect=cm.SourceError(cm.QUOTA_EXHAUSTED, "over")):
        assert ce._comments_outcome(MagicMock(), "t1", "c1", _competitor(), "a")[:3] == (ce.STATUS_FAILED, ce.QUOTA_EXHAUSTED, "over")


def test_replies_are_only_stored_under_a_comment_that_was_stored():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [("rid1", True), ("rid2", True)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    comments = [
        {"external_id": "r1", "parent_external_id": "c1", "author": "L", "text": "reply", "likes": 0, "published_at": None, "reply_count": None},
        {"external_id": "c1", "parent_external_id": None, "author": "S", "text": "top", "likes": 5, "published_at": None, "reply_count": 1},
        {"external_id": "r2", "parent_external_id": "missing", "author": "L", "text": "orphan", "likes": 0, "published_at": None, "reply_count": None},
    ]
    new = ce._save_comments(conn, "t1", "comp", "src", "YouTube", comments)
    assert new == 2 and cursor.execute.call_count == 2  # top first, its reply second, the orphan skipped
    assert cursor.execute.call_args_list[1].args[1][-2] == "rid1"  # the reply's parent_review_id (the source url follows it)


# ---- which comments are worth keeping (P2) ---------------------------------------------------

@pytest.mark.parametrize("text,keep", [
    ("first!", False), ("🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥", False), ("nice nice", False), ("+1 +1 +1 +1 +1 +1", False),
    ("The waiter was rude and the food came cold", True),
    ("الخدمة بطيئة جدا والأسعار مرتفعة", True),  # Arabic counts letters and words the same way
])
def test_only_substantive_comments_are_kept(text, keep):
    assert cm.is_substantive(text) is keep


def test_an_unnamed_comment_on_someone_elses_channel_must_be_a_real_opinion():
    short = "great video, loved the music"  # 28 chars, does not name the business
    long = "Went there last week and the burgers were dry, the service was slow and they overcharged us"
    assert cm.keep_comment(short, "Rival Burger", channel_names_it=False) is False
    assert cm.keep_comment(long, "Rival Burger", channel_names_it=False) is True
    assert cm.keep_comment(short, "Rival Burger", channel_names_it=True) is True   # their own channel
    assert cm.keep_comment("Rival Burger was fine honestly", "Rival Burger", channel_names_it=False) is True  # names them


def test_youtube_comments_drop_noise_and_duplicates():
    def get(url, params, secret=None):
        if "search" in url:
            return 200, {"items": [{"id": {"videoId": "v1"}, "snippet": {"title": "Rival Burger review", "channelTitle": "Foodie"}}]}
        opinion = "Rival Burger was cold and the staff ignored us for twenty minutes"
        return 200, {"items": [
            {"snippet": {"topLevelComment": {"id": "a", "snippet": {"textOriginal": opinion, "likeCount": 4}}, "totalReplyCount": 0}},
            {"snippet": {"topLevelComment": {"id": "b", "snippet": {"textOriginal": opinion.upper(), "likeCount": 1}}, "totalReplyCount": 0}},  # duplicate
            {"snippet": {"topLevelComment": {"id": "c", "snippet": {"textOriginal": "first!", "likeCount": 99}}, "totalReplyCount": 0}},
        ]}
    assert [c["external_id"] for c in cm.youtube_comments("Rival Burger", None, "KEY", get=get)] == ["a"]


def test_a_bad_request_that_is_not_about_the_key_is_not_reported_as_a_rejected_key():
    get = lambda url, params, secret=None: (400, {"error": {"errors": [{"reason": "invalidVideoId"}], "message": "bad id"}})
    with pytest.raises(cm.SourceError) as err:
        cm.youtube_comments("Rival Burger", None, "KEY", get=get)
    assert err.value.code == cm.PROVIDER_ERROR


def test_quota_running_out_midway_keeps_the_comments_already_collected():
    quota = (403, {"error": {"errors": [{"reason": "quotaExceeded"}], "message": "q"}})
    get = _yt([_video("v1", "Rival Burger"), _video("v2", "Rival Burger 2")],
              {"v1": {"items": [_thread("c1", "Terrible service and very long waits", 3)]}, "v2": quota})
    assert [c["external_id"] for c in cm.youtube_comments("Rival Burger", None, "KEY", get=get)] == ["c1"]


def test_httpx_request_urls_carrying_api_keys_are_not_logged_at_info():
    import logging
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_videos_naming_the_place_are_read_first_and_the_region_is_sent():
    seen = {}
    base = _yt([_video("far", "Rival Burger review"), _video("near", "Rival Burger Amman tour")],
               {"far": {"items": [_thread("c1", "Terrible service and very long waits", 1)]},
                "near": {"items": [_thread("c2", "Lovely staff and quick service here", 1)]}})

    def get(url, params, secret=None):
        if url == cm.YOUTUBE_SEARCH_URL:
            seen.update(params)
        return base(url, params, secret)
    out = cm.youtube_comments("Rival Burger", "Amman", "KEY", get=get, max_videos=1, country_code="jo")
    assert [c["external_id"] for c in out] == ["c2"] and seen["regionCode"] == "JO"
    seen.clear()
    cm.youtube_comments("Rival Burger", None, "KEY", get=get, country_code="Jordan")
    assert "regionCode" not in seen


def test_generic_words_in_a_competitor_name_are_not_required_to_match():
    assert cm._names_match("Starbucks Coffee Company", "Starbucks in Amman")
    assert not cm._names_match("Rival Burger", "Rival Pizza")
    assert cm._names_match("Coffee", "best coffee in town")  # a name made only of generic words still has to appear
