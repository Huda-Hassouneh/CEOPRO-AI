"""PRICES and SOCIAL_CONTENT facets, the completeness panel, and deploy-order safety on a real Postgres through the
restricted app role. Skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD are set."""
import os

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test")

from src.ai import db  # noqa: E402
from src.ai.market_inputs import competitor_intel  # noqa: E402
from src.ai.tests.test_intel_review_integration_db import PAGES, _collect, _setup  # noqa: E402
from src.market_scraper import competitor_enrichment as ce  # noqa: E402
from src.market_scraper import social_content  # noqa: E402
from src.market_scraper.market_discovery import intel  # noqa: E402


_REAL_COLLECT = intel.collect


def _use_pages(monkeypatch, pages):
    monkeypatch.setattr(intel, "collect", lambda url, **kw: _REAL_COLLECT(url, fetch=lambda u: pages.get(u.rstrip("/")), **kw))


def test_prices_facet_reads_the_site_writes_the_ledger_and_shows_in_the_panel(monkeypatch):
    tenant, user, competitor_id = _setup()
    _use_pages(monkeypatch, PAGES)
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        result = ce.enrich_competitor(conn, tenant, competitor_id, facets=[ce.FACET_PRICES])
        conn.commit()
        assert result[ce.FACET_PRICES]["status"] == ce.STATUS_SUCCEEDED and result[ce.FACET_PRICES]["items_found"] >= 4
        panel = ce.load_data_completeness(conn, tenant, competitor_id)[competitor_id]["facets"][ce.FACET_PRICES]
        assert panel["can_retry"] is True and panel["status"] in (ce.STATUS_SUCCEEDED, ce.STATUS_BLOCKED, ce.STATUS_FAILED)

        # A site that is read fine but no longer shows prices replaces what was stored (prices that were taken down
        # are not kept); the outcome says why instead of crashing.
        _use_pages(monkeypatch, {"https://habibah.jo": "<html><body><h1>Closed for renovation</h1></body></html>"})
        again = ce.enrich_competitor(conn, tenant, competitor_id, facets=[ce.FACET_PRICES], deep=True)
        conn.commit()
        assert (again[ce.FACET_PRICES]["status"], again[ce.FACET_PRICES]["reason_code"]) == (ce.STATUS_FAILED, ce.NO_PRICES_PUBLISHED)
    finally:
        conn.close()


def test_a_site_without_prices_reports_why(monkeypatch):
    tenant, user, competitor_id = _setup()
    _use_pages(monkeypatch, {"https://habibah.jo": "<html><body><h1>Welcome</h1><p>Come and visit us.</p></body></html>"})
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        with conn.cursor() as cursor:  # the discovery run in _setup already stored prices; start clean
            cursor.execute("DELETE FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s;", (tenant, competitor_id))
        result = ce.enrich_competitor(conn, tenant, competitor_id, facets=[ce.FACET_PRICES])
        conn.commit()
        assert result[ce.FACET_PRICES]["status"] == ce.STATUS_FAILED
        assert result[ce.FACET_PRICES]["reason_code"] in (ce.NO_PRICES_PUBLISHED,)
        panel = ce.load_data_completeness(conn, tenant, competitor_id)[competitor_id]["facets"][ce.FACET_PRICES]
        assert panel["reason_code"] in (ce.NO_PRICES_PUBLISHED, ce.NO_PRODUCTS_MAPPED, ce.NO_DATA_COLLECTED, ce.TERMS_UNREVIEWED)
    finally:
        conn.close()


def test_social_content_facet_stores_channel_facts_and_the_panel_shows_the_outcome(monkeypatch):
    tenant, user, competitor_id = _setup()
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        cursor.execute("UPDATE global_competitors SET social_profiles = %s::jsonb WHERE global_competitor_id = %s;",
                       ('{"instagram": "https://www.instagram.com/habibahsweets/"}', competitor_id))
    monkeypatch.setenv("APIFY_API_TOKEN", "tok")
    monkeypatch.setenv("SOCIAL_CONTENT_APPROVAL_REFERENCE", "TICKET-7")
    monkeypatch.setattr(social_content, "fetch_posts", lambda url, platform, token, limit, post=None: social_content.normalize_posts(
        [{"id": "1", "url": "https://www.instagram.com/p/AAA/", "caption": "New: Mansaf 8.50 JD, Tea 0.75 JD\nBuy 2 get 1 free!"}], platform))
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        before = ce.load_data_completeness(conn, tenant, competitor_id)[competitor_id]["facets"][ce.FACET_SOCIAL_CONTENT]
        assert before["status"] == ce.STATUS_PENDING and before["can_retry"] is True
        result = ce.enrich_competitor(conn, tenant, competitor_id, facets=[ce.FACET_SOCIAL_CONTENT])
        conn.commit()
        assert result[ce.FACET_SOCIAL_CONTENT]["status"] in (ce.STATUS_SUCCEEDED, ce.STATUS_PARTIAL)
        found = competitor_intel.get_intel(conn, tenant, competitor_id)
        social = [p for p in found["products"] if p.get("channel") == "instagram"]
        assert {p["name"] for p in social} == {"Mansaf", "Tea"} and all(p["source_url"].endswith("/p/AAA/") for p in social)
        assert any(p.get("channel") == "instagram" for p in found["promotions"])
        after = ce.load_data_completeness(conn, tenant, competitor_id)[competitor_id]["facets"][ce.FACET_SOCIAL_CONTENT]
        assert after["status"] in (ce.STATUS_SUCCEEDED, ce.STATUS_PARTIAL) and after["items_found"] == 3
    finally:
        conn.close()


def test_reading_a_site_still_works_when_the_review_table_is_not_deployed_yet():
    tenant, user, competitor_id = _setup()
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        cursor.execute("ALTER TABLE competitor_intel_review RENAME TO competitor_intel_review_off;")
    try:
        conn = db.dedicated_tenant_connection(tenant, user)
        try:
            outcome = competitor_intel.refresh_competitor(conn, tenant, competitor_id, collect=_collect(PAGES))
            conn.commit()  # a poisoned transaction would fail here
            assert outcome["status"] == "prices_found"
            assert len(competitor_intel.get_intel(conn, tenant, competitor_id)["products"]) >= 4
        finally:
            conn.close()
    finally:
        with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
            cursor.execute("ALTER TABLE competitor_intel_review_off RENAME TO competitor_intel_review;")
