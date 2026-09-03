"""
Integration test for the pricing pipeline against a real PostgreSQL instance
running the actual Final_schema.sql (+ migrations/). Same convention as
test_integration_db.py: skipped unless AI_TEST_DATABASE_URL is set.
"""

import json
import os
import uuid
from datetime import date, datetime, timezone

import psycopg2
import pytest

from src.ai.pricing import currency, data_access, matching, pipeline

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn, business_name: str) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, business_name),
        )
    return tenant_id


def _insert_product(conn, tenant_id: str, name: str, price: float, currency_code: str = "JOD", cost: float = None) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency, cost_price) "
            "VALUES (%s, %s, %s, %s, %s, %s);",
            (product_id, tenant_id, json.dumps({"en": name}), price, currency_code, cost),
        )
    return product_id


def _insert_competitor_price(
    conn, tenant_id: str, product_id: str, competitor_name: str, price: float, currency_code: str = "JOD",
) -> str:
    """
    Builds the full chain a real price needs: global_competitors ->
    tenant_competitors -> competitor_product_mappings -> competitor_prices.

    Reuses an existing global_competitor/mapping for the same
    (tenant_id, competitor_name, product_id) instead of inserting a fresh
    global_competitors row every call - repeated calls with the same
    competitor_name (e.g. seeding several observed prices for one rival)
    would otherwise collide with uq_competitor_private.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT global_competitor_id FROM global_competitors "
            "WHERE added_by_tenant_id = %s AND LOWER(competitor_name) = LOWER(%s);",
            (tenant_id, competitor_name),
        )
        row = cursor.fetchone()
        if row:
            global_competitor_id = row[0]
        else:
            global_competitor_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id) "
                "VALUES (%s, %s, 'PRIVATE', %s);",
                (global_competitor_id, competitor_name, tenant_id),
            )
            cursor.execute(
                "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);",
                (tenant_id, global_competitor_id),
            )

        cursor.execute(
            "SELECT mapping_id FROM competitor_product_mappings "
            "WHERE tenant_id = %s AND global_competitor_id = %s AND product_id = %s;",
            (tenant_id, global_competitor_id, product_id),
        )
        row = cursor.fetchone()
        if row:
            mapping_id = row[0]
        else:
            mapping_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, is_active) "
                "VALUES (%s, %s, %s, %s, TRUE);",
                (mapping_id, tenant_id, global_competitor_id, product_id),
            )

        cursor.execute(
            "INSERT INTO competitor_prices "
            "(tenant_id, mapping_id, scraped_price, currency, is_exact_data, source_status, is_available, observed_at) "
            "VALUES (%s, %s, %s, %s, TRUE, 'ALLOWED', TRUE, %s);",
            (tenant_id, mapping_id, price, currency_code, datetime.now(timezone.utc)),
        )
    return global_competitor_id


@pytest.fixture
def seeded_tenant_product_and_competitor(conn):
    tenant_id = _insert_company(conn, "Pricing Test Co")
    product_id = _insert_product(conn, tenant_id, "Sunscreen SPF 50", 30.00)
    competitor_id = None
    for price in (18.00, 19.50, 20.00):
        competitor_id = _insert_competitor_price(conn, tenant_id, product_id, "Rival Pharmacy", price)
    conn.commit()

    return tenant_id, product_id, competitor_id


def test_load_competitor_prices_reads_seeded_rows(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    records = data_access.load_competitor_prices(conn, tenant_id, product_id, "JOD")
    assert len(records) == 3
    assert {r["price_found"] for r in records} == {18.00, 19.50, 20.00}


def test_load_competitor_prices_excludes_wrong_currency(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    records = data_access.load_competitor_prices(conn, tenant_id, product_id, "USD")
    assert records == []


def test_load_competitor_prices_stays_tenant_scoped_for_a_shared_global_competitor(conn):
    """
    global_competitors can be a single shared GLOBAL row that many tenants
    independently track (visibility='GLOBAL', no added_by_tenant_id) - the
    trickiest cross-tenant-leak shape, since tenant_competitors/
    competitor_product_mappings/competitor_prices all key off the same
    global_competitor_id for two completely different tenants. Confirms the
    join chain (every join matched on tenant_id, not just the base WHERE)
    keeps each tenant's own price observations isolated.
    """
    tenant_a = _insert_company(conn, "Shared-Competitor Tenant A")
    tenant_b = _insert_company(conn, "Shared-Competitor Tenant B")
    product_a = _insert_product(conn, tenant_a, "Product A", 10.00)
    product_b = _insert_product(conn, tenant_b, "Product B", 10.00)

    shared_competitor_id = str(uuid.uuid4())
    mapping_a = str(uuid.uuid4())
    mapping_b = str(uuid.uuid4())
    # uq_competitor_global requires GLOBAL-visibility names to be unique
    # across the whole table (it's a shared canonical directory, unlike
    # PRIVATE names which are only unique per-tenant) - vary the name so
    # repeat runs against a not-yet-reset database don't collide.
    competitor_name = f"Shared Global Rival {shared_competitor_id}"
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility) VALUES (%s, %s, 'GLOBAL');",
            (shared_competitor_id, competitor_name),
        )
        cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);", (tenant_a, shared_competitor_id))
        cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);", (tenant_b, shared_competitor_id))
        cursor.execute(
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, is_active) VALUES (%s, %s, %s, %s, TRUE);",
            (mapping_a, tenant_a, shared_competitor_id, product_a),
        )
        cursor.execute(
            "INSERT INTO competitor_product_mappings (mapping_id, tenant_id, global_competitor_id, product_id, is_active) VALUES (%s, %s, %s, %s, TRUE);",
            (mapping_b, tenant_b, shared_competitor_id, product_b),
        )
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, is_exact_data, source_status, is_available, observed_at) "
            "VALUES (%s, %s, 111.11, 'JOD', TRUE, 'ALLOWED', TRUE, %s);",
            (tenant_a, mapping_a, datetime.now(timezone.utc)),
        )
        cursor.execute(
            "INSERT INTO competitor_prices (tenant_id, mapping_id, scraped_price, currency, is_exact_data, source_status, is_available, observed_at) "
            "VALUES (%s, %s, 222.22, 'JOD', TRUE, 'ALLOWED', TRUE, %s);",
            (tenant_b, mapping_b, datetime.now(timezone.utc)),
        )
    conn.commit()

    results_a = data_access.load_competitor_prices(conn, tenant_a, product_a, "JOD")
    results_b = data_access.load_competitor_prices(conn, tenant_b, product_b, "JOD")
    assert [r["price_found"] for r in results_a] == [111.11]
    assert [r["price_found"] for r in results_b] == [222.22]

    # cross tenant/product mismatch must return nothing, not tenant_b's row
    assert data_access.load_competitor_prices(conn, tenant_a, product_b, "JOD") == []


def test_load_own_product_excludes_soft_deleted_product(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET deleted_at = NOW() WHERE product_id = %s;", (product_id,))
    conn.commit()

    assert data_access.load_own_product(conn, tenant_id, product_id) is None


def test_load_own_product_returns_none_cost_when_unset(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    own = data_access.load_own_product(conn, tenant_id, product_id)
    assert own["cost"] is None


def test_load_own_product_reads_cost_when_set(conn):
    tenant_id = _insert_company(conn, "Cost Test Co")
    product_id = _insert_product(conn, tenant_id, "Widget", 30.00, cost=25.00)
    conn.commit()

    own = data_access.load_own_product(conn, tenant_id, product_id)
    assert own["cost"] == 25.00


def test_load_competitor_prices_excludes_untracked_competitor(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, competitor_id = seeded_tenant_product_and_competitor
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE tenant_competitors SET is_tracked = FALSE WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
    conn.commit()

    records = data_access.load_competitor_prices(conn, tenant_id, product_id, "JOD")
    assert records == []


def test_load_competitor_prices_excludes_inactive_mapping(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor
    with conn.cursor() as cursor:
        cursor.execute("UPDATE competitor_product_mappings SET is_active = FALSE WHERE tenant_id = %s;", (tenant_id,))
    conn.commit()

    records = data_access.load_competitor_prices(conn, tenant_id, product_id, "JOD")
    assert records == []


def test_run_price_recommendation_end_to_end_against_real_db(conn, seeded_tenant_product_and_competitor):
    tenant_id, product_id, _ = seeded_tenant_product_and_competitor

    result = pipeline.run_price_recommendation(conn, tenant_id, product_id)

    assert result["status"] == "OK"
    assert result["action"] == "lower"  # 30.00 is well above the ~19.17 market average
    assert result["matched_competitor_count"] == 3

    with conn.cursor() as cursor:
        cursor.execute("SELECT category FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],))
        assert cursor.fetchone()[0] == "RECOMMENDATION"

        cursor.execute(
            "SELECT evidence_id, tenant_id, user_decision FROM recommendation_outcomes WHERE recommendation_id = %s;",
            (result["outcome_id"],),
        )
        row = cursor.fetchone()
        assert row[0] == result["evidence_id"]
        assert row[1] == tenant_id
        assert row[2] == "PENDING"  # DB default, not yet acted on


def test_run_price_recommendation_applies_margin_guardrail_against_real_db(conn):
    tenant_id = _insert_company(conn, "Margin Test Co")
    # own price 30.00, cost 27.00 - a price-change-guardrailed suggestion
    # toward the ~19.17 market average (25.5 after the 15% guardrail) would
    # sell at a loss; the margin guardrail (10% over cost) must raise it back
    # to 27 * 1.10 = 29.70.
    product_id = _insert_product(conn, tenant_id, "Margin Widget", 30.00, cost=27.00)
    for price in (18.00, 19.50, 20.00):
        _insert_competitor_price(conn, tenant_id, product_id, "Rival Pharmacy", price)
    conn.commit()

    result = pipeline.run_price_recommendation(conn, tenant_id, product_id)

    assert result["status"] == "OK"
    assert result["margin_guardrail_clamped"] is True
    assert result["suggested_price"] == 29.70


def _upsert_currency_rate(conn, base: str, target: str, rate: float, rate_date_value: date, source: str) -> None:
    """
    currency_rates has no tenant_id (rates aren't tenant-scoped) and a unique
    constraint on (from_currency, to_currency) - a plain INSERT would collide
    with whatever a previous run of this same test already committed. Upsert
    instead so these tests are idempotent regardless of prior runs.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO currency_rates (from_currency, to_currency, exchange_rate, last_fetched)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (from_currency, to_currency)
            DO UPDATE SET exchange_rate = EXCLUDED.exchange_rate, last_fetched = EXCLUDED.last_fetched;
            """,
            (base, target, rate, rate_date_value),
        )
    conn.commit()


def test_get_latest_rate_reads_seeded_currency_rate(conn):
    _upsert_currency_rate(conn, "SAR", "JOD", 0.9500, date(2026, 8, 1), "test_feed")

    rate = currency.get_latest_rate(conn, "SAR", "JOD")
    assert rate.rate == 0.95


def test_run_price_recommendation_includes_cross_currency_reference_against_real_db(conn):
    tenant_id = _insert_company(conn, "Cross Currency Test Co")
    product_id = _insert_product(conn, tenant_id, "Sunscreen SPF 50", 20.00)
    _insert_competitor_price(conn, tenant_id, product_id, "Gulf Pharmacy", 75.00, currency_code="SAR")
    conn.commit()
    _upsert_currency_rate(conn, "SAR", "JOD", 0.9500, date(2026, 8, 1), "test_feed")

    result = pipeline.run_price_recommendation(conn, tenant_id, product_id)

    assert result["status"] == "UNKNOWN"  # no same-currency competitors matched
    with conn.cursor() as cursor:
        cursor.execute("SELECT explanation_text FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],))
        explanation = cursor.fetchone()[0]
        assert "reference only" in explanation
        assert "75.00 SAR" in explanation
        assert "71.25 JOD" in explanation  # 75.00 * 0.95


def test_run_price_recommendation_with_no_competitor_data_writes_unknown_evidence(conn):
    tenant_id = _insert_company(conn, "No Competitors Co")
    product_id = _insert_product(conn, tenant_id, "Rare Widget", 40.00)
    conn.commit()

    result = pipeline.run_price_recommendation(conn, tenant_id, product_id)

    assert result["status"] == "UNKNOWN"
    with conn.cursor() as cursor:
        cursor.execute("SELECT category FROM evidence_records WHERE evidence_id = %s;", (result["evidence_id"],))
        assert cursor.fetchone()[0] == "UNKNOWN"
        cursor.execute("SELECT COUNT(*) FROM recommendation_outcomes WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 0  # no outcome row when there's no recommendation


def _insert_global_competitor(
    conn, tenant_id: str, name: str, country_code: str = None, is_manufacturer: bool = False,
) -> str:
    global_competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors "
            "(global_competitor_id, competitor_name, visibility, added_by_tenant_id, country_code, is_manufacturer) "
            "VALUES (%s, %s, 'PRIVATE', %s, %s, %s);",
            (global_competitor_id, name, tenant_id, country_code, is_manufacturer),
        )
    return global_competitor_id


def test_create_competitor_mapping_succeeds_for_a_relevant_same_country_competitor(conn):
    """The straightforward, correct case: a same-country retail competitor must map cleanly."""
    tenant_id = _insert_company(conn, "Jordan Grocer Co")  # _insert_company hardcodes country_code='JO'
    product_id = _insert_product(conn, tenant_id, "Olive Oil 1L", 10.00)
    competitor_id = _insert_global_competitor(conn, tenant_id, "Rival Grocer JO", country_code="JO")
    conn.commit()

    mapping_id = matching.create_competitor_mapping(conn, tenant_id, competitor_id, product_id)
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tenant_id, global_competitor_id, product_id, is_active FROM competitor_product_mappings "
            "WHERE mapping_id = %s;",
            (mapping_id,),
        )
        row = cursor.fetchone()
    assert row == (tenant_id, competitor_id, product_id, True)


def test_create_competitor_mapping_rejects_a_geographically_irrelevant_competitor(conn):
    """
    The exact scenario flagged as a real gap: a competitor with no
    presence in any country this tenant operates in (e.g. an India-only
    business proposed as a competitor for a China-only restaurant) must
    be refused, not silently mapped on name similarity alone.
    """
    tenant_id = _insert_company(conn, "Jordan Grocer Co")  # country_code='JO', no operating_countries
    product_id = _insert_product(conn, tenant_id, "Olive Oil 1L", 10.00)
    competitor_id = _insert_global_competitor(conn, tenant_id, "Unrelated India Business", country_code="IN")
    conn.commit()

    with pytest.raises(matching.CompetitorMappingError, match="IN"):
        matching.create_competitor_mapping(conn, tenant_id, competitor_id, product_id)

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM competitor_product_mappings WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 0


def test_create_competitor_mapping_allows_a_tenants_declared_operating_country(conn):
    """A competitor outside the tenant's primary country but inside its declared operating_countries is still relevant."""
    tenant_id = _insert_company(conn, "Multi-Country Retailer")
    with conn.cursor() as cursor:
        cursor.execute("UPDATE companies SET operating_countries = ARRAY['SA', 'AE'] WHERE tenant_id = %s;", (tenant_id,))
    product_id = _insert_product(conn, tenant_id, "Dates 500g", 8.00)
    competitor_id = _insert_global_competitor(conn, tenant_id, "Riyadh Grocer", country_code="SA")
    conn.commit()

    mapping_id = matching.create_competitor_mapping(conn, tenant_id, competitor_id, product_id)
    assert mapping_id is not None


def test_create_competitor_mapping_rejects_a_competitor_with_no_country_on_record(conn):
    """Missing geography must fail closed, not be treated as 'assume relevant'."""
    tenant_id = _insert_company(conn, "Jordan Grocer Co")
    product_id = _insert_product(conn, tenant_id, "Olive Oil 1L", 10.00)
    competitor_id = _insert_global_competitor(conn, tenant_id, "Unknown Location Business", country_code=None)
    conn.commit()

    with pytest.raises(matching.CompetitorMappingError, match="no country_code"):
        matching.create_competitor_mapping(conn, tenant_id, competitor_id, product_id)


def test_create_competitor_mapping_rejects_a_manufacturer(conn):
    """
    The other flagged logical flaw: the business that manufactures a
    product is not a rival seller of it, even if same-country and even if
    its name is an exact match (a manufacturer's own storefront/brand
    page would otherwise pass geography and name-similarity checks).
    """
    tenant_id = _insert_company(conn, "Jordan Grocer Co")
    product_id = _insert_product(conn, tenant_id, "Olive Oil 1L", 10.00)
    manufacturer_id = _insert_global_competitor(
        conn, tenant_id, "Olive Oil Original Manufacturer", country_code="JO", is_manufacturer=True,
    )
    conn.commit()

    with pytest.raises(matching.CompetitorMappingError, match="manufacturer"):
        matching.create_competitor_mapping(conn, tenant_id, manufacturer_id, product_id)

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM competitor_product_mappings WHERE tenant_id = %s;", (tenant_id,))
        assert cursor.fetchone()[0] == 0
