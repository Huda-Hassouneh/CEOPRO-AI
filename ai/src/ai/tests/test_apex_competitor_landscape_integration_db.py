"""Competitor landscape on a real database: stated and derived competition
levels, price position per competitor, and per-product coverage."""
import json
import os
import uuid
from datetime import datetime, timezone

import psycopg2
import pytest

from src.ai.market_inputs import competitor_landscape as landscape

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.mark.parametrize("stated, discovery, linked, catalog, expected", [
    ("PRODUCT", "INDUSTRY_KEYWORD_SEARCH", 0, 10, "PRODUCT"),   # what the owner said wins
    (None, "PLACES_NEARBY", 1, 10, "MARKET"),
    (None, None, 6, 10, "MARKET"),
    (None, None, 2, 10, "PRODUCT"),
    (None, None, 0, 10, "MARKET"),
])
def test_derive_level(stated, discovery, linked, catalog, expected):
    assert landscape.derive_level(stated, discovery, linked, catalog) == expected


def test_landscape_levels_prices_and_coverage():
    conn = psycopg2.connect(DATABASE_URL)
    tenant = str(uuid.uuid4())
    competitors = []
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');", (tenant, f"Landscape {tenant[:8]}"))
            products = {}
            for name, price in (("Coffee", 5.0), ("Honey", 20.0), ("Tea", 3.0)):
                pid = str(uuid.uuid4())
                cur.execute("INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, %s, 'JOD');", (pid, tenant, json.dumps({"en": name}), price))
                products[name] = pid
            for name, level, prices in (("Roaster", "PRODUCT", {"Coffee": 4.5}), ("Grocer", "MARKET", {"Coffee": 5.5, "Honey": 18.0})):
                cid = str(uuid.uuid4())
                competitors.append(cid)
                cur.execute("INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url) VALUES (%s, %s, %s);", (cid, name, f"https://{cid[:8]}.example.jo"))
                cur.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, competition_level) VALUES (%s, %s, TRUE, %s);", (tenant, cid, level))
                for product, price in prices.items():
                    cur.execute("INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id) VALUES (%s, %s, %s) RETURNING mapping_id;", (tenant, cid, products[product]))
                    mapping = cur.fetchone()[0]
                    cur.execute("INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, observed_at) VALUES (%s, %s, %s, 'JOD', %s);", (tenant, mapping, price, datetime.now(timezone.utc)))
        conn.commit()

        result = landscape.build_landscape(conn, tenant)
        by_name = {c["name"]: c for c in result["competitors"]}
        assert by_name["Roaster"]["level"] == "PRODUCT" and by_name["Roaster"]["cheaper_on"] == 1
        assert by_name["Grocer"]["level"] == "MARKET" and by_name["Grocer"]["pricier_on"] == 1 and by_name["Grocer"]["cheaper_on"] == 1
        assert result["market_wide"] == 1 and result["product_level"] == 1
        coverage = {p["name"]: p for p in result["products"]}
        assert coverage["Coffee"]["competitor_count"] == 2 and coverage["Coffee"]["cheapest"]["name"] == "Roaster"
        assert coverage["Tea"]["competitor_count"] == 0  # a blind spot, shown as such
        assert result["products_covered"] == 2 and result["catalog_size"] == 3
        assert result["products_priced_above"] == 1  # Honey: 20 vs 18 (+11%); Coffee is at the average
    finally:
        with conn.cursor() as cur:
            for table in ("competitor_prices", "competitor_product_mappings", "tenant_competitors", "products", "companies"):
                cur.execute(f"DELETE FROM {table} WHERE tenant_id = %s;", (tenant,))
            for cid in competitors:
                cur.execute("DELETE FROM global_competitors WHERE global_competitor_id = %s;", (cid,))
        conn.commit()
        conn.close()
