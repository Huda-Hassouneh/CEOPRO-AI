"""
Integration tests for register_manual_competitor() - the "Add Competitor"
UI action's real backend. Same convention as every other live-DB test in
this package: skipped unless AI_TEST_DATABASE_URL is set.
"""
import os
import uuid

import psycopg2
import pytest

from src.ai.pricing.competitor_classification import TIER_CANDIDATE, TIER_STRATEGIC
from src.market_scraper.discovery import register_manual_competitor

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn, country_code: str = "JO") -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, %s, 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}", country_code),
        )
    return tenant_id


def test_registers_a_real_new_competitor(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = register_manual_competitor(conn, tenant_id, "SparkFun Electronics", "https://sparkfun.com")
    conn.commit()

    assert result["competitor_name"] == "SparkFun Electronics"
    assert "sparkfun.com" in result["website_url"]
    assert result["is_manufacturer"] is False

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tc.discovery_method, tc.is_tracked, gc.visibility, gc.added_by_tenant_id "
            "FROM tenant_competitors tc JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id "
            "WHERE tc.tenant_id = %s AND tc.global_competitor_id = %s;",
            (tenant_id, result["competitor_id"]),
        )
        discovery_method, is_tracked, visibility, added_by = cursor.fetchone()
    assert discovery_method is None  # honest: no discovery run found this, the owner typed it in
    assert is_tracked is True
    assert visibility == "PRIVATE"
    assert str(added_by) == tenant_id


def test_runs_real_classification_immediately(conn):
    """A manually-added competitor gets a real tier the moment it's
    added, same as every other registration path - not an unclassified
    placeholder row."""
    tenant_id = _insert_company(conn, country_code="JO")
    conn.commit()

    result = register_manual_competitor(conn, tenant_id, "Rival Co", "https://rival.example")
    conn.commit()

    assert result["tier"] in (TIER_CANDIDATE, TIER_STRATEGIC, "RELEVANT")
    assert result["is_confirmed_competitor"] is not None


def test_excludes_a_real_manufacturer_domain(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    result = register_manual_competitor(conn, tenant_id, "Example Wholesale Distributor", "https://example-wholesale.com")
    conn.commit()

    assert result["is_manufacturer"] is True
    assert result["tier"] == TIER_CANDIDATE


def test_adding_the_same_website_twice_converges_on_one_row(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    first = register_manual_competitor(conn, tenant_id, "Rival Co", "https://rival.example")
    conn.commit()
    second = register_manual_competitor(conn, tenant_id, "Rival Co Renamed", "https://rival.example")
    conn.commit()

    assert first["competitor_id"] == second["competitor_id"]

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM global_competitors WHERE added_by_tenant_id = %s;",
            (tenant_id,),
        )
        assert cursor.fetchone()[0] == 1


def test_two_different_tenants_adding_the_same_website_get_separate_rows(conn):
    """visibility='PRIVATE' + added_by_tenant_id scoping - the same
    tenant isolation every other registration path in this module
    already guarantees."""
    tenant_a = _insert_company(conn)
    tenant_b = _insert_company(conn)
    conn.commit()

    result_a = register_manual_competitor(conn, tenant_a, "Rival Co", "https://rival.example")
    conn.commit()
    result_b = register_manual_competitor(conn, tenant_b, "Rival Co", "https://rival.example")
    conn.commit()

    assert result_a["competitor_id"] != result_b["competitor_id"]
