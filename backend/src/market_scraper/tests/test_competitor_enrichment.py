"""Offline tests for competitor_enrichment.py: Places error classification
(the setup failures the old helpers swallowed), place matching on evidence,
social-link extraction rules, additive retry, throttling, and the
data-completeness reasons. DB access and network are mocked; the DB side is
covered by test_competitor_enrichment_integration_db.py."""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.market_scraper import competitor_enrichment as ce

TENANT = "11111111-1111-1111-1111-111111111111"
COMP = "22222222-2222-2222-2222-222222222222"


def _competitor(**overrides):
    base = {
        "name": "Burger Hub", "website_url": "https://burgerhub.example", "identity_key": "burgerhub.example",
        "address": None, "city": None, "phone": None, "rating": None, "rating_count": None, "place_types": None,
        "place_id": None, "latitude": None, "longitude": None, "social_profiles": None,
        "visibility": "PRIVATE", "owner_tenant_id": TENANT,
    }
    base.update(overrides)
    return base


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---- Places error classification -------------------------------------------------

@pytest.mark.parametrize("status,code", [
    ("REQUEST_DENIED", ce.CREDENTIALS_REJECTED),
    ("OVER_QUERY_LIMIT", ce.QUOTA_EXHAUSTED),
    ("INVALID_REQUEST", ce.PROVIDER_ERROR),
])
def test_places_status_is_classified_not_swallowed(status, code):
    with patch("urllib.request.urlopen", return_value=_Resp({"status": status, "error_message": "bad key SECRET123"})):
        with pytest.raises(ce._PlacesError) as exc:
            ce._places_get(ce._DETAILS_URL, {"place_id": "p"}, "SECRET123")
    assert exc.value.code == code
    assert "SECRET123" not in exc.value.detail  # the key never reaches the ledger


def test_network_failure_is_a_provider_error_without_the_key():
    with patch("urllib.request.urlopen", side_effect=OSError("boom key=SECRET123")):
        with pytest.raises(ce._PlacesError) as exc:
            ce._places_get(ce._DETAILS_URL, {}, "SECRET123")
    assert exc.value.code == ce.PROVIDER_ERROR
    assert "SECRET123" not in exc.value.detail


def test_zero_results_is_a_normal_answer():
    with patch("urllib.request.urlopen", return_value=_Resp({"status": "ZERO_RESULTS", "candidates": []})):
        assert ce._places_get(ce._FIND_PLACE_URL, {}, "k")["candidates"] == []


# ---- place matching -----------------------------------------------------------------

def test_find_place_accepts_a_matching_website_host_over_a_similar_name():
    competitor = _competitor(name="burgerhub.example")  # product-search rows are named by hostname
    responses = [
        {"candidates": [{"place_id": "p1", "name": "Totally Different"}]},
        {"result": {"name": "Totally Different", "website": "https://www.burgerhub.example/menu"}},
    ]
    with patch.object(ce, "_places_get", side_effect=responses):
        details, confidence = ce._find_place(competitor, "k")
    assert details["place_id"] == "p1" and confidence == 0.95


def test_find_place_rejects_a_dissimilar_candidate():
    responses = [
        {"candidates": [{"place_id": "p1", "name": "Joe's Pizza"}]},
        {"result": {"name": "Joe's Pizza", "website": "https://joes.example"}},
    ]
    with patch.object(ce, "_places_get", side_effect=responses):
        assert ce._find_place(_competitor(), "k") == (None, None)


# ---- profile outcomes -----------------------------------------------------------------

def test_profile_without_a_key_is_blocked_with_a_clear_reason():
    conn = MagicMock()
    with patch.object(ce, "_write_ledger") as ledger:
        result = ce.enrich_profile(conn, TENANT, COMP, _competitor(), api_key=None)
    assert result["status"] == ce.STATUS_BLOCKED and result["reason_code"] == ce.NO_CREDENTIALS
    assert ledger.call_args.args[4:6] == (ce.STATUS_BLOCKED, ce.NO_CREDENTIALS)


def test_profile_with_a_rejected_key_reports_credentials_rejected():
    with patch.object(ce, "_places_get", side_effect=ce._PlacesError(ce.CREDENTIALS_REJECTED, "denied")), \
         patch.object(ce, "_write_ledger") as ledger:
        result = ce.enrich_profile(MagicMock(), TENANT, COMP, _competitor(), api_key="k")
    assert result["status"] == ce.STATUS_FAILED and result["reason_code"] == ce.CREDENTIALS_REJECTED
    ledger.assert_called_once()


def test_profile_for_a_shared_record_is_not_applicable_and_never_written():
    conn = MagicMock()
    with patch.object(ce, "_write_ledger"):
        result = ce.enrich_profile(conn, TENANT, COMP, _competitor(visibility="GLOBAL", owner_tenant_id=None), api_key="k")
    assert result["status"] == ce.STATUS_NOT_APPLICABLE
    conn.cursor.assert_not_called()


# ---- social links ----------------------------------------------------------------------

def test_social_links_without_a_website_are_not_applicable():
    status, code, *_ = ce._social_outcome(MagicMock(), TENANT, COMP, _competitor(website_url=None))
    assert (status, code) == (ce.STATUS_NOT_APPLICABLE, ce.NO_WEBSITE)


def test_social_links_respect_robots_txt():
    with patch.object(ce.direct_search, "_robots_allowed_cached", return_value=False), \
         patch.object(ce.direct_search, "_fetch") as fetch:
        status, code, *_ = ce._social_outcome(MagicMock(), TENANT, COMP, _competitor())
    assert (status, code) == (ce.STATUS_BLOCKED, ce.ROBOTS_DISALLOWED)
    fetch.assert_not_called()


def test_unreachable_site_is_retryable_failure():
    with patch.object(ce.direct_search, "_robots_allowed_cached", return_value=True), \
         patch.object(ce.direct_search, "_fetch", return_value=None):
        status, code, *_ = ce._social_outcome(MagicMock(), TENANT, COMP, _competitor())
    assert (status, code) == (ce.STATUS_FAILED, ce.SITE_UNREACHABLE)


def test_share_links_are_ignored_and_existing_links_are_kept_on_retry():
    html = '<script type="application/ld+json">{"sameAs": ["https://instagram.com/burgerhub"]}</script>' \
           '<a href="https://www.facebook.com/sharer/sharer.php?u=x">share</a>'
    conn = MagicMock()
    existing = {"tiktok": "https://tiktok.com/@old", "instagram": "https://instagram.com/older"}
    with patch.object(ce.direct_search, "_robots_allowed_cached", return_value=True), \
         patch.object(ce.direct_search, "_fetch", return_value=html):
        status, code, _detail, items, confidence = ce._social_outcome(conn, TENANT, COMP, _competitor(social_profiles=existing))
    assert status == ce.STATUS_SUCCEEDED and confidence == 0.95
    saved = json.loads(conn.cursor.return_value.__enter__.return_value.execute.call_args.args[1][0])
    assert saved["instagram"] == "https://instagram.com/older"  # a retry never overwrites
    assert "facebook" not in saved and saved["tiktok"] == "https://tiktok.com/@old"
    assert items == 2


def test_a_social_profile_competitor_is_its_own_link():
    competitor = _competitor(website_url="https://instagram.com/burgerhub", identity_key="instagram.com/burgerhub")
    conn = MagicMock()
    status, *_rest, confidence = ce._social_outcome(conn, TENANT, COMP, competitor)
    assert status == ce.STATUS_SUCCEEDED and confidence == 1.0


# ---- orchestration ------------------------------------------------------------------------

def test_unsupported_facets_are_rejected_up_front():
    with pytest.raises(ValueError):
        ce.enrich_competitor(MagicMock(), TENANT, COMP, facets=["BOGUS"])


def test_unknown_competitor_raises():
    with patch.object(ce, "_load_competitor", return_value=None):
        with pytest.raises(ValueError):
            ce.enrich_competitor(MagicMock(), TENANT, COMP)


def test_a_manual_retry_inside_the_throttle_window_is_not_run():
    with patch.object(ce, "_load_competitor", return_value=_competitor()), \
         patch.object(ce, "_recent_attempt_wait", return_value=12), \
         patch.object(ce, "enrich_profile") as profile:
        results = ce.enrich_competitor(MagicMock(), TENANT, COMP, facets=[ce.FACET_PROFILE], throttle=True)
    assert results == {ce.FACET_PROFILE: {"status": "THROTTLED", "retry_after_seconds": 12}}
    profile.assert_not_called()


def test_one_facet_crashing_is_recorded_and_the_other_still_runs():
    with patch.object(ce, "_load_competitor", return_value=_competitor()), \
         patch.object(ce, "enrich_profile", side_effect=RuntimeError("boom")), \
         patch.object(ce, "enrich_social_links", return_value={"status": ce.STATUS_SUCCEEDED}) as social, \
         patch.object(ce, "enrich_reviews", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_news", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_comments", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_prices", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_social_content", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "_write_ledger") as ledger:
        results = ce.enrich_competitor(MagicMock(), TENANT, COMP, places_api_key="k")
    assert results[ce.FACET_PROFILE]["reason_code"] == ce.PROVIDER_ERROR
    assert results[ce.FACET_SOCIAL_LINKS]["status"] == ce.STATUS_SUCCEEDED
    social.assert_called_once()
    assert ledger.call_args.args[3] == ce.FACET_PROFILE


def test_a_changed_profile_triggers_a_rescore():
    with patch.object(ce, "_load_competitor", return_value=_competitor()), \
         patch.object(ce, "enrich_profile", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch("src.ai.pricing.competitor_classification.classify_competitor") as classify:
        ce.enrich_competitor(MagicMock(), TENANT, COMP, facets=[ce.FACET_PROFILE], places_api_key="k")
    classify.assert_called_once()


def test_completeness_score_weights_partial_half():
    facets = {
        ce.FACET_PROFILE: {"status": ce.STATUS_SUCCEEDED}, ce.FACET_SOCIAL_LINKS: {"status": ce.STATUS_PARTIAL},
        ce.FACET_PRICES: {"status": ce.STATUS_FAILED}, ce.FACET_REVIEWS: {"status": ce.STATUS_PENDING},
        ce.FACET_SOCIAL_CONTENT: {"status": ce.STATUS_BLOCKED}, ce.FACET_NEWS: {"status": ce.STATUS_SUCCEEDED},
        ce.FACET_COMMENTS: {"status": ce.STATUS_FAILED},
    }
    assert ce._completeness_score(facets) == 36  # (1 + 0.5 + 1) / 7 facets


def test_the_routine_facets_leave_out_the_youtube_search_that_costs_quota():
    assert ce.FACET_COMMENTS in ce.ENRICHABLE_FACETS and ce.FACET_COMMENTS not in ce.ROUTINE_FACETS
    assert {ce.FACET_PROFILE, ce.FACET_SOCIAL_LINKS, ce.FACET_REVIEWS, ce.FACET_NEWS} == set(ce.ROUTINE_FACETS)


# ---- PRICES: website + menu files -----------------------------------------------------------

def _prices_conn(priced, average=0.6, from_menus=0):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (priced, average, from_menus)
    return conn


def _prices(conn, outcome, website="https://cafe.jo", deep=False):
    competitor = {**_competitor(), "website_url": website}
    with patch("src.ai.market_inputs.competitor_intel.refresh_competitor", return_value=outcome) as refresh, \
         patch.object(ce, "_write_ledger") as ledger:
        result = ce.enrich_prices(conn, TENANT, COMP, competitor, deep)
    return result, ledger, refresh


def test_prices_without_a_website_is_not_applicable_and_reads_nothing():
    result, _ledger, refresh = _prices(MagicMock(), {}, website=None)
    assert (result["status"], result["reason_code"]) == (ce.STATUS_NOT_APPLICABLE, ce.NO_WEBSITE)
    refresh.assert_not_called()


def test_prices_found_are_a_success_and_menu_origin_is_disclosed():
    result, ledger, _ = _prices(_prices_conn(9, 0.55, from_menus=4), {"status": "prices_found", "media": {"found": 2, "read": 2}})
    assert result["status"] == ce.STATUS_SUCCEEDED and result["items_found"] == 9
    assert "4 of them were read from menu files" in result["reason_detail"]
    assert ledger.call_args.args[3] == ce.FACET_PRICES


def test_menu_pictures_without_an_ocr_engine_say_so_instead_of_no_prices():
    result, _l, _r = _prices(_prices_conn(0, None), {"status": "no_price_published", "media": {"found": 3, "read": 0, "skipped_no_ocr": 3}})
    assert (result["status"], result["reason_code"]) == (ce.STATUS_FAILED, ce.OCR_NOT_AVAILABLE)
    assert "3 picture(s)" in result["reason_detail"]


def test_some_prices_with_some_unreadable_pictures_is_partial_not_success():
    result, _l, _r = _prices(_prices_conn(5), {"status": "prices_found", "media": {"found": 3, "read": 1, "skipped_no_ocr": 2}})
    assert result["status"] == ce.STATUS_PARTIAL and "not installed" in result["reason_detail"]


def test_site_side_outcomes_get_specific_reasons():
    for status, expected in (("blocked_by_robots", ce.ROBOTS_DISALLOWED), ("needs_javascript", ce.JS_RENDERED),
                             ("unreachable", ce.SITE_UNREACHABLE), ("no_price_published", ce.NO_PRICES_PUBLISHED),
                             ("not_own_site", ce.NOT_OWN_SITE)):
        result, _l, _r = _prices(_prices_conn(0, None), {"status": status, "media": {}})
        assert result["reason_code"] == expected, status


def test_deep_reads_are_requested_through_the_collector():
    _result, _l, refresh = _prices(_prices_conn(1), {"status": "prices_found", "media": {}}, deep=True)
    collect = refresh.call_args.kwargs["collect"]
    assert collect.keywords == {"deep": True}


def test_prices_is_retryable_but_not_part_of_the_routine_sweep():
    assert {ce.FACET_PRICES, ce.FACET_SOCIAL_CONTENT} <= set(ce.ENRICHABLE_FACETS)
    assert not {ce.FACET_PRICES, ce.FACET_SOCIAL_CONTENT} & set(ce.ROUTINE_FACETS)


def test_a_plain_retry_never_runs_the_paid_social_facet_but_an_explicit_request_does():
    with patch.object(ce, "_load_competitor", return_value=_competitor()), \
         patch.object(ce, "enrich_profile", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_social_links", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_reviews", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_news", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_comments", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_prices", return_value={"status": ce.STATUS_SUCCEEDED}), \
         patch.object(ce, "enrich_social_content", return_value={"status": ce.STATUS_SUCCEEDED}) as social, \
         patch.object(ce, "_write_ledger"):
        plain = ce.enrich_competitor(MagicMock(), TENANT, COMP, places_api_key="k")
        assert ce.FACET_SOCIAL_CONTENT not in plain and not social.called
        explicit = ce.enrich_competitor(MagicMock(), TENANT, COMP, facets=[ce.FACET_SOCIAL_CONTENT], deep=True)
    assert list(explicit) == [ce.FACET_SOCIAL_CONTENT]
    assert social.call_args.args[-1] is True  # deep reaches the collector


def test_a_refused_paid_deep_review_read_keeps_the_places_reviews_and_says_why():
    from src.ai.billing import credits
    with patch.object(ce, "_store_deep_google_reviews", side_effect=credits.BudgetError("COST_NOT_CONFIGURED", credits.DATA, detail="apify")):
        # Only the refusal handling is under test: reproduce the except branches the reviews outcome has.
        try:
            with ce._billing_scope(TENANT, "competitor_reviews"):  # noqa: SLF001
                ce._store_deep_google_reviews(MagicMock(), TENANT, COMP, "p", "s", "tok")  # noqa: SLF001
        except credits.BudgetError as exc:
            error = mentions_source_error(exc)
    assert error.code == "COST_NOT_CONFIGURED" and "bound method" not in error.detail


def mentions_source_error(exc):
    from src.market_scraper import competitor_mentions as mentions
    return mentions.SourceError(exc.reason, ce._refusal_text(exc))  # noqa: SLF001


# ---- next_step: who can resolve a gap ---------------------------------------------------------

@pytest.mark.parametrize("status,code,expected", [
    (ce.STATUS_SUCCEEDED, None, "none"),
    (ce.STATUS_NOT_APPLICABLE, ce.NO_WEBSITE, "none"),
    (ce.STATUS_BLOCKED, ce.NO_CREDENTIALS, "admin"),
    (ce.STATUS_BLOCKED, ce.PLATFORM_APPROVAL_MISSING, "admin"),
    (ce.STATUS_FAILED, ce.CREDENTIALS_REJECTED, "admin"),
    (ce.STATUS_FAILED, ce.QUOTA_EXHAUSTED, "wait"),
    (ce.STATUS_FAILED, ce.SITE_UNREACHABLE, "wait"),
    (ce.STATUS_BLOCKED, ce.TERMS_UNREVIEWED, "owner"),
    (ce.STATUS_BLOCKED, ce.ROBOTS_DISALLOWED, "none"),
    (ce.STATUS_FAILED, ce.NO_VIDEOS, "retry"),
    (ce.STATUS_PENDING, ce.NOT_ATTEMPTED, "retry"),
    (ce.STATUS_FAILED, "SOMETHING_NEW", "retry"),
])
def test_next_step_says_who_can_resolve_a_gap(status, code, expected):
    assert ce.next_step_for(status, code) == expected


def test_a_comments_facet_without_a_youtube_key_names_the_missing_setting(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    status, code, detail, items, _ = ce._comments_outcome(MagicMock(), TENANT, COMP, {"name": "X", "city": None}, None)
    assert (status, code, items) == (ce.STATUS_BLOCKED, ce.NO_CREDENTIALS, 0)
    assert "YOUTUBE_API_KEY" in detail and ce.next_step_for(status, code) == "admin"


def test_every_retry_outcome_carries_a_next_step():
    with patch.object(ce, "_load_competitor", return_value={"name": "X"}), \
         patch.object(ce, "enrich_news", return_value={"status": ce.STATUS_FAILED, "reason_code": ce.NO_NEWS, "reason_detail": "x", "items_found": 0}):
        results = ce.enrich_competitor(MagicMock(), TENANT, COMP, facets=[ce.FACET_NEWS])
    assert results[ce.FACET_NEWS]["next_step"] == "retry"


def test_only_http_links_are_stored_as_a_comments_source():
    assert ce._http_url("https://www.youtube.com/watch?v=x&lc=y") == "https://www.youtube.com/watch?v=x&lc=y"
    assert ce._http_url("javascript:alert(1)") is None and ce._http_url(None) is None and ce._http_url("") is None


def test_comments_are_not_collected_once_the_daily_youtube_allowance_is_spent(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setenv("EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "ref")
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "u")
    with patch.object(ce.youtube_quota, "take_search", return_value=False), \
         patch.object(ce.mentions, "youtube_comments") as search:
        status, code, detail, items, _ = ce._comments_outcome(MagicMock(), TENANT, COMP, {"name": "X", "city": None}, None)
    assert (status, code, items) == (ce.STATUS_FAILED, ce.QUOTA_EXHAUSTED, 0) and "daily" in detail
    search.assert_not_called()


def test_manual_comment_retries_wait_longer_than_other_facets():
    from datetime import datetime, timedelta, timezone
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (datetime.now(timezone.utc) - timedelta(seconds=60),)
    assert ce._recent_attempt_wait(conn, TENANT, COMP, ce.FACET_COMMENTS) > 200
    assert ce._recent_attempt_wait(conn, TENANT, COMP, ce.FACET_NEWS) == 0
