"""
The whole competitor path against a real Postgres through the restricted app
role: a burger restaurant's discovery run keeps burger/pizza places and drops
the donut shop, every kept competitor is scored (category, 0-100 confidence,
evidence), lists can be sorted by confidence, and an owner's explicit
track/untrack choice survives every automatic re-score.
"""
import json
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai import db
from src.ai.market_inputs import discovered_competitors
from src.ai.tests.test_market_discovery_integration_db import FakeProvider, _company, _place, _run
from src.market_scraper.discovery import refresh_tenant_competitors

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test")


def _burger_company():
    tenant, user = _company("Burger restaurant")
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        for name in ("Cheeseburger", "Double Beef Burger", "Chicken Burger", "Fries"):
            cursor.execute("INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s, 5, 'JOD');",
                           (tenant, json.dumps({"en": name})))
    return tenant, user


def _providers():
    return (FakeProvider("openstreetmap", [
        _place("Smash Burger House", "node/1", website="https://smash.example", lat=31.9545, lon=35.911,
               categories=["amenity=fast_food", "cuisine=burger"]),
        _place("Napoli Pizza", "node/2", lat=31.96, lon=35.92, categories=["amenity=fast_food", "cuisine=pizza"]),
        _place("Krispy Donuts", "node/3", lat=31.9541, lon=35.9108, categories=["amenity=cafe", "cuisine=donut"]),
        _place("Joe's Place", "node/4", lat=31.965, lon=35.925, categories=["amenity=restaurant"]),
    ]),)


def _rows(tenant, user, **kw):
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        return {c["name"]: c for c in discovered_competitors.list_competitors(conn, tenant, **kw)["competitors"]}
    finally:
        conn.close()


def test_a_burger_restaurants_run_keeps_its_segment_and_scores_every_competitor():
    tenant, user = _burger_company()
    summary, listing, _run_row = _run(tenant, user, _providers())

    names = {c["name"] for c in listing["competitors"]}
    assert "Krispy Donuts" not in names  # different segment: never listed
    assert {"Smash Burger House", "Napoli Pizza", "Joe's Place"} <= names

    rows = _rows(tenant, user)
    smash, pizza = rows["Smash Burger House"], rows["Napoli Pizza"]
    # scored by the competitor classifier after the run, with the reasons and a category
    assert smash["confidence_score"] is not None and smash["confidence_label"] in ("High", "Medium", "Low")
    assert smash["category"] == "food > snacks > burger" and pizza["category"] == "food > snacks > pizza"
    assert smash["confidence_score"] > pizza["confidence_score"] > rows["Joe's Place"]["confidence_score"]
    assert smash["confidence_reasons"]
    # links and details
    assert smash["website_url"] == "https://smash.example"
    assert smash["maps_url"] == "https://www.google.com/maps/search/?api=1&query=31.9545,35.911"
    assert smash["sources"] and smash["sources"][0]["url"].startswith("https://www.openstreetmap.org/")


def test_the_list_can_be_sorted_by_confidence_best_first():
    tenant, user = _burger_company()
    _run(tenant, user, _providers())
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        ordered = discovered_competitors.list_competitors(conn, tenant, status="all", sort="confidence")["competitors"]
    finally:
        conn.close()
    scores = [c["confidence_score"] for c in ordered if c["is_tracked"]]
    assert scores == sorted(scores, reverse=True) and len(scores) >= 2
    assert ordered[0]["name"] == "Smash Burger House"


def test_an_owner_untracking_a_competitor_is_never_undone_by_a_rescore():
    tenant, user = _burger_company()
    _run(tenant, user, _providers())
    smash = _rows(tenant, user)["Smash Burger House"]
    assert smash["is_tracked"]

    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        assert discovered_competitors.set_tracked(conn, tenant, smash["competitor_id"], False)
        conn.commit()
        refresh_tenant_competitors(conn, tenant)           # what runs after every discovery pass
        _run_again = _run(tenant, user, _providers())      # and a whole new run
    finally:
        conn.close()
    after = _rows(tenant, user)["Smash Burger House"]
    assert after["is_tracked"] is False and after["tracking_decision"] == "USER_UNTRACKED"


def test_an_owner_tracking_a_competitor_keeps_it_even_if_a_rule_would_drop_it():
    tenant, user = _burger_company()
    _run(tenant, user, _providers())
    # the owner adds a donut shop by hand through the track action on a suggestion
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        competitor_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id, "
                       "category_path) VALUES (%s, 'Krispy Donuts', 'https://krispy.example', 'PRIVATE', %s, %s);",
                       (competitor_id, tenant, ["food", "desserts", "donuts"]))
        cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, discovery_method, is_tracked, tier) "
                       "VALUES (%s, %s, 'MAP_LISTING', FALSE, 'CANDIDATE');", (tenant, competitor_id))
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        discovered_competitors.set_tracked(conn, tenant, competitor_id, True)
        conn.commit()
        summary = refresh_tenant_competitors(conn, tenant)
    finally:
        conn.close()
    donut = _rows(tenant, user)["Krispy Donuts"]
    assert donut["is_tracked"] is True and donut["tier"] in ("RELEVANT", "STRATEGIC")
    assert donut["tracking_decision"] == "USER_TRACKED"


def test_a_rescore_never_starts_tracking_a_suggestion_or_changes_its_tier():
    tenant, user = _burger_company()
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        competitor_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id) "
                       "VALUES (%s, 'Napoli Pizza', 'https://napoli.example', 'PRIVATE', %s);", (competitor_id, tenant))
        cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, discovery_method, is_tracked, tier) "
                       "VALUES (%s, %s, 'MAP_LISTING', FALSE, 'CANDIDATE');", (tenant, competitor_id))
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        refresh_tenant_competitors(conn, tenant)
    finally:
        conn.close()
    row = _rows(tenant, user)["Napoli Pizza"]
    assert row["is_tracked"] is False and row["tier"] == "CANDIDATE"      # still just a suggestion
    assert row["confidence_score"] is not None and row["category"] == "food > snacks > pizza"  # but now scored


def test_a_rescore_stops_tracking_a_competitor_the_system_tracked_in_a_different_category():
    tenant, user = _burger_company()
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        competitor_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id, "
                       "category_path) VALUES (%s, 'Krispy Donuts', 'https://krispy.example', 'PRIVATE', %s, %s);",
                       (competitor_id, tenant, ["food", "desserts", "donuts"]))
        cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, discovery_method, is_tracked, tier) "
                       "VALUES (%s, %s, 'MAP_LISTING', TRUE, 'RELEVANT');", (tenant, competitor_id))   # tracked by the system, not the owner
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        summary = refresh_tenant_competitors(conn, tenant)
    finally:
        conn.close()
    assert summary["demoted_to_candidate"] == 1
    donut = _rows(tenant, user)["Krispy Donuts"]
    assert donut["is_tracked"] is False and donut["tier"] == "CANDIDATE"


def test_the_flat_competitors_list_is_alphabetical_by_default_and_confidence_on_request():
    from src.ai.main import app
    client = TestClient(app)
    response = client.post("/auth/signup", json={"full_name": "Owner", "business_name": "Order Co", "email": f"order+{uuid.uuid4().hex[:8]}@example.com",
                                                  "country_code": "JO", "primary_currency": "JOD", "password": "Order!Test-2026"})
    assert response.status_code == 200, response.text
    session = response.json()
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        for name, score, label in (("Aardvark", 20.0, "Low"), ("Zebra", 90.0, "High"), ("Mid", 55.0, "Medium"), ("Unscored", None, None)):
            competitor_id = str(uuid.uuid4())
            cursor.execute("INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id) "
                           "VALUES (%s, %s, 'PRIVATE', %s);", (competitor_id, name, session["tenant_id"]))
            cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, tier, confidence_score, confidence_label) "
                           "VALUES (%s, %s, TRUE, 'RELEVANT', %s, %s);", (session["tenant_id"], competitor_id, score, label))
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    by_confidence = client.get("/competitors?sort=confidence", headers=headers).json()["competitors"]
    assert [c["name"] for c in by_confidence] == ["Zebra", "Mid", "Aardvark", "Unscored"]
    default = client.get("/competitors", headers=headers).json()["competitors"]       # original contract: alphabetical
    assert [c["name"] for c in default] == ["Aardvark", "Mid", "Unscored", "Zebra"]
    assert client.get("/competitors?sort=bogus", headers=headers).status_code == 422


def _suggestions(tenant, names):
    ids = []
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        for i, name in enumerate(names):
            competitor_id = str(uuid.uuid4())
            cursor.execute("INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, "
                           "added_by_tenant_id, latitude, longitude) VALUES (%s, %s, %s, 'PRIVATE', %s, 31.95, 35.91);",
                           (competitor_id, name, f"https://c{i}.example", tenant))
            cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, discovery_method, is_tracked, tier) "
                           "VALUES (%s, %s, 'MAP_LISTING', TRUE, 'RELEVANT');", (tenant, competitor_id))
            ids.append(competitor_id)
    return ids


def test_a_batch_rescore_reads_the_product_catalog_once_not_once_per_competitor():
    from unittest.mock import patch
    from src.ai.pricing import competitor_classification as classification
    tenant, user = _burger_company()
    _suggestions(tenant, ["Alpha Burger", "Beta Pizza", "Gamma Grill", "Delta Kebab"])
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        with patch.object(classification, "_tenant_category_paths", wraps=classification._tenant_category_paths) as spy:
            summary = refresh_tenant_competitors(conn, tenant)
    finally:
        conn.close()
    assert summary["reclassified"] == 4
    assert spy.call_count == 1


def test_the_dashboard_directory_carries_the_map_link_and_the_owners_choice():
    from src.ai.dashboard.competitors import get_competitor_directory
    tenant, user = _burger_company()
    (competitor_id,) = _suggestions(tenant, ["Alpha Burger"])
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        directory = get_competitor_directory(conn, tenant)
    finally:
        conn.close()
    row = (directory["strategic"] + directory["relevant"])[0]
    assert row["maps_url"] == "https://www.google.com/maps/search/?api=1&query=31.95,35.91"
    assert row["tracking_decision"] is None


def test_a_competitor_the_owner_tracked_is_recorded_as_confirmed():
    tenant, user = _burger_company()
    (competitor_id,) = _suggestions(tenant, ["Krispy Donuts"])
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        cursor.execute("UPDATE global_competitors SET category_path = %s WHERE global_competitor_id = %s;",
                       (["food", "desserts", "donuts"], competitor_id))
        cursor.execute("UPDATE tenant_competitors SET tracking_decision = 'USER_TRACKED' WHERE global_competitor_id = %s;", (competitor_id,))
    conn = db.dedicated_tenant_connection(tenant, user)
    try:
        refresh_tenant_competitors(conn, tenant)
        with conn.cursor() as cursor:
            cursor.execute("SELECT is_tracked, is_confirmed_competitor FROM tenant_competitors WHERE global_competitor_id = %s;", (competitor_id,))
            assert cursor.fetchone() == (True, True)
    finally:
        conn.close()
