"""Price changes on a competitor's own items and the owner's corrections of product matches, on a real Postgres through the
restricted app role. Skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD are set."""
import os
import time
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test")

from src.ai import db  # noqa: E402
from src.ai.market_inputs import competitor_intel, intel_review, price_history, product_matches  # noqa: E402
from src.ai.tests.test_intel_review_integration_db import MENU, OFFERS, HOME, _collect, _setup  # noqa: E402
from src.market_scraper.market_discovery import offerings  # noqa: E402

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _facts(**prices):
    return [{"kind": "product", "name": name.replace("_", " "), "price": price, "currency": "JOD", "confidence": 0.9,
             "source_url": "https://habibah.jo/menu"} for name, price in prices.items()]


def _conn_for(tenant, user):
    return db.dedicated_tenant_connection(tenant, user)


def test_a_moved_price_is_recorded_once_and_an_unchanged_one_only_extends_its_row():
    tenant, user, cid = _setup()
    conn = _conn_for(tenant, user)
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM competitor_price_history WHERE tenant_id = %s;", (tenant,))  # start after discovery's own read
        first = price_history.record(conn, tenant, cid, _facts(Mansaf=8.5, Tea=0.75), observed_at=T0)
        assert first == {"new_items": 2, "changes": 0, "unchanged": 0, "ambiguous": 0}
        again = price_history.record(conn, tenant, cid, _facts(Mansaf=8.5, Tea=0.75), observed_at=T0 + timedelta(days=1))
        assert again["unchanged"] == 2 and again["changes"] == 0
        moved = price_history.record(conn, tenant, cid, _facts(Mansaf=9.5, Tea=0.75), observed_at=T0 + timedelta(days=2))
        assert moved["changes"] == 1 and moved["unchanged"] == 1
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM competitor_price_history WHERE tenant_id = %s AND global_competitor_id = %s;", (tenant, cid))
            assert cursor.fetchone()[0] == 3  # Mansaf twice (8.5 then 9.5), Tea once
        changes = price_history.list_changes(conn, tenant, cid, days=60, now=T0 + timedelta(days=3))
        assert len(changes) == 1
        change = changes[0]
        assert (change["item"], change["old_price"], change["new_price"], change["direction"], change["change_pct"]) == ("Mansaf", 8.5, 9.5, "up", 11.8)
        assert change["reliable"] is True and change["currency"] == "JOD" and change["competitor"] == "Habibah Sweets"
        # Outside the window nothing is listed; the series shows both prices oldest first.
        assert price_history.list_changes(conn, tenant, cid, days=1, now=T0 + timedelta(days=30)) == []
        series = price_history.item_series(conn, tenant, cid, change["item_key"])
        assert [p["price"] for p in series] == [8.5, 9.5]
    finally:
        conn.rollback()
        conn.close()


def test_weak_reads_are_listed_only_on_request_and_a_confirmation_makes_them_count():
    tenant, user, cid = _setup()
    conn = _conn_for(tenant, user)
    try:
        weak = lambda price: [{"kind": "product", "name": "Labneh jar", "price": price, "currency": "JOD", "confidence": 0.5,  # noqa: E731
                               "extracted_by": "ocr", "source_url": "https://habibah.jo/menu.jpg"}]
        price_history.record(conn, tenant, cid, weak(3.0), observed_at=T0)
        price_history.record(conn, tenant, cid, weak(2.0), observed_at=T0 + timedelta(days=1))
        now = T0 + timedelta(days=2)
        assert price_history.list_changes(conn, tenant, cid, 30, now=now) == []
        listed = price_history.list_changes(conn, tenant, cid, 30, include_unreliable=True, now=now)
        assert len(listed) == 1 and listed[0]["reliable"] is False and listed[0]["origin"] == "ocr"
        assert price_history.alert_changes(conn, tenant, 30, 3.0, now=now) == []
        key = intel_review.name_key("Labneh jar")
        price_history.mark_verified(conn, tenant, cid, key, 3.0)
        price_history.mark_verified(conn, tenant, cid, key, 2.0)
        counted = price_history.list_changes(conn, tenant, cid, 30, now=now)
        assert len(counted) == 1 and counted[0]["reliable"] is True and counted[0]["verified"] is True
        assert [a["item"] for a in price_history.alert_changes(conn, tenant, 30, 3.0, now=now)] == ["Labneh jar"]
    finally:
        conn.rollback()
        conn.close()


def test_two_prices_for_one_item_in_one_read_are_ambiguous_and_a_rejected_read_is_not_recorded():
    tenant, user, cid = _setup()
    conn = _conn_for(tenant, user)
    try:
        conflict = _facts(Kunafa=3.5) + _facts(Kunafa=3.25)
        assert price_history.record(conn, tenant, cid, conflict, observed_at=T0)["ambiguous"] == 1
        key = intel_review.name_key("Cake")
        from decimal import Decimal
        rejected = {(key, Decimal("2.0000")): {"verdict": "REJECTED"}}
        assert price_history.record(conn, tenant, cid, _facts(Cake=2.0), rejected, observed_at=T0)["new_items"] == 0
    finally:
        conn.rollback()
        conn.close()


def test_a_site_read_feeds_the_history_and_the_owner_correction_is_not_mistaken_for_a_competitor_change():
    tenant, user, cid = _setup()
    conn = _conn_for(tenant, user)
    try:
        found = competitor_intel.get_intel(conn, tenant, cid)
        fact = next(p for p in found["products"] if p["name"] == "Kunafa Khishneh")
        intel_review.review_fact(conn, tenant, cid, fact["intel_id"], "CORRECTED", user, corrected_price=3.9, currency="JOD")
        conn.commit()
        competitor_intel.refresh_competitor(conn, tenant, cid, collect=_collect({"https://habibah.jo": HOME, "https://habibah.jo/menu": MENU,
                                                                                  "https://habibah.jo/offers": OFFERS}))
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute("SELECT price FROM competitor_price_history WHERE tenant_id = %s AND global_competitor_id = %s AND name_key = %s ORDER BY first_seen_at;",
                           (tenant, cid, intel_review.name_key("Kunafa Khishneh")))
            assert [float(r[0]) for r in cursor.fetchall()] == [3.75]  # what the site shows - never the owner's 3.9
        assert price_history.list_changes(conn, tenant, cid, 365) == []
        # The site really moves the price: that is one change, from 3.75.
        changed = MENU.replace('"price":"3.75"', '"price":"4.10"')
        competitor_intel.refresh_competitor(conn, tenant, cid, collect=_collect({"https://habibah.jo": HOME, "https://habibah.jo/menu": changed,
                                                                                  "https://habibah.jo/offers": OFFERS}))
        conn.commit()
        changes = price_history.list_changes(conn, tenant, cid, 365)
        assert [(c["item"], c["old_price"], c["new_price"]) for c in changes] == [("Kunafa Khishneh", 3.75, 4.1)]
    finally:
        conn.close()


def test_reading_a_site_still_works_when_the_history_table_is_not_deployed_yet():
    tenant, user, cid = _setup()
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        cursor.execute("ALTER TABLE competitor_price_history RENAME TO competitor_price_history_off;")
    try:
        conn = _conn_for(tenant, user)
        try:
            outcome = competitor_intel.refresh_competitor(conn, tenant, cid, collect=_collect({"https://habibah.jo": HOME, "https://habibah.jo/menu": MENU}))
            conn.commit()  # a poisoned transaction would fail here
            assert outcome["status"] == "prices_found"
            assert price_history.list_changes(conn, tenant, cid, 30) == []
        finally:
            conn.close()
    finally:
        with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
            cursor.execute("ALTER TABLE competitor_price_history_off RENAME TO competitor_price_history;")


def test_history_is_private_to_the_company():
    tenant, user, cid = _setup()
    other, other_user, _other_cid = _setup()
    conn = _conn_for(tenant, user)
    try:
        price_history.record(conn, tenant, cid, _facts(Mansaf=8.5), observed_at=T0)
        price_history.record(conn, tenant, cid, _facts(Mansaf=9.5), observed_at=T0 + timedelta(days=1))
        conn.commit()
    finally:
        conn.close()
    conn = _conn_for(other, other_user)
    try:
        assert price_history.list_changes(conn, other, None, 365) == []
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM competitor_price_history WHERE global_competitor_id = %s;", (cid,))
            assert cursor.fetchone()[0] == 0
    finally:
        conn.close()


# ---- product matches --------------------------------------------------------------------------

def _products(tenant, **names):
    ids = {}
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        for name, price in names.items():
            cursor.execute("INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s::jsonb, %s, 'JOD') RETURNING product_id;",
                           (tenant, '{"en": "%s"}' % name.replace("_", " "), price))
            ids[name] = str(cursor.fetchone()[0])
    return ids


def _item(conn, tenant, cid, name):
    return next(p for p in competitor_intel.get_intel(conn, tenant, cid)["products"] if p["name"] == name)


def test_a_wrong_match_can_be_rejected_replaced_chosen_and_reset_and_the_decisions_survive_re_reads():
    tenant, user, cid = _setup()
    ids = _products(tenant, Kunafa_Nabulsieh=3.5)
    conn = _conn_for(tenant, user)
    try:
        offerings.record_matches(conn, tenant, cid, offerings.company_products(conn, tenant), with_aliases=False)
        conn.commit()
        listing = product_matches.list_matches(conn, tenant, cid)
        assert [(m["product"], m["item"]) for m in listing["matches"]] == [("Kunafa Nabulsieh", "Kunafa Nabulsieh")]
        assert any(i["name"] == "Kunafa Khishneh" for i in listing["items"])

        # "Not this item": the mapping goes off and the item is never offered to this product again.
        rejected = product_matches.reject_match(conn, tenant, cid, ids["Kunafa_Nabulsieh"], user)
        conn.commit()
        assert rejected["rejected_item"] == "Kunafa Nabulsieh"
        after = product_matches.list_matches(conn, tenant, cid)
        assert all(m["item"] != "Kunafa Nabulsieh" for m in after["matches"])
        assert [r["item"] for r in after["rejected"]] == ["Kunafa Nabulsieh"]
        offerings.record_matches(conn, tenant, cid, offerings.company_products(conn, tenant), with_aliases=False)
        conn.commit()
        assert all(m["item"] != "Kunafa Nabulsieh" for m in product_matches.list_matches(conn, tenant, cid)["matches"])  # survives a re-match pass

        # The owner chooses the right item.
        khishneh = _item(conn, tenant, cid, "Kunafa Khishneh")
        chosen = product_matches.choose_match(conn, tenant, cid, ids["Kunafa_Nabulsieh"], khishneh["intel_id"], user)
        conn.commit()
        assert chosen["new_match"]["item"] == "Kunafa Khishneh" and chosen["new_match"]["owner_chosen"] is True
        match = product_matches.list_matches(conn, tenant, cid)["matches"][0]
        assert (match["item"], match["owner_chosen"], match["their_price"]) == ("Kunafa Khishneh", True, 3.75)
        competitor_intel.refresh_competitor(conn, tenant, cid, collect=_collect({"https://habibah.jo": HOME, "https://habibah.jo/menu": MENU, "https://habibah.jo/offers": OFFERS}))
        conn.commit()
        assert product_matches.list_matches(conn, tenant, cid)["matches"][0]["item"] == "Kunafa Khishneh"  # the choice survives a re-read

        # Back to automatic: the choice and the rejection are gone and the best item matches again.
        cleared = product_matches.clear_match(conn, tenant, cid, ids["Kunafa_Nabulsieh"])
        conn.commit()
        assert cleared["cleared"] == 2 and cleared["new_match"]["item"] == "Kunafa Nabulsieh"
    finally:
        conn.close()


def test_a_choice_must_be_a_priced_item_in_the_products_currency_and_an_unconfirmed_post_price_needs_confirming_first():
    tenant, user, cid = _setup()
    ids = _products(tenant, Mansaf=18.0)
    conn = _conn_for(tenant, user)
    try:
        competitor_intel.save_channel_facts(conn, tenant, cid, "instagram", [
            {"kind": "product", "name": "Mansaf tray", "price": 18.0, "currency": "JOD", "confidence": 0.5, "channel": "instagram",
             "extracted_by": "caption", "source_url": "https://www.instagram.com/p/A/", "retrieved_at": "2026-10-19T10:00:00+00:00"},
            {"kind": "product", "name": "Mansaf USD", "price": 25.0, "currency": "USD", "confidence": 0.9, "channel": "instagram",
             "extracted_by": "caption", "source_url": "https://www.instagram.com/p/B/", "retrieved_at": "2026-10-19T10:00:00+00:00"}])
        conn.commit()
        tray, usd = _item(conn, tenant, cid, "Mansaf tray"), _item(conn, tenant, cid, "Mansaf USD")
        with pytest.raises(product_matches.MatchError, match="confirm this price first"):
            product_matches.choose_match(conn, tenant, cid, ids["Mansaf"], tray["intel_id"], user)
        with pytest.raises(product_matches.MatchError, match="another currency"):
            product_matches.choose_match(conn, tenant, cid, ids["Mansaf"], usd["intel_id"], user)
        intel_review.review_fact(conn, tenant, cid, tray["intel_id"], "CONFIRMED", user)
        result = product_matches.choose_match(conn, tenant, cid, ids["Mansaf"], tray["intel_id"], user)
        conn.commit()
        assert result["new_match"]["item"] == "Mansaf tray"
        with pytest.raises(LookupError):
            product_matches.choose_match(conn, tenant, cid, "00000000-0000-0000-0000-000000000001", tray["intel_id"], user)
    finally:
        conn.close()


def test_match_decisions_are_private_to_the_company():
    tenant, user, cid = _setup()
    other, other_user, _ = _setup()
    ids = _products(tenant, Kunafa_Nabulsieh=3.5)
    conn = _conn_for(tenant, user)
    try:
        offerings.record_matches(conn, tenant, cid, offerings.company_products(conn, tenant), with_aliases=False)
        product_matches.reject_match(conn, tenant, cid, ids["Kunafa_Nabulsieh"], user)
        conn.commit()
    finally:
        conn.close()
    conn = _conn_for(other, other_user)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM competitor_match_override;")
            assert cursor.fetchone()[0] == 0
        with pytest.raises(LookupError):
            product_matches.reject_match(conn, other, cid, ids["Kunafa_Nabulsieh"], other_user)
    finally:
        conn.close()


def test_the_read_endpoints_return_changes_series_and_matches_and_404_for_an_unknown_competitor():
    import jwt
    from fastapi.testclient import TestClient

    from src.ai.main import app
    tenant, user, cid = _setup()
    conn = _conn_for(tenant, user)
    try:
        price_history.record(conn, tenant, cid, _facts(Mansaf=8.5), observed_at=datetime.now(timezone.utc) - timedelta(days=3))
        price_history.record(conn, tenant, cid, _facts(Mansaf=7.5), observed_at=datetime.now(timezone.utc) - timedelta(days=1))
        conn.commit()
    finally:
        conn.close()
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + jwt.encode({"tenant_id": tenant, "user_id": user, "exp": int(time.time()) + 3600}, os.environ["JWT_SECRET"], algorithm="HS256")}
    body = client.get(f"/discovery/competitors/{cid}/price-changes", headers=headers).json()
    assert [(c["item"], c["direction"], c["change_pct"]) for c in body["changes"]] == [("Mansaf", "down", -11.8)]
    feed = client.get("/discovery/price-changes", headers=headers).json()
    assert [c["item"] for c in feed["changes"]] == ["Mansaf"]
    key = body["changes"][0]["item_key"]
    series = client.get(f"/discovery/competitors/{cid}/price-history", params={"item_key": key}, headers=headers).json()["series"]
    assert [p["price"] for p in series] == [8.5, 7.5]
    assert "matches" in client.get(f"/discovery/competitors/{cid}/matches", headers=headers).json()
    unknown = "00000000-0000-0000-0000-0000000000aa"
    assert client.get(f"/discovery/competitors/{unknown}/price-changes", headers=headers).status_code == 404
    assert client.get(f"/discovery/competitors/{unknown}/matches", headers=headers).status_code == 404
    # A change in the alerts list (not matched to one of your products): the bell shows it.
    from src.ai import alerts
    conn = _conn_for(tenant, user)
    try:
        kinds = [a["kind"] for a in alerts.build_alerts(conn, tenant)]
    finally:
        conn.close()
    assert "competitor_item_price" in kinds
