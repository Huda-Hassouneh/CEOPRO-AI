"""
Integration test for tenant_discovery.py's orchestration against a real
PostgreSQL instance. Same convention as test_pricing_competitor_
classification_integration_db.py: skipped unless AI_TEST_DATABASE_URL is
set. discover_product_candidates (the real Google Custom Search call) is
mocked - this test verifies the orchestration/persistence wiring, not
Google's API, and needs no network credentials to run. evaluate_candidate()
runs for real (its own real robots.txt fetch), which is fine: with no
terms_evidence ever supplied by an automated run, policy.py's own decision
table (verified by reading policy.py directly) guarantees the outcome is
always BLOCKED or RESTRICTED, never ALLOWED, regardless of whether the
robots.txt fetch itself succeeds - so this test's assertions don't depend
on this environment's network reachability.
"""
import json
import os
import uuid
from unittest.mock import patch

import psycopg2
import pytest

from src.market_scraper.discovery import CandidateSource
from src.market_scraper.tenant_discovery import discover_competitors_for_tenant

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


def _insert_product(conn, tenant_id: str, name: str) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
    return product_id


def test_discovers_and_registers_candidates_for_a_non_electronics_vertical(conn):
    """
    The actual industry-agnostic claim, proven rather than asserted: a
    catalog with zero electronics_hobbyist keyword hits (coffee-shop
    products) still gets real candidates registered, entirely through the
    Google Custom Search path (RETAILER_DOMAINS_BY_VERTICAL has no
    "food_beverage" entry, so the free direct_search.py path contributes
    nothing here - every registered candidate below came from
    discover_product_candidates alone).
    """
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Espresso Machine")

    fake_candidates = [
        CandidateSource("Espresso Machine", "https://example-roastery.test/espresso-machine", "Example Roastery"),
    ]
    with patch(
        "src.market_scraper.tenant_discovery.discover_product_candidates",
        return_value=fake_candidates,
    ):
        results = discover_competitors_for_tenant(conn, tenant_id, actor_user_id=str(uuid.uuid4()))

    assert len(results) == 1
    result = results[0]
    assert result["product_url"] == "https://example-roastery.test/espresso-machine"
    assert result["policy_status"] in ("BLOCKED", "RESTRICTED")  # never auto-approved - see module docstring
    assert result["competitor_name"] == "Example Roastery"

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM global_competitors WHERE added_by_tenant_id = %s;", (tenant_id,)
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT approval_reference, approved_at FROM data_sources WHERE tenant_id = %s;", (tenant_id,)
        )
        approval_reference, approved_at = cursor.fetchone()
        assert approval_reference is None
        assert approved_at is None


def test_returns_no_results_when_custom_search_finds_nothing(conn):
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Espresso Machine")

    with patch("src.market_scraper.tenant_discovery.discover_product_candidates", return_value=[]):
        results = discover_competitors_for_tenant(conn, tenant_id, actor_user_id=str(uuid.uuid4()))

    assert results == []


def test_max_products_caps_how_many_catalog_products_are_searched(conn):
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Espresso Machine")
    _insert_product(conn, tenant_id, "Pour Over Kettle")

    with patch(
        "src.market_scraper.tenant_discovery.discover_product_candidates", return_value=[],
    ) as mocked:
        discover_competitors_for_tenant(conn, tenant_id, actor_user_id=str(uuid.uuid4()), max_products=1)

    assert mocked.call_count == 1


def test_deleted_products_are_not_searched(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Espresso Machine")
    with conn.cursor() as cursor:
        cursor.execute("UPDATE products SET deleted_at = NOW() WHERE product_id = %s;", (product_id,))

    with patch(
        "src.market_scraper.tenant_discovery.discover_product_candidates", return_value=[],
    ) as mocked:
        discover_competitors_for_tenant(conn, tenant_id, actor_user_id=str(uuid.uuid4()))

    mocked.assert_not_called()
