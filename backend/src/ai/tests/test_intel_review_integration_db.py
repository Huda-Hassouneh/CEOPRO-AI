"""Owner verification of website prices on a real Postgres, through the
restricted app role: a decision survives a re-read, never vouches for a
changed price, and is private to the company. Skipped unless
AI_TEST_DATABASE_URL and APP_DB_PASSWORD are set."""
import os

import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test")

from src.ai import db  # noqa: E402
from src.ai.market_inputs import competitor_intel, intel_review  # noqa: E402
from src.ai.tests.test_competitor_intel import HOME, MENU, OFFERS  # noqa: E402
from src.ai.tests.test_market_discovery_integration_db import FakeProvider, _company, _place, _run  # noqa: E402
from src.market_scraper.market_discovery import intel  # noqa: E402

PAGES = {"https://habibah.jo": HOME, "https://habibah.jo/menu": MENU, "https://habibah.jo/offers": OFFERS}


def _collect(pages):
    return lambda url, **kwargs: intel.collect(url, fetch=lambda u: pages.get(u.rstrip("/")))


def _setup():
    tenant, user = _company("Bakery", "bakery")
    osm = FakeProvider("openstreetmap", [_place("Habibah Sweets", "node/9", industry="bakery", website="https://habibah.jo")])
    _summary, listing, _run_row = _run(tenant, user, (osm,), site_reader=_collect(PAGES))
    return tenant, user, listing["competitors"][0]["competitor_id"]


def _fact(found, name, price=None):
    return next(p for p in found["products"] if p["name"] == name and (price is None or p.get("read_price", p["price"]) == price))


def test_decisions_survive_a_reread_and_never_vouch_for_a_changed_price():
    tenant, user, competitor_id = _setup()
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        found = competitor_intel.get_intel(conn, tenant, competitor_id)
        khishneh, baklava, maamoul = (_fact(found, "Kunafa Khishneh"), _fact(found, "Baklava box (1 kg)"), _fact(found, "معمول بالتمر"))
        assert khishneh["intel_id"] and not khishneh.get("verified")

        intel_review.review_fact(conn, tenant, competitor_id, khishneh["intel_id"], "CONFIRMED", user)
        result = intel_review.review_fact(conn, tenant, competitor_id, baklava["intel_id"], "CORRECTED", user,
                                          corrected_price=11.5, currency="jod", note="menu board in store")
        intel_review.review_fact(conn, tenant, competitor_id, maamoul["intel_id"], "REJECTED", user)
        conn.commit()
        assert result["price"] == 11.5 and result["read_price"] == 12.0

        found = competitor_intel.get_intel(conn, tenant, competitor_id)
        assert _fact(found, "Kunafa Khishneh")["verified"] is True and _fact(found, "Kunafa Khishneh")["confidence"] == 1.0
        corrected = _fact(found, "Baklava box (1 kg)")
        assert corrected["price"] == 11.5 and corrected["read_price"] == 12.0 and corrected["currency"] == "JOD"
        assert not any(p["name"] == "معمول بالتمر" for p in found["products"])

        # The site is read again, unchanged: the same decisions apply to the fresh rows.
        competitor_intel.refresh_competitor(conn, tenant, competitor_id, collect=_collect(PAGES))
        conn.commit()
        found = competitor_intel.get_intel(conn, tenant, competitor_id)
        assert _fact(found, "Kunafa Khishneh")["verified"] is True
        assert _fact(found, "Baklava box (1 kg)")["price"] == 11.5
        assert not any(p["name"] == "معمول بالتمر" for p in found["products"])

        # The site now shows another price for the confirmed item: that price is new and unreviewed.
        changed = {**PAGES, "https://habibah.jo/menu": MENU.replace('"price":"3.75"', '"price":"4.10"')}
        competitor_intel.refresh_competitor(conn, tenant, competitor_id, collect=_collect(changed))
        conn.commit()
        found = competitor_intel.get_intel(conn, tenant, competitor_id)
        new = _fact(found, "Kunafa Khishneh")
        assert new["price"] == 4.1 and not new.get("verified") and new["confidence"] < 1.0

        # Withdrawing a decision: the next read shows the fact as read.
        assert intel_review.clear_review(conn, tenant, competitor_id, _fact(found, "Baklava box (1 kg)")["intel_id"]) is True
        competitor_intel.refresh_competitor(conn, tenant, competitor_id, collect=_collect(PAGES))
        conn.commit()
        assert _fact(competitor_intel.get_intel(conn, tenant, competitor_id), "Baklava box (1 kg)")["price"] == 12.0
    finally:
        conn.close()


def test_a_decision_needs_a_priced_product_and_valid_input():
    tenant, user, competitor_id = _setup()
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        found = competitor_intel.get_intel(conn, tenant, competitor_id)
        fact = _fact(found, "Kunafa Khishneh")
        with pytest.raises(intel_review.ReviewError):
            intel_review.review_fact(conn, tenant, competitor_id, fact["intel_id"], "CORRECTED", user)
        with pytest.raises(intel_review.ReviewError):
            intel_review.review_fact(conn, tenant, competitor_id, fact["intel_id"], "CONFIRMED", user, corrected_price=3)
        with pytest.raises(intel_review.ReviewError):
            intel_review.review_fact(conn, tenant, competitor_id, fact["intel_id"], "MAYBE", user)
        promo = found["promotions"][0]
        with pytest.raises(LookupError):  # a promotion is not a product fact
            intel_review.review_fact(conn, tenant, competitor_id, promo["intel_id"], "CONFIRMED", user)
    finally:
        conn.close()


def test_decisions_are_private_to_the_company():
    tenant, user, competitor_id = _setup()
    other, other_user = _company("Bakery", "bakery")
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        fact = _fact(competitor_intel.get_intel(conn, tenant, competitor_id), "Kunafa Khishneh")
        intel_review.review_fact(conn, tenant, competitor_id, fact["intel_id"], "CONFIRMED", user)
        conn.commit()
    finally:
        conn.close()
    conn = db.dedicated_tenant_connection(other, other_user)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM competitor_intel_review;")
            assert cursor.fetchone()[0] == 0
        with pytest.raises(LookupError):  # another company's fact id is simply not found
            intel_review.review_fact(conn, other, competitor_id, fact["intel_id"], "REJECTED", other_user)
    finally:
        conn.close()
