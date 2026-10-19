"""
Times the competitor screens against a database holding many competitors.

Seeds N competitors for one fresh company (a mix of: nothing collected, enrichment ledger rows, website facts with prices,
price history with changes), then calls the endpoints the competitor screens use several times and prints median / worst
milliseconds. Meant for a LOCAL database; it creates a throwaway account and never deletes anything.

  AI_TEST_DATABASE_URL=postgresql://... APP_DB_PASSWORD=... JWT_SECRET=... \
  python -m scripts.competitor_list_benchmark --competitors 1000 [--runs 5]

Reads through the app in process (FastAPI TestClient), so the numbers include auth, serialisation and the restricted
database role (RLS) but not the network.
"""
import argparse
import json
import os
import random
import statistics
import time
import uuid

import psycopg2

ITEMS_PER_SITE = 20


def seed(admin_url: str, tenant_id: str, count: int) -> list:
    rng = random.Random(7)
    ids = []
    with psycopg2.connect(admin_url) as conn, conn.cursor() as cursor:
        for i in range(count):
            cid = str(uuid.uuid4())
            ids.append(cid)
            site = f"https://competitor-{i:05d}.example.jo" if i % 5 else None
            cursor.execute(
                "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility, added_by_tenant_id, is_manufacturer, "
                "rating, rating_count, address, social_profiles) VALUES (%s, %s, %s, 'PRIVATE', %s, FALSE, %s, %s, %s, %s::jsonb);",
                (cid, f"{'Bakery' if i % 7 == 0 else 'Store'} {i:05d}", site, tenant_id, round(rng.uniform(3, 5), 1), rng.randint(5, 900),
                 f"{i} Main Street, Amman", json.dumps({"instagram": f"https://www.instagram.com/c{i}/"} if i % 3 == 0 else {})))
            cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, confidence_score, relevance_score) "
                           "VALUES (%s, %s, %s, %s, %s);", (tenant_id, cid, i % 4 != 0, rng.randint(20, 95), round(rng.random(), 3)))
            if site and i % 2 == 0:
                for facet, status in (("PROFILE", "SUCCEEDED"), ("PRICES", "PARTIAL" if i % 6 == 0 else "FAILED"), ("REVIEWS", "FAILED")):
                    cursor.execute("INSERT INTO competitor_enrichment (tenant_id, global_competitor_id, facet, status, items_found, last_attempt_at) "
                                   "VALUES (%s, %s, %s, %s, %s, now());", (tenant_id, cid, facet, status, rng.randint(0, 9)))
            if site and i % 3 == 0:
                for n in range(ITEMS_PER_SITE):
                    price = round(rng.uniform(1, 30), 2)
                    cursor.execute("INSERT INTO competitor_intel (tenant_id, global_competitor_id, kind, payload, source_url, confidence) "
                                   "VALUES (%s, %s, 'product', %s::jsonb, %s, 0.9);",
                                   (tenant_id, cid, json.dumps({"name": f"Item {n}", "price": price, "currency": "JOD"}), site + "/menu"))
                    cursor.execute("INSERT INTO competitor_price_history (tenant_id, global_competitor_id, name_key, item_name, price, currency, first_seen_at, last_seen_at, confidence) "
                                   "VALUES (%s, %s, %s, %s, %s, 'JOD', now() - interval '20 days', now() - interval '10 days', 0.9), "
                                   "(%s, %s, %s, %s, %s, 'JOD', now() - interval '5 days', now(), 0.9);",
                                   (tenant_id, cid, f"item {n}", f"Item {n}", price, tenant_id, cid, f"item {n}", f"Item {n}", round(price * rng.choice([0.9, 1.1]), 2)))
    with psycopg2.connect(admin_url) as conn:
        conn.autocommit = True
        with conn.cursor() as cursor:  # autovacuum does this in a live database; a freshly bulk-loaded one has no statistics yet
            for table in ("global_competitors", "tenant_competitors", "competitor_enrichment", "competitor_intel", "competitor_price_history"):
                cursor.execute(f"ANALYZE {table};")
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competitors", type=int, default=500)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    admin_url = os.environ["AI_TEST_DATABASE_URL"]
    from fastapi.testclient import TestClient

    from src.ai.main import app

    client = TestClient(app)
    response = client.post("/auth/signup", json={"full_name": "Bench Owner", "business_name": "Bench Co", "email": f"bench+{uuid.uuid4().hex[:8]}@example.com",
                                                  "country_code": "JO", "primary_currency": "JOD", "password": "Bench!Test-2026"})
    response.raise_for_status()
    session = response.json()
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    started = time.perf_counter()
    ids = seed(admin_url, session["tenant_id"], args.competitors)
    print(f"seeded {len(ids)} competitors in {time.perf_counter() - started:.1f}s")
    sample = ids[3]
    endpoints = [
        ("GET /discovery/competitors?limit=100 (first page)", "/discovery/competitors?limit=100"),
        ("GET /discovery/competitors?q=Bakery&limit=100", "/discovery/competitors?q=Bakery&limit=100"),
        ("GET /competitor-data/overview (every competitor)", "/competitor-data/overview"),
        ("GET /competitor-data/overview?ids=<100 on screen>", "/competitor-data/overview?ids=" + ",".join(ids[:100])),
        ("GET /dashboard/competitors", "/dashboard/competitors"),
        ("GET /discovery/price-changes", "/discovery/price-changes?days=30"),
        ("GET /discovery/competitors/{id} (one profile)", f"/discovery/competitors/{sample}"),
        ("GET /competitors/{id}/data-status", f"/competitors/{sample}/data-status"),
        ("GET /alerts", "/alerts"),
    ]
    print(f"{'endpoint':58s} {'status':>6s} {'median ms':>10s} {'worst ms':>9s} {'KB':>7s}")
    for label, path in endpoints:
        times, status, size = [], None, 0
        for _ in range(args.runs):
            t0 = time.perf_counter()
            r = client.get(path, headers=headers)
            times.append((time.perf_counter() - t0) * 1000)
            status, size = r.status_code, len(r.content)
        print(f"{label:58s} {status:>6d} {statistics.median(times):10.0f} {max(times):9.0f} {size / 1024:7.1f}")


if __name__ == "__main__":
    main()
