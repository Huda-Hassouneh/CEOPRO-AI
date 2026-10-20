"""The price comparison endpoints through the real app and a real PostgreSQL (RLS, roles, entitlements, SQL):
refresh -> ladder with a category band -> owner sets and clears a band -> report -> another company sees none of it."""
import json
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set")


def _admin(sql, params=()):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
    conn.close()


def _signup(client):
    email = f"cmp+{uuid.uuid4().hex[:8]}@example.com"
    return client.post("/auth/signup", json={"full_name": "Owner", "business_name": "Burger Co", "email": email, "country_code": "JO",
                                              "primary_currency": "JOD", "password": "Compare!Test2026"}).json()


def test_ladder_bands_and_report_through_the_real_api():
    from src.ai.main import app

    client = TestClient(app)
    owner, other = _signup(client), _signup(client)
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    tenant = owner["tenant_id"]
    product_ids = []
    for price in (3.6, 3.9, 4.2, 4.5, 4.8, 5.1):
        product_id = str(uuid.uuid4())
        product_ids.append(product_id)
        _admin("INSERT INTO products (product_id, tenant_id, product_name, current_price, currency, category) VALUES (%s, %s, %s, %s, 'JOD', %s);",
               (product_id, tenant, json.dumps({"en": "Extra cheese burger"}), price, json.dumps({"en": "Burgers"})))
    competitor = str(uuid.uuid4())
    _admin("INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) VALUES (%s, 'Rival Grill', 'PRIVATE', %s, FALSE);", (competitor, tenant))
    _admin("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);", (tenant, competitor))
    _admin("INSERT INTO competitor_intel (tenant_id, global_competitor_id, kind, payload, source_url, confidence) VALUES (%s, %s, 'product', %s, 'https://rival.example/menu', 0.9);",
           (tenant, competitor, json.dumps({"name": "Cheese burger", "type": "product", "price": 3.0, "currency": "JOD"})))

    refreshed = client.post("/pricing/comparisons/refresh", headers=headers)
    assert refreshed.status_code == 200 and refreshed.json()["rows"] == 6

    ladder = client.get(f"/pricing/comparisons/{product_ids[0]}", headers=headers).json()
    assert ladder["category"] == "burgers" and ladder["headline"]["tier"] == "ADDED_VALUE"
    assert ladder["premium_band"]["source"] == "observed" and ladder["premium_band"]["samples"] == 6
    assert ladder["added_value_guidance"]["kind"] == "range_not_a_price"

    bands = client.get("/pricing/premium-bands", headers=headers).json()
    assert {c["category"]: c["band"]["source"] for c in bands["categories"]}["burgers"] == "observed"
    # an unknown shape or an out-of-range band is refused; another company cannot touch this one
    assert client.put("/pricing/premium-bands", json={"category": "burgers", "band_pct": 1}, headers=headers).status_code == 422
    saved = client.put("/pricing/premium-bands", json={"category": "Burgers", "band_pct": 25}, headers=headers)
    assert saved.status_code == 200
    assert {c["category"]: c["band"] for c in saved.json()["categories"]}["burgers"]["source"] == "owner"
    owned = client.get(f"/pricing/comparisons/{product_ids[-1]}", headers=headers).json()
    assert owned["premium_band"] == {"band_pct": 25.0, "source": "owner", "samples": 6}
    assert owned["tiers"]["ADDED_VALUE"]["items"][0]["premium"]["status"] == "above_range"  # 5.1 vs 3.0 is +70 %

    report = client.get("/reports/price-comparison?limit=3", headers=headers).json()
    assert report["count"] == 3 and report["products"][0]["headline"]["tier"] == "ADDED_VALUE"
    assert client.get(f"/pricing/comparisons/{product_ids[0]}", headers=other_headers).status_code == 404
    assert client.get("/reports/price-comparison", headers=other_headers).json() == {"products": [], "count": 0}
    assert all(c["category"] != "burgers" for c in client.get("/pricing/premium-bands", headers=other_headers).json()["categories"])

    cleared = client.put("/pricing/premium-bands", json={"category": "burgers", "band_pct": None}, headers=headers)
    assert {c["category"]: c["band"]["source"] for c in cleared.json()["categories"]}["burgers"] == "observed"
