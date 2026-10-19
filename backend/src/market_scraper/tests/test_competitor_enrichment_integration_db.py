"""
Live-DB tests for competitor enrichment (migration 20261017000000): a
website-less Places find is registered and deduplicated by place_id, the
ledger records outcomes and increments attempts, a retry is additive, the
tenant cannot see another tenant's ledger, and data_completeness explains
price gaps from the real policy status. Skipped unless AI_TEST_DATABASE_URL
is set; Google/network calls are mocked.
"""
import os
import uuid
from unittest.mock import patch

import psycopg2
import pytest

from src.market_scraper import competitor_enrichment as ce
from src.market_scraper.discovery import CandidateSource, register_domain_level_competitor

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _register(conn, tenant_id, **overrides):
    candidate = CandidateSource(
        product_name="burger restaurant", url=overrides.pop("url", "https://burgerhub.example"),
        title=overrides.pop("title", "Burger Hub"), **overrides,
    )
    result = register_domain_level_competitor(conn, tenant_id, str(uuid.uuid4()), candidate, "PLACES_NEARBY")
    conn.commit()
    return result["competitor_id"]


def test_a_business_with_no_website_is_registered_once_by_place_id(conn):
    tenant_id = _insert_company(conn)
    first = _register(conn, tenant_id, url="", title="Corner Grill", place_id="ChIJ_abc", latitude=31.95, longitude=35.91)
    again = _register(conn, tenant_id, url="", title="Corner Grill (renamed)", place_id="ChIJ_abc")
    assert first == again
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT website_url, website_identity_key, google_place_id FROM global_competitors WHERE global_competitor_id = %s;",
            (first,),
        )
        assert cursor.fetchone() == (None, "place:ChIJ_abc", "ChIJ_abc")


def test_a_url_less_candidate_without_a_place_id_is_refused(conn):
    tenant_id = _insert_company(conn)
    with pytest.raises(ValueError):
        register_domain_level_competitor(conn, tenant_id, str(uuid.uuid4()), CandidateSource("x", "", "Nameless"), "PLACES_NEARBY")


def test_a_missing_key_is_recorded_in_the_ledger_and_attempts_accumulate(conn, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    with patch.object(ce.direct_search, "_robots_allowed_cached", return_value=False):
        ce.enrich_competitor(conn, tenant_id, competitor_id, places_api_key=None)
        ce.enrich_competitor(conn, tenant_id, competitor_id, facets=[ce.FACET_PROFILE], places_api_key=None)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT status, reason_code, attempts FROM competitor_enrichment "
            "WHERE tenant_id = %s AND global_competitor_id = %s AND facet = 'PROFILE';",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone() == ("BLOCKED", "NO_CREDENTIALS", 2)


def test_a_retry_adds_profile_data_without_overwriting_what_exists(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id, phone="+962 6 111", address="Amman")
    details = {
        "place_id": "p9", "website": "https://burgerhub.example", "formatted_address": "Other address",
        "formatted_phone_number": "+962 6 999", "rating": 4.4, "user_ratings_total": 120, "types": ["restaurant"],
    }
    with patch.object(ce, "_places_get", return_value={"result": details, "candidates": [{"place_id": "p9", "name": "Burger Hub"}]}), \
         patch.object(ce.direct_search, "_robots_allowed_cached", return_value=False):
        results = ce.enrich_competitor(conn, tenant_id, competitor_id, facets=[ce.FACET_PROFILE], places_api_key="k")
    assert results[ce.FACET_PROFILE]["status"] == ce.STATUS_SUCCEEDED
    with conn.cursor() as cursor:
        cursor.execute("SELECT address, phone, rating, rating_count, google_place_id FROM global_competitors WHERE global_competitor_id = %s;", (competitor_id,))
        address, phone, rating, rating_count, place_id = cursor.fetchone()
    assert (address, phone) == ("Amman", "+962 6 111")  # existing values kept
    assert (float(rating), rating_count, place_id) == (4.4, 120, "p9")  # gaps filled


def test_the_ledger_is_tenant_isolated_and_cascades_with_the_competitor_row(conn):
    tenant_a, tenant_b = _insert_company(conn), _insert_company(conn)
    competitor_id = _register(conn, tenant_a)
    ce._write_ledger(conn, tenant_a, competitor_id, ce.FACET_PROFILE, ce.STATUS_FAILED, ce.NO_MATCH, "x")
    assert ce.load_data_completeness(conn, tenant_b) == {}
    assert ce.load_data_completeness(conn, tenant_a, competitor_id)[competitor_id]["facets"][ce.FACET_PROFILE]["reason_code"] == ce.NO_MATCH


def test_completeness_explains_why_prices_and_reviews_are_empty(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    facets = ce.load_data_completeness(conn, tenant_id, competitor_id)[competitor_id]["facets"]
    assert facets[ce.FACET_PRICES]["reason_code"] == ce.NO_PRODUCTS_MAPPED
    assert facets[ce.FACET_REVIEWS]["reason_code"] == ce.NOT_ATTEMPTED
    assert facets[ce.FACET_SOCIAL_CONTENT]["reason_code"] == ce.NO_SOCIAL_LINKS
    assert facets[ce.FACET_PROFILE]["status"] == ce.STATUS_PENDING


def _candidates_picked(conn, tenant_id, mode):
    """Which competitors enrich_tenant_competitors(mode) would attempt (enrich_competitor stubbed)."""
    seen = []
    with patch.object(ce, "enrich_competitor", side_effect=lambda c, t, cid, **kw: seen.append(cid) or {}):
        ce.enrich_tenant_competitors(conn, tenant_id, mode=mode, limit=50)
    return seen


def test_due_mode_skips_permanent_misses_but_force_mode_retries_them_and_fixed_setup_blocks(conn):
    tenant_id = _insert_company(conn)
    permanent = _register(conn, tenant_id, url="https://permanent.example", title="Permanent")
    transient = _register(conn, tenant_id, url="https://transient.example", title="Transient")
    blocked_key = _register(conn, tenant_id, url="https://nokey.example", title="No Key")
    done = _register(conn, tenant_id, url="https://done.example", title="Done")
    for cid in (permanent, transient, blocked_key, done):
        # SOCIAL_LINKS, REVIEWS and NEWS are settled for all four, so only PROFILE decides who is picked.
        ce._write_ledger(conn, tenant_id, cid, ce.FACET_SOCIAL_LINKS, ce.STATUS_SUCCEEDED)
        ce._write_ledger(conn, tenant_id, cid, ce.FACET_REVIEWS, ce.STATUS_SUCCEEDED)
        ce._write_ledger(conn, tenant_id, cid, ce.FACET_NEWS, ce.STATUS_SUCCEEDED)
    ce._write_ledger(conn, tenant_id, done, ce.FACET_PROFILE, ce.STATUS_SUCCEEDED)
    ce._write_ledger(conn, tenant_id, permanent, ce.FACET_PROFILE, ce.STATUS_FAILED, ce.NO_MATCH, "x")
    ce._write_ledger(conn, tenant_id, transient, ce.FACET_PROFILE, ce.STATUS_FAILED, ce.PROVIDER_ERROR, "x")
    ce._write_ledger(conn, tenant_id, blocked_key, ce.FACET_PROFILE, ce.STATUS_BLOCKED, ce.NO_CREDENTIALS, "x")
    with conn.cursor() as cursor:  # make the transient failure's scheduled retry due
        cursor.execute("UPDATE competitor_enrichment SET next_retry_at = NOW() - INTERVAL '1 minute' WHERE global_competitor_id = %s;", (transient,))
    conn.commit()

    assert set(_candidates_picked(conn, tenant_id, "due")) == {transient}
    assert set(_candidates_picked(conn, tenant_id, "force")) == {permanent, transient, blocked_key}


def test_the_sweep_function_lists_only_tenants_with_work(conn):
    busy, idle = _insert_company(conn), _insert_company(conn)
    _register(conn, busy)
    _register(conn, idle)
    for facet in (ce.FACET_PROFILE, ce.FACET_SOCIAL_LINKS):
        ce._write_ledger(conn, idle, _only_competitor(conn, idle), facet, ce.STATUS_SUCCEEDED)
    # `busy` has a competitor whose PROFILE was never attempted
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM list_tenants_with_due_enrichment();")
        tenants = {str(r[0]) for r in cursor.fetchall()}
    assert busy in tenants and idle not in tenants


def _only_competitor(conn, tenant_id):
    with conn.cursor() as cursor:
        cursor.execute("SELECT global_competitor_id FROM tenant_competitors WHERE tenant_id = %s;", (tenant_id,))
        return str(cursor.fetchone()[0])


def test_price_coverage_reports_each_product_with_its_real_reason(conn):
    from src.market_scraper.price_coverage import REASON_NO_MAPPING, REASON_TERMS, get_price_coverage
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    with conn.cursor() as cursor:
        for name in ("Mapped but unreviewed", "Unmatched"):
            cursor.execute(
                "INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s::jsonb, 5, 'JOD') RETURNING product_id;",
                (tenant_id, '{"en": "%s"}' % name),
            )
            if name.startswith("Mapped"):
                product_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO data_sources (tenant_id, source_name, source_type, policy_status) VALUES (%s, 'x', 'WEB_SCRAPE', 'RESTRICTED') RETURNING source_id;", (tenant_id,))
        source_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, competitor_product_url, source_id) VALUES (%s, %s, %s, 'https://x.example/p', %s);",
            (tenant_id, competitor_id, product_id, source_id),
        )
    conn.commit()
    result = get_price_coverage(conn, tenant_id)
    reasons = {i["product_name"]: i["reason_code"] for i in result["products"]}
    assert reasons == {"Mapped but unreviewed": REASON_TERMS, "Unmatched": REASON_NO_MAPPING}
    assert result["summary"]["coverage_pct"] == 0.0
    assert next(i for i in result["products"] if i["reason_code"] == REASON_TERMS)["source_ids"] == [str(source_id)]


def test_price_coverage_flags_stale_foreign_currency_and_switched_off_mappings_from_real_rows(conn):
    from src.market_scraper import price_coverage as pc
    tenant_id = _insert_company(conn)
    first = _register(conn, tenant_id, url="https://first.example", title="First")
    second = _register(conn, tenant_id, url="https://second.example", title="Second")
    products = {}
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO data_sources (tenant_id, source_name, source_type, policy_status) VALUES (%s, 'x', 'WEB_SCRAPE', 'RESTRICTED') RETURNING source_id;", (tenant_id,))
        source_id = cursor.fetchone()[0]
        for name in ("Old price", "Priced in USD", "Mapping off"):
            cursor.execute(
                "INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s::jsonb, 5, 'JOD') RETURNING product_id;",
                (tenant_id, '{"en": "%s"}' % name),
            )
            products[name] = cursor.fetchone()[0]
        mappings = {}
        for name, competitor, active in (("Old price", first, True), ("Priced in USD", first, True), ("Mapping off", second, False)):
            cursor.execute(
                "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, competitor_product_url, source_id, is_active) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING mapping_id;",
                (tenant_id, competitor, products[name], f"https://x.example/{name.replace(' ', '-')}", source_id, active),
            )
            mappings[name] = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, observed_at) VALUES (%s, %s, 4.5, 'JOD', NOW() - make_interval(days => %s));",
            (tenant_id, mappings["Old price"], pc.STALE_AFTER_DAYS + 10),
        )
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency) VALUES (%s, %s, 7.1, 'USD');",
            (tenant_id, mappings["Priced in USD"]),
        )
    conn.commit()

    result = pc.get_price_coverage(conn, tenant_id)
    items = {i["product_name"]: i for i in result["products"]}
    assert items["Old price"]["issues"] == [pc.ISSUE_STALE] and items["Old price"]["next_action"] == "refresh_prices"
    # The row is 40 days old by the DATABASE's clock; the test host's clock can differ by minutes (a Docker VM
    # drifts), which moves a whole-days age across a boundary - so allow a day either way.
    assert abs(items["Old price"]["price_age_days"] - (pc.STALE_AFTER_DAYS + 10)) <= 1
    assert items["Priced in USD"]["issues"] == [pc.ISSUE_CURRENCY] and items["Priced in USD"]["foreign_currency_prices"] == 1
    assert items["Mapping off"]["has_market_price"] is False and items["Mapping off"]["inactive_mappings"] == 1
    assert items["Mapping off"]["next_action"] == "review_mappings"
    summary = result["summary"]
    assert (summary["stale_prices"], summary["currency_mismatches"], summary["inactive_mappings"]) == (1, 1, 1)
    assert summary["with_market_price"] == 2 and summary["needs_attention"] == 3


def test_price_lookup_picks_only_unpriced_products_stores_a_quote_and_skips_recent_lookups(conn):
    from src.market_scraper.price_lookup import pipeline
    from src.market_scraper.price_lookup.models import PriceQuote
    tenant_id = _insert_company(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, metadata) VALUES (%s, '{\"en\": \"Nutella Hazelnut Spread 350g\"}'::jsonb, 3.5, 'JOD', '{\"barcode\": \"3017-6204-22003\"}'::jsonb) RETURNING product_id;",
            (tenant_id,),
        )
        product_id = str(cursor.fetchone()[0])
    conn.commit()

    contexts = pipeline.products_needing_a_price(conn, tenant_id, limit=10)
    assert [c.product_id for c in contexts] == [product_id]
    assert contexts[0].barcode == "3017620422003"  # read from products.metadata, digits only

    quote = PriceQuote("web_offers", "Nutella Hazelnut Spread 350g", 3.4, "JOD", seller="Shop", url="https://shop.example/p", rating=4.6, review_count=12)
    assert pipeline._store(conn, tenant_id, contexts[0], quote, 1.0, True) is True
    assert pipeline._store(conn, tenant_id, contexts[0], quote, 1.0, True) is False  # same listing: updated, not duplicated
    pipeline._record_lookup(conn, tenant_id, contexts[0], pipeline.OUTCOME_FOUND, ["web_offers"], 1)
    conn.commit()

    assert pipeline.products_needing_a_price(conn, tenant_id, limit=10) == []  # it now has a reference price
    from src.market_scraper.price_coverage import get_price_coverage
    summary = get_price_coverage(conn, tenant_id, include_covered=True)
    assert summary["summary"]["with_reference_price_only"] == 1
    assert summary["products"][0]["price_basis"] == "market_reference"


# ---- news and comments from further sources -------------------------------------------------------------

def test_new_facets_are_accepted_by_the_ledger_and_news_is_stored_once_with_its_origin(conn):
    from src.market_scraper import competitor_mentions as cm  # noqa: F401
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    ce._write_ledger(conn, tenant_id, competitor_id, ce.FACET_NEWS, ce.STATUS_SUCCEEDED, items_found=2)
    ce._write_ledger(conn, tenant_id, competitor_id, ce.FACET_COMMENTS, ce.STATUS_FAILED, ce.NO_VIDEOS, "none")
    items = [
        {"url": "https://burgerhub.example/a", "title": "New branch", "summary": "Opening soon", "published_at": "2026-10-01T10:00:00+00:00", "source_domain": "burgerhub.example"},
        {"url": "https://news.example/b", "title": "Burger Hub wins award", "summary": None, "published_at": None, "source_domain": "news.example"},
    ]
    assert ce._save_news(conn, tenant_id, competitor_id, items, "own_site") == 2
    assert ce._save_news(conn, tenant_id, competitor_id, items, "web_search") == 0  # already stored: left as it is
    with conn.cursor() as cursor:
        cursor.execute("SELECT title, topic, source_kind, summary, global_competitor_id::text FROM market_news WHERE tenant_id = %s ORDER BY url;", (tenant_id,))
        rows = cursor.fetchall()
    assert rows[0] == ("New branch", "competitor", "own_site", "Opening soon", competitor_id)
    facets = ce.load_data_completeness(conn, tenant_id, competitor_id)[competitor_id]["facets"]
    assert facets[ce.FACET_NEWS]["status"] == ce.STATUS_SUCCEEDED and facets[ce.FACET_NEWS]["items_found"] == 2  # the data wins
    assert facets[ce.FACET_COMMENTS]["reason_code"] == ce.NO_VIDEOS


def test_comments_are_stored_with_likes_and_replies_linked_to_their_parent_and_restored_idempotently(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    source_id = ce._review_source(conn, tenant_id, str(uuid.uuid4()), "ops-1", name="YouTube comments (official API)", collector_key="youtube_comments", retention_days=30)
    again = ce._review_source(conn, tenant_id, str(uuid.uuid4()), "ops-1", name="YouTube comments (official API)", collector_key="youtube_comments", retention_days=30)
    assert source_id == again  # one source per tenant and provider
    with conn.cursor() as cursor:
        cursor.execute("SELECT retention_days, policy_status FROM data_sources WHERE source_id = %s;", (source_id,))
        assert cursor.fetchone() == (30, "ALLOWED")

    comments = [
        {"external_id": "c1", "parent_external_id": None, "author": "Sam", "text": "Terrible service", "likes": 400, "published_at": "2026-10-01T10:00:00Z", "reply_count": 1},
        {"external_id": "r1", "parent_external_id": "c1", "author": "Lee", "text": "Same here", "likes": 2, "published_at": "2026-10-02T10:00:00Z", "reply_count": None},
    ]
    assert ce._save_comments(conn, tenant_id, competitor_id, source_id, "YouTube", comments) == 2
    comments[0]["likes"] = 450  # likes grow between runs
    assert ce._save_comments(conn, tenant_id, competitor_id, source_id, "YouTube", comments) == 0
    from src.ai.market_inputs import competitor_comments
    result = competitor_comments.list_competitor_comments(conn, tenant_id, competitor_id)
    assert result["comments"][0]["people_agreeing"] == 450 and result["comments"][0]["platform"] == "YouTube"
    assert [r["text"] for r in result["comments"][0]["replies"]] == ["Same here"]


def test_deeper_google_reviews_do_not_duplicate_what_places_gave_and_add_likes_and_owner_replies(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    source_id = ce._places_review_source(conn, tenant_id, str(uuid.uuid4()), "ops-1")
    with conn.cursor() as cursor:  # a review the Places API already gave (no likes, no id from Apify)
        cursor.execute(
            "INSERT INTO reviews (tenant_id, source_platform, reviewer_name, review_text, review_rating, subject_type, competitor_id, source_status, "
            "collection_method, source_id, external_review_id) VALUES (%s, 'Google Places', 'Sam', 'Cold food and a very long wait for the bill', 1, 'COMPETITOR', %s, 'ALLOWED', 'PUBLIC_API', %s, 'places-hash');",
            (tenant_id, competitor_id, source_id),
        )
    conn.commit()
    deep = [
        {"external_id": "g1", "author": "Sam", "text": "Cold food and a very long wait for the bill - never again", "rating": 1.0, "likes": 12,
         "published_at": "2026-09-01T10:00:00Z", "owner_reply": "We are sorry", "owner_reply_at": "2026-09-02T10:00:00Z"},
        {"external_id": "g2", "author": "Lee", "text": "Lovely staff", "rating": 5.0, "likes": 0, "published_at": "2026-09-03T10:00:00Z", "owner_reply": None, "owner_reply_at": None},
    ]
    with patch.object(ce.mentions, "apify_google_reviews", return_value=deep):
        new, total = ce._store_deep_google_reviews(conn, tenant_id, competitor_id, "PID", source_id, "TOKEN")
        again = ce._store_deep_google_reviews(conn, tenant_id, competitor_id, "PID", source_id, "TOKEN")
    assert (new, total) == (1, 2) and again == (0, 2)  # Sam's review was already there; Lee's is new; a re-run adds nothing
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM reviews WHERE tenant_id = %s AND competitor_id = %s AND parent_review_id IS NULL;", (tenant_id, competitor_id))
        assert cursor.fetchone()[0] == 2
        cursor.execute("SELECT like_count FROM reviews WHERE tenant_id = %s AND reviewer_name = 'Sam' AND parent_review_id IS NULL;", (tenant_id,))
        assert cursor.fetchone()[0] == 12  # the existing review gained its likes
        cursor.execute("SELECT review_text FROM reviews WHERE tenant_id = %s AND reviewer_name = 'Owner';", (tenant_id,))
        assert cursor.fetchall() == [("We are sorry",)]


def test_youtube_comments_are_deleted_after_their_retention_but_other_sources_are_only_anonymized(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    youtube = ce._review_source(conn, tenant_id, str(uuid.uuid4()), "ops-1", name="YouTube comments (official API)", collector_key="youtube_comments", retention_days=30)
    google = ce._places_review_source(conn, tenant_id, str(uuid.uuid4()), "ops-1")
    with conn.cursor() as cursor:
        for source, ext, text in ((youtube, "old-yt", "old youtube"), (youtube, "new-yt", "new youtube"), (google, "old-g", "old google")):
            cursor.execute(
                "INSERT INTO reviews (tenant_id, source_platform, reviewer_name, review_text, subject_type, competitor_id, source_status, collection_method, source_id, external_review_id, review_date, created_at) "
                "VALUES (%s, 'X', 'Sam', %s, 'COMPETITOR', %s, 'ALLOWED', 'PUBLIC_API', %s, %s, NOW() - INTERVAL '400 days', "
                "CASE WHEN %s LIKE 'old%%' THEN NOW() - INTERVAL '45 days' ELSE NOW() END);",
                (tenant_id, text, competitor_id, source, ext, ext),
            )
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute("SELECT enforce_comment_retention();")
        assert cursor.fetchone()[0] >= 1  # the function is cross-tenant: other tenants' expired comments may go too
        cursor.execute("SELECT review_text FROM reviews WHERE tenant_id = %s ORDER BY review_text;", (tenant_id,))
        assert [r[0] for r in cursor.fetchall()] == ["new youtube", "old google"]
