"""
Competitor discovery against a real Postgres through the restricted app
role: a restaurant and a pharmacy each run discovery, results are stored
with provenance, a refresh updates instead of duplicating, auto-tracking
respects the plan limit, and neither company can see the other's results.
Sources are replaced by fakes returning the shapes the real APIs return.
"""
import json
import os
import re
import time
import uuid

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test")

from src.ai import db  # noqa: E402
from src.ai.market_inputs import discovered_competitors, public_sources  # noqa: E402
from src.market_scraper.market_discovery import intel, pipeline  # noqa: E402
from src.market_scraper.market_discovery.models import Candidate, ProviderResult  # noqa: E402

AMMAN = (31.9539, 35.9106)
# The background-worker principal: trusted for the tenant its connection is scoped to.
SERVICE_ACTOR = "00000000-0000-0000-0000-000000000000"


class FakeProvider:
    def __init__(self, name, candidates=None, status="ok"):
        self.NAME, self.candidates, self.status, self.calls = name, candidates or [], status, 0

    def available(self):
        return True, None

    def search(self, query):
        self.calls += 1
        return ProviderResult(self.NAME, self.status, list(self.candidates), reason=None if self.status == "ok" else "unreachable",
                              requests=1)


def _company(business_type, industry_key=None):
    tenant_id, user_id = str(uuid.uuid4()), SERVICE_ACTOR
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO companies (tenant_id, business_name, business_type, industry_key, country_code, primary_currency,
                                   city, latitude, longitude)
            VALUES (%s, %s, %s, %s, 'JO', 'JOD', 'Amman', %s, %s);
            """,
            (tenant_id, f"Discovery {tenant_id[:6]}", business_type, industry_key, *AMMAN),
        )
    return tenant_id, user_id


def _place(name, ref, source="openstreetmap", lat=31.955, lon=35.912, industry="restaurant", **kw):
    return Candidate(name=name, source=source, source_ref=ref, latitude=lat, longitude=lon, industry_key=industry,
                     source_url=f"https://www.openstreetmap.org/{ref}" if source == "openstreetmap" else None, **kw)


def _no_website(url):
    return {"facts": [], "pages_read": [], "pages_blocked": 0, "error": "unreachable"}


def _no_news(industry_terms, competitor_names, country_code):
    return {"articles": [], "requests": 0, "answered": 0, "status": "skipped", "reason": "disabled"}


def _run(tenant_id, user_id, providers, site_reader=_no_website, news_reader=_no_news):
    conn = db.dedicated_tenant_connection(tenant_id, user_id)
    try:
        run_id = pipeline.start_run(conn, tenant_id, user_id)
        conn.commit()
        summary = pipeline.execute_run(conn, tenant_id, run_id, providers=providers, site_reader=site_reader,
                                       news_reader=news_reader)
        listing = discovered_competitors.list_competitors(conn, tenant_id)
        run = pipeline.get_run(conn, tenant_id, run_id)
        return summary, listing, run
    finally:
        conn.close()


def test_restaurant_and_pharmacy_discover_their_own_competitors_without_leakage():
    restaurant, r_user = _company("Lebanese restaurant")
    pharmacy, p_user = _company("Neighbourhood pharmacy", "pharmacy")
    osm = FakeProvider("openstreetmap", [
        _place("Hashem", "node/1", website="https://hashem.jo", phone="06 463 6440"),
        _place("Reem Shawarma", "node/2", lat=31.96, lon=35.92),
        _place("Tyre Centre", "node/3", industry="automotive"),
    ])
    google = FakeProvider("google_places", [
        _place("Hashem Restaurant", "ChIJ1", source="google_places", lat=31.9551, lon=35.9121,
               website="http://www.hashem.jo/", rating=4.5, review_count=12000),
    ])
    web = FakeProvider("web_search", status="failed")

    summary, listing, run = _run(restaurant, r_user, (osm, google, web))
    assert summary["status"] == "partial"  # one source failed, others answered
    assert run["providers"]["web_search"]["status"] == "failed"
    names = sorted(c["name"] for c in listing["competitors"])
    assert len(names) == 2 and "Reem Shawarma" in names  # merged across sources; other industry dropped
    hashem = next(c for c in listing["competitors"] if c["name"].startswith("Hashem"))
    # Two map listings back it, shown to the customer as one public category -
    # the internal providers that found it are never named, though the
    # listing itself is linked so the customer can check it.
    assert hashem["source_count"] == 2 and [s["source"] for s in hashem["sources"]] == ["map_listing"]
    assert hashem["sources"][0]["url"].startswith("https://www.openstreetmap.org/")
    payload = re.sub(r"https?://[^\s\"]+", "", json.dumps([listing, public_sources.public_run(run)], default=str).lower())
    for internal in ("openstreetmap", "google_places", "apify", "searxng", "overpass"):
        assert internal not in payload, internal
    assert hashem["rating"] == 4.5 and hashem["review_count"] == 12000 and hashem["distance_km"] < 1
    assert hashem["confidence"] > next(c for c in listing["competitors"] if c["name"] == "Reem Shawarma")["confidence"]
    assert hashem["is_tracked"]  # strong new match is tracked automatically

    pharmacy_osm = FakeProvider("openstreetmap", [_place("Amal Pharmacy", "node/9", industry="pharmacy")])
    _, p_listing, _ = _run(pharmacy, p_user, (pharmacy_osm,))
    assert [c["name"] for c in p_listing["competitors"]] == ["Amal Pharmacy"]

    # Through the app role each company sees only its own results and sources.
    conn = db.dedicated_tenant_connection(pharmacy, p_user)
    try:
        assert discovered_competitors.get_competitor(conn, pharmacy, hashem["competitor_id"]) is None
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM competitor_sources;")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM discovery_runs;")
            assert cursor.fetchone()[0] == 1
    finally:
        conn.close()


def test_refresh_updates_existing_competitors_instead_of_duplicating():
    tenant, user = _company("cafe", "cafe")
    first = FakeProvider("openstreetmap", [_place("Bean There", "node/5", industry="cafe")])
    _run(tenant, user, (first,))
    again = FakeProvider("openstreetmap", [_place("Bean There", "node/5", industry="cafe", phone="079 123 4567")])
    summary, listing, _ = _run(tenant, user, (again,))
    assert summary["new_count"] == 0 and summary["updated_count"] == 1
    assert len(listing["competitors"]) == 1 and listing["competitors"][0]["phone"] == "079 123 4567"


def test_auto_tracking_stays_within_the_plan_limit_and_one_run_at_a_time():
    tenant, user = _company("hotel", "hotel")
    many = FakeProvider("openstreetmap", [
        _place(f"Hotel {i}", f"node/{i}", industry="hotel", lat=31.954 + i * 0.0005, website=f"https://hotel{i}.jo")
        for i in range(30)])
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        from src.ai.core import usage

        limit = usage.get_plan(conn, tenant)["features"][usage.TRACKED_COMPETITORS]["limit"]
        run_id = pipeline.start_run(conn, tenant, user)
        conn.commit()
        with pytest.raises(pipeline.DiscoveryBusy):
            pipeline.start_run(conn, tenant, user)
        conn.rollback()
        pipeline.execute_run(conn, tenant, run_id, providers=(many,), site_reader=_no_website, news_reader=_no_news)
        tracked = discovered_competitors.list_competitors(conn, tenant, status="tracked")["competitors"]
        suggested = discovered_competitors.list_competitors(conn, tenant, status="suggested")["competitors"]
        assert len(tracked) <= min(pipeline.AUTO_TRACK_MAX, limit or pipeline.AUTO_TRACK_MAX)
        assert len(tracked) + len(suggested) == 30
        assert discovered_competitors.set_tracked(conn, tenant, suggested[0]["competitor_id"], True)
        conn.commit()
    finally:
        conn.close()


def test_stale_discovery_is_refreshed_on_schedule_and_fresh_is_left_alone():
    from datetime import datetime, timedelta, timezone

    from src.market_scraper.market_discovery import refresh

    tenant, user = _company("cafe", "cafe")
    _run(tenant, user, (FakeProvider("openstreetmap", [_place("Bean There", "node/5", industry="cafe")]),))
    never_ran, _ = _company("Lebanese restaurant")

    def due_now(now=None):
        conn = db.system_connection()
        try:
            return [t for t, *_ in refresh.due(conn, now=now, limit=1000)]
        finally:
            conn.close()

    assert tenant not in due_now()  # just ran
    later = datetime.now(timezone.utc) + timedelta(days=8)
    stale = due_now(later)
    assert tenant in stale and never_ran not in stale  # never-scanned companies are never scanned for them

    source = FakeProvider("openstreetmap", [_place("Bean There", "node/5", industry="cafe"),
                                            _place("Daily Grind", "node/6", industry="cafe")])
    # Other test companies in this database are due too; refresh only this one.
    real_due = refresh.due
    refresh.due = lambda conn, now=None: [row for row in real_due(conn, now=now, limit=1000) if row[0] == tenant]
    try:
        outcome = refresh.refresh_once(now=later, providers=(source,))
    finally:
        refresh.due = real_due
    assert outcome == {"due": 1, "refreshed": 1, "busy": 0, "failed": 0, "no_budget": 0} and source.calls == 1
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        names = sorted(c["name"] for c in discovered_competitors.list_competitors(conn, tenant)["competitors"])
        assert names == ["Bean There", "Daily Grind"]
    finally:
        conn.close()


def test_results_from_every_web_search_provider_can_be_saved():
    # brave_search / tavily_search used to break the run at the database.
    tenant, user = _company("Bakery", "bakery")
    web = FakeProvider("web_search", [
        Candidate(name="Habibah Sweets", source="brave_search", source_ref="habibah.jo", source_url="https://habibah.jo/",
                  website="https://habibah.jo", online_only=True, industry_key="bakery"),
        Candidate(name="Zalatimo", source="tavily_search", source_ref="zalatimo.com", source_url="https://zalatimo.com/",
                  website="https://zalatimo.com", online_only=True, industry_key="bakery"),
    ])
    summary, listing, _run_row = _run(tenant, user, (web,))
    assert summary["status"] == "completed"
    assert sorted(c["name"] for c in listing["competitors"]) == ["Habibah Sweets", "Zalatimo"]


def test_competitor_websites_are_read_stored_with_sources_and_kept_private():
    from fastapi.testclient import TestClient
    import jwt

    from src.ai.main import app
    from src.ai.market_inputs import competitor_intel
    from src.ai.tests.test_competitor_intel import HOME, MENU, OFFERS

    pages = {"https://habibah.jo": HOME, "https://habibah.jo/menu": MENU, "https://habibah.jo/offers": OFFERS}
    site = lambda url: pages.get(url.rstrip("/"))  # noqa: E731
    tenant, user = _company("Bakery", "bakery")
    other, other_user = _company("Bakery", "bakery")
    osm = FakeProvider("openstreetmap", [_place("Habibah Sweets", "node/9", industry="bakery", website="https://habibah.jo")])
    summary, listing, run = _run(tenant, user, (osm,), site_reader=lambda url: intel.collect(url, fetch=site))
    competitor_id = listing["competitors"][0]["competitor_id"]
    # One map search plus three pages of the competitor's site, all answered.
    assert (run["sources_checked"], run["sources_answered"]) == (4, 4)
    assert summary["providers"]["website_intel"]["found"] == 1

    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        found = competitor_intel.get_intel(conn, tenant, competitor_id)
        assert found["status"] == "prices_found" and found["checked_at"]
        prices = {(p["name"], p["price"]) for p in found["products"]}
        assert ("Kunafa Khishneh", 3.75) in prices and found["price_conflicts"] == ["kunafa nabulsieh"]
        assert all(p["source_url"].startswith("https://habibah.jo") and p["retrieved_at"] for p in found["products"])
        assert any("Free delivery" in p["text"] for p in found["promotions"])
        # Read again when the site is down: what was read before is kept.
        assert competitor_intel.refresh_competitor(conn, tenant, competitor_id,
                                                   collect=lambda url: intel.collect(url, fetch=lambda u: None))["status"] == "blocked_by_robots"
        conn.commit()
        assert len(competitor_intel.get_intel(conn, tenant, competitor_id)["products"]) == len(found["products"])
    finally:
        conn.close()

    # Another company sees none of it, through the database or the API.
    conn = db.dedicated_tenant_connection(other, other_user)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM competitor_intel;")
            assert cursor.fetchone()[0] == 0
    finally:
        conn.close()
    client = TestClient(app)
    token = jwt.encode({"tenant_id": other, "user_id": other_user, "exp": int(time.time()) + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/discovery/competitors/{competitor_id}", headers=headers).status_code == 404
    assert client.post(f"/discovery/competitors/{competitor_id}/refresh", headers=headers).status_code == 404


def test_industry_and_competitor_news_is_stored_with_links_and_private():
    from src.ai.market_inputs import market_news

    tenant, user = _company("Bakery", "bakery")
    other, other_user = _company("Bakery", "bakery")
    osm = FakeProvider("openstreetmap", [_place("Habibah Sweets", "node/9", industry="bakery")])
    asked = []

    def news_reader(industry_terms, competitor_names, country_code):
        asked.append((industry_terms, competitor_names, country_code))
        return {"requests": 2, "answered": 2, "status": "ok", "reason": None, "articles": [
            {"url": "https://jordantimes.com/news/bakeries-flour-prices", "title": "Bakeries feel rising flour prices",
             "source_domain": "jordantimes.com", "language": "English", "published_at": "2026-10-01T08:00:00+00:00",
             "topic": "industry"},
            {"url": "https://roya.news/habibah-new-branch", "title": "Habibah Sweets opens a new branch in Irbid",
             "source_domain": "roya.news", "language": "English", "published_at": "2026-09-20T10:00:00+00:00",
             "topic": "competitor", "competitor": "Habibah Sweets"},
        ]}

    summary, listing, run = _run(tenant, user, (osm,), news_reader=news_reader)
    assert asked[0][1] == ["Habibah Sweets"] and asked[0][2] == "JO" and "bakery" in asked[0][0]
    assert run["sources_checked"] == 3 and summary["providers"]["gdelt"]["found"] == 2
    assert public_sources.public_run(run)["providers"]["news"]["found"] == 2
    _run(tenant, user, (osm,), news_reader=news_reader)  # the same articles again are not duplicated
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        articles = market_news.latest(conn, tenant)
        assert [a["title"] for a in articles] == ["Bakeries feel rising flour prices", "Habibah Sweets opens a new branch in Irbid"]
        assert articles[1]["competitor_id"] == listing["competitors"][0]["competitor_id"]
        assert articles[1]["competitor_name"] == "Habibah Sweets" and articles[0]["url"].startswith("https://")
    finally:
        conn.close()
    conn = db.dedicated_tenant_connection(other, other_user)
    try:
        assert market_news.latest(conn, other) == []
    finally:
        conn.close()


def test_ai_analysis_cites_only_real_evidence_and_stays_private(monkeypatch):
    from fastapi.testclient import TestClient
    import jwt

    from src.ai.main import app
    from src.ai.rag import llm_client
    from src.ai.tests.test_competitor_intel import HOME, MENU, OFFERS

    pages = {"https://habibah.jo": HOME, "https://habibah.jo/menu": MENU, "https://habibah.jo/offers": OFFERS}
    tenant, user = _company("Bakery", "bakery")
    other, other_user = _company("Bakery", "bakery")
    osm = FakeProvider("openstreetmap", [_place("Habibah Sweets", "node/9", industry="bakery", website="https://habibah.jo")])
    _summary, listing, _run_row = _run(tenant, user, (osm,), site_reader=lambda url: intel.collect(url, fetch=lambda u: pages.get(u.rstrip("/"))))
    competitor_id = listing["competitors"][0]["competitor_id"]
    prompts = []

    def model(messages, **kwargs):
        prompts.append(messages[1]["content"])
        return json.dumps({
            "positioning": {"text": "Traditional Nablus kunafa specialist", "evidence": [5, 99]},
            "target_audience": {"text": "Families buying sweets for occasions", "evidence": []},  # uncited: dropped
            "strengths": [{"text": "Low kunafa price of 3.50 JD", "evidence": [4]}, {"text": "Invented claim", "evidence": [500]}],
            "weaknesses": [], "differentiators": [{"text": "Free delivery over 10 JD", "evidence": ["8"]}], "opportunities": "not a list",
        }), {"total_tokens": 1234}

    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", model)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {jwt.encode({'tenant_id': tenant, 'user_id': user, 'exp': int(time.time()) + 3600}, os.environ['JWT_SECRET'], algorithm='HS256')}"}
    response = client.post(f"/discovery/competitors/{competitor_id}/analysis", headers=headers)
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert "[1] The user's company" in prompts[0] and "Habibah Sweets lists Kunafa Khishneh - 3.75 JOD" in prompts[0]
    assert analysis["is_ai_analysis"] and analysis["positioning"]["text"] == "Traditional Nablus kunafa specialist"
    assert [c["n"] for c in analysis["positioning"]["citations"]] == [5]  # 99 doesn't exist
    assert analysis["target_audience"] is None and analysis["opportunities"] == []
    assert [s["text"] for s in analysis["strengths"]] == ["Low kunafa price of 3.50 JD"]
    cited = analysis["strengths"][0]["citations"][0]
    assert cited["url"].startswith("https://habibah.jo")
    stored = client.get(f"/discovery/competitors/{competitor_id}", headers=headers).json()["intel"]["analysis"]
    assert stored["strengths"] == analysis["strengths"]
    other_headers = {"Authorization": f"Bearer {jwt.encode({'tenant_id': other, 'user_id': other_user, 'exp': int(time.time()) + 3600}, os.environ['JWT_SECRET'], algorithm='HS256')}"}
    assert client.post(f"/discovery/competitors/{competitor_id}/analysis", headers=other_headers).status_code == 404


def test_a_competitors_published_prices_reach_the_product_comparison():
    """Discovery -> its site read -> its menu items matched to the company's
    products -> mappings and prices -> the Competitors page's product figures.
    A same-industry rival without the dish stays INDIRECT; nothing is matched
    across currencies or to another dish."""
    from src.ai.market_inputs import competitor_landscape

    tenant, user = _company("Restaurant", "restaurant")
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        for name, price in (("Mansaf", 6.5), ("Shawarma plate", 3.0), ("Fattoush", 2.0)):
            cursor.execute("INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 'JOD');",
                           (tenant, json.dumps({"en": name}), price))
    menu = ("<html><head><title>Menu</title></head><body><ul><li>Mansaf - 7.00 JD</li><li>Chicken Shawerma plate 2.75 JD</li>"
            "<li>Mansaf family tray 45 JD</li><li>Kunafa 2 USD</li></ul>" + "Fresh daily. " * 40 + "</body></html>")
    pages = {"https://reem.jo": "<html><body><a href='/menu'>Our menu</a>" + "Welcome. " * 60 + "</body></html>",
             "https://reem.jo/menu": menu}
    osm = FakeProvider("openstreetmap", [
        _place("Reem Grill", "node/31", website="https://reem.jo"),
        _place("Luna Rossa", "node/32", lat=31.956),
    ])
    summary, listing, run = _run(tenant, user, (osm,), site_reader=lambda url: intel.collect(url, fetch=lambda u: pages.get(u.rstrip("/"))))
    coverage = run["coverage"]
    assert coverage["websites"]["tried"] == 1 and coverage["websites"]["outcomes"] == {"prices_found": 1}
    assert coverage["prices_found"] == 4 and coverage["prices_matched"] == 2 and coverage["products_with_competitor_prices"] == 2
    by_name = {c["name"]: c for c in listing["competitors"]}
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT gc.competitor_name, tc.relationship, tc.is_tracked FROM tenant_competitors tc "
                "JOIN global_competitors gc USING (global_competitor_id) WHERE tc.tenant_id = %s ORDER BY 1;", (tenant,))
            assert cursor.fetchall() == [("Luna Rossa", "INDIRECT", True), ("Reem Grill", "DIRECT", True)]
            cursor.execute(
                """
                SELECT p.product_name->>'en', cpm.competitor_product_sku, cp.scraped_price, cp.currency, cpm.competitor_product_url
                FROM competitor_prices cp JOIN competitor_product_mappings cpm USING (mapping_id)
                JOIN products p ON p.product_id = cpm.product_id WHERE cp.tenant_id = %s ORDER BY 1;
                """,
                (tenant,),
            )
            assert cursor.fetchall() == [("Mansaf", "Mansaf", 7.0, "JOD", "https://reem.jo/menu"),
                                         ("Shawarma plate", "Chicken Shawerma plate", 2.75, "JOD", "https://reem.jo/menu")]
        landscape = competitor_landscape.build_landscape(conn, tenant)
    finally:
        conn.close()
    assert by_name["Reem Grill"]["name"] == "Reem Grill"
    assert landscape["products_covered"] == 2 and landscape["catalog_size"] == 3
