"""
Integration tests for the price comparison ladder (market_scraper/price_comparison/engine.py +
ai/pricing/comparisons.py + pricing/data_access.load_comparable_prices) against a real PostgreSQL instance
with migration 20261024000000 applied. Same convention as every other live-DB test here: skipped unless
AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.ai.pricing import comparisons, data_access
from src.market_scraper.price_comparison import engine

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _product(conn, tenant_id, name, price) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), price),
        )
    return product_id


def _competitor(conn, tenant_id, name, items, tracked=True) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, FALSE);",
            (competitor_id, name, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, %s);",
            (tenant_id, competitor_id, tracked),
        )
        for item_name, price in items:
            cursor.execute(
                "INSERT INTO competitor_intel (tenant_id, global_competitor_id, kind, payload, source_url, confidence) "
                "VALUES (%s, %s, 'product', %s, 'https://rival.example/menu', 0.9);",
                (tenant_id, competitor_id, json.dumps({"name": item_name, "type": "product", "price": price, "currency": "JOD"})),
            )
    return competitor_id


def test_the_brief_examples_end_to_end(conn):
    tenant_id = _company(conn)
    exact = _product(conn, tenant_id, "Cheese burger", 3.5)
    similar = _product(conn, tenant_id, "Small beef burger", 2.5)
    added = _product(conn, tenant_id, "Extra cheese burger", 4.0)
    equivalent = _product(conn, tenant_id, "1 hour class", 10.0)
    _competitor(conn, tenant_id, "Rival Grill", [("Cheese burger", 3.0)])
    _competitor(conn, tenant_id, "Rival Language Centre", [("30 min class", 5.0)])
    conn.commit()

    totals = engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()
    assert totals["competitors"] == 2

    ladders = comparisons.get_ladders(conn, tenant_id, [exact, similar, added, equivalent])
    assert ladders[exact]["headline"]["tier"] == "EXACT"
    assert ladders[similar]["headline"]["tier"] == "SIMILAR"
    assert ladders[added]["headline"]["tier"] == "ADDED_VALUE"
    assert ladders[added]["tiers"]["ADDED_VALUE"]["items"][0]["premium"]["premium_pct"] == pytest.approx(33.3)
    assert ladders[equivalent]["headline"]["tier"] == "EQUIVALENT"
    assert ladders[equivalent]["tiers"]["EQUIVALENT"]["items"][0]["comparable_price"] == pytest.approx(10.0)
    assert ladders[equivalent]["tiers"]["EQUIVALENT"]["items"][0]["scale_factor"] == pytest.approx(2.0)


def test_refresh_replaces_a_competitors_rows_when_an_item_disappears(conn):
    tenant_id = _company(conn)
    product_id = _product(conn, tenant_id, "Cheese burger", 3.5)
    competitor_id = _competitor(conn, tenant_id, "Rival Grill", [("Cheese burger", 3.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()
    assert comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]["covered"] is True

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM competitor_intel WHERE tenant_id = %s AND global_competitor_id = %s;", (tenant_id, competitor_id))
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)  # no items left for this competitor: nothing to recompute
    conn.commit()
    result = engine.refresh_for_competitor(conn, tenant_id, competitor_id, [{"product_id": product_id, "name": "Cheese burger",
                                                                              "name_alt": None, "price": 3.5, "currency": "JOD"}])
    conn.commit()
    assert result["rows"] == 0
    assert comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]["covered"] is False


def test_untracked_competitors_and_other_tenants_never_appear(conn):
    tenant_id, other_tenant = _company(conn), _company(conn)
    product_id = _product(conn, tenant_id, "Cheese burger", 3.5)
    _competitor(conn, tenant_id, "Untracked Grill", [("Cheese burger", 3.0)], tracked=False)
    _competitor(conn, other_tenant, "Other Tenant Grill", [("Cheese burger", 3.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)
    engine.refresh_for_tenant(conn, other_tenant)
    conn.commit()

    ladder = comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]
    assert ladder["covered"] is False
    assert comparisons.get_ladders(conn, other_tenant, [product_id]) == {}  # not the other tenant's product


def test_comparable_prices_feed_the_recommendation_but_added_value_does_not(conn):
    tenant_id = _company(conn)
    equivalent = _product(conn, tenant_id, "1 hour class", 10.0)
    added = _product(conn, tenant_id, "30 min class with conversation", 7.0)
    _competitor(conn, tenant_id, "Rival Language Centre", [("30 min class", 5.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()

    rows = data_access.load_comparable_prices(conn, tenant_id, equivalent, "JOD")
    assert [(r["tier"], r["price_found"]) for r in rows] == [("EQUIVALENT", 10.0)]
    assert data_access.load_comparable_prices(conn, tenant_id, added, "JOD") == []


def test_a_richer_product_is_never_pulled_down_toward_leaner_similar_items(conn):
    # Found in a browser check: "Extra cheese burger" was recommended a cut toward a plain burger and a beef burger.
    tenant_id = _company(conn)
    richer = _product(conn, tenant_id, "Extra cheese burger", 4.0)
    swap = _product(conn, tenant_id, "Chicken burger", 3.5)
    _competitor(conn, tenant_id, "Burger House", [("Cheese burger", 3.2), ("Beef burger", 3.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()

    assert data_access.load_comparable_prices(conn, tenant_id, richer, "JOD") == []
    # A like-for-like variant swap (same size, same richness) is a fair stand-in.
    swap_rows = data_access.load_comparable_prices(conn, tenant_id, swap, "JOD")
    assert swap_rows and all(r["tier"] == "SIMILAR" for r in swap_rows)
    ladders = comparisons.get_ladders(conn, tenant_id, [richer])
    assert ladders[richer]["headline"]["tier"] == "ADDED_VALUE"


def test_deleting_a_product_removes_its_comparisons(conn):
    tenant_id = _company(conn)
    product_id = _product(conn, tenant_id, "Cheese burger", 3.5)
    _competitor(conn, tenant_id, "Rival Grill", [("Cheese burger", 3.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM products WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        cursor.execute("SELECT COUNT(*) FROM product_price_comparisons WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 0


def test_unsettled_extra_words_stay_out_of_recommendations_until_judged(conn):
    tenant_id = _company(conn)
    product_id = _product(conn, tenant_id, "Conversation class 30 min", 7.0)
    _competitor(conn, tenant_id, "Rival Language Centre", [("30 min class", 5.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)  # no judge: unsettled
    conn.commit()
    ladder = comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]
    assert ladder["tiers"]["SIMILAR"]["count"] == 1
    assert data_access.load_comparable_prices(conn, tenant_id, product_id, "JOD") == []

    engine.refresh_for_tenant(conn, tenant_id, judge=lambda *a: "addition")  # the model settles it
    conn.commit()
    ladder = comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]
    assert ladder["tiers"]["ADDED_VALUE"]["count"] == 1
    assert ladder["tiers"]["ADDED_VALUE"]["items"][0]["method"] == "AI_ASSISTED"


def test_owner_decisions_survive_a_recompute_and_clearing_restores_the_system_reading(conn):
    tenant_id = _company(conn)
    product_id = _product(conn, tenant_id, "Chicken burger", 3.5)
    competitor_id = _competitor(conn, tenant_id, "Burger House", [("Beef burger", 3.0)])
    conn.commit()
    key = engine.name_key("Beef burger")

    def decide(verdict):
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM product_price_comparison_overrides WHERE tenant_id = %s;", (tenant_id,))
            if verdict:
                cursor.execute(
                    "INSERT INTO product_price_comparison_overrides (tenant_id, product_id, global_competitor_id, name_key, verdict) "
                    "VALUES (%s, %s, %s, %s, %s);", (tenant_id, product_id, competitor_id, key, verdict))
        engine.refresh_for_tenant(conn, tenant_id)
        conn.commit()
        return comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]

    assert decide(None)["tiers"]["SIMILAR"]["count"] == 1
    owner = decide("ADDITION")
    assert owner["tiers"]["ADDED_VALUE"]["count"] == 1 and owner["tiers"]["ADDED_VALUE"]["items"][0]["method"] == "OWNER"
    assert owner["tiers"]["SIMILAR"]["count"] == 0
    assert decide("NOT_COMPARABLE")["covered"] is False
    assert decide(None)["tiers"]["SIMILAR"]["count"] == 1


def test_an_ai_verdict_survives_a_recompute_that_has_no_model(conn):
    tenant_id = _company(conn)
    product_id = _product(conn, tenant_id, "Conversation class 30 min", 7.0)
    _competitor(conn, tenant_id, "Rival Language Centre", [("30 min class", 5.0)])
    conn.commit()
    asked = []
    engine.refresh_for_tenant(conn, tenant_id, judge=lambda *a: asked.append(a) or "addition")
    conn.commit()
    assert len(asked) == 1
    totals = engine.refresh_for_tenant(conn, tenant_id)  # request path: no model, earlier answer reused
    conn.commit()
    assert totals["unsettled"] == 0 and len(asked) == 1
    ladder = comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]
    assert ladder["tiers"]["ADDED_VALUE"]["count"] == 1 and ladder["tiers"]["ADDED_VALUE"]["items"][0]["method"] == "AI_ASSISTED"


def test_rejecting_a_scraped_price_also_retracts_the_exact_price_recorded_from_it(conn):
    # Found while testing: the rejected price stayed in competitor_prices and kept showing as an exact match
    # (and kept feeding recommendations) after the owner threw it out.
    from src.ai.market_inputs import intel_review
    from src.market_scraper.market_discovery import offerings

    tenant_id = _company(conn)
    product_id = _product(conn, tenant_id, "Cheese burger", 3.5)
    competitor_id = _competitor(conn, tenant_id, "Rival Grill", [("Cheese burger", 3.0)])
    user_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'x');", (user_id, f"{user_id[:8]}@e.test"))
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');", (tenant_id, user_id))
        cursor.execute("SELECT intel_id FROM competitor_intel WHERE tenant_id = %s;", (tenant_id,))
        intel_id = str(cursor.fetchone()[0])
    offerings.record_matches(conn, tenant_id, competitor_id, offerings.company_products(conn, tenant_id), with_aliases=False)
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()
    assert comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]["tiers"]["EXACT"]["count"] == 1
    assert data_access.load_competitor_prices(conn, tenant_id, product_id, "JOD")

    intel_review.review_fact(conn, tenant_id, competitor_id, intel_id, "REJECTED", user_id)
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()
    assert comparisons.get_ladders(conn, tenant_id, [product_id])[product_id]["covered"] is False
    assert data_access.load_competitor_prices(conn, tenant_id, product_id, "JOD") == []


def test_category_premium_band_is_observed_from_the_tenants_own_added_value_pairs(conn):
    tenant_id = _company(conn)
    ids = [_product(conn, tenant_id, "Extra cheese burger", price) for price in (3.6, 3.9, 4.2, 4.5, 4.8, 5.1)]
    lone = _product(conn, tenant_id, "Extra cheese pizza", 9.0)
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET category = %s WHERE tenant_id = %s AND product_id = ANY(%s::uuid[]);",
                       (json.dumps({"en": "Burgers"}), tenant_id, ids))
        cursor.execute("UPDATE products SET category = %s WHERE tenant_id = %s AND product_id = %s;",
                       (json.dumps({"en": "Pizza"}), tenant_id, lone))
    _competitor(conn, tenant_id, "Rival Grill", [("Cheese burger", 3.0), ("Cheese pizza", 6.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()

    bands = comparisons.load_category_bands(conn, tenant_id)
    assert bands["burgers"] == {"band_pct": 57.5, "source": "observed", "samples": 6}
    assert bands["pizza"]["source"] == "default" and bands["pizza"]["samples"] == 1  # too few pairs to trust

    ladder = comparisons.get_ladders(conn, tenant_id, [ids[0], lone])
    assert ladder[ids[0]]["premium_band"]["source"] == "observed"
    assert ladder[ids[0]]["added_value_guidance"]["band_pct"] == 57.5
    assert ladder[lone]["added_value_guidance"]["band_source"] == "default"
    lines = comparisons.overview_lines(conn, tenant_id)
    assert lines and "reference, never an exact competitor price" in lines[0] and any("Extra cheese pizza" in l for l in lines)


def test_an_owner_set_band_wins_over_the_observed_one_and_clearing_it_restores_it(conn):
    tenant_id = _company(conn)
    ids = [_product(conn, tenant_id, "Extra cheese burger", price) for price in (3.6, 3.9, 4.2, 4.5, 4.8, 5.1)]
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET category = %s WHERE tenant_id = %s;", (json.dumps({"en": "Burgers"}), tenant_id))
    _competitor(conn, tenant_id, "Rival Grill", [("Cheese burger", 3.0)])
    conn.commit()
    engine.refresh_for_tenant(conn, tenant_id)
    conn.commit()
    assert comparisons.load_category_bands(conn, tenant_id)["burgers"]["source"] == "observed"

    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO price_premium_band_overrides (tenant_id, category_key, band_pct) VALUES (%s, 'burgers', 25);", (tenant_id,))
    conn.commit()
    assert comparisons.load_category_bands(conn, tenant_id)["burgers"] == {"band_pct": 25.0, "source": "owner", "samples": 6}
    ladder = comparisons.get_ladders(conn, tenant_id, [ids[0]])[ids[0]]
    assert ladder["category"] == "burgers" and ladder["premium_band"]["source"] == "owner"
    assert ladder["added_value_guidance"]["band_source"] == "owner"
    assert ladder["tiers"]["ADDED_VALUE"]["items"][0]["premium"]["status"] == "within_range"  # 3.6 vs 3.0 is +20 %, inside 25 %
    top = comparisons.get_ladders(conn, tenant_id, [ids[-1]])[ids[-1]]  # 5.1 vs 3.0 is +70 %, past 25 %
    assert top["tiers"]["ADDED_VALUE"]["items"][0]["premium"]["status"] == "above_range"

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM price_premium_band_overrides WHERE tenant_id = %s;", (tenant_id,))
    conn.commit()
    assert comparisons.load_category_bands(conn, tenant_id)["burgers"]["source"] == "observed"
