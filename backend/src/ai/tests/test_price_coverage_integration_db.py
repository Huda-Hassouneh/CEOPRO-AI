"""
Live-DB test for market_scraper/price_coverage.py: test_price_coverage.py
feeds the report canned rows, so this is the only test that runs its SQL
against the real schema. Skipped unless AI_TEST_DATABASE_URL is set; reuses
the seeding helpers of the pricing integration tests.
"""
import pytest

from src.ai.tests.test_pricing_integration_db import (  # noqa: F401 (conn is a fixture)
    DATABASE_URL, _insert_company, _insert_competitor_price, _insert_product, conn,
)
from src.market_scraper import price_coverage

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


def test_coverage_reports_each_product_with_its_gap_cause_and_issues(conn):
    tenant_id = _insert_company(conn, "Coverage Co")
    fresh = _insert_product(conn, tenant_id, "Fresh Priced", 10.0)
    foreign = _insert_product(conn, tenant_id, "Foreign Priced", 10.0)
    old = _insert_product(conn, tenant_id, "Two Years Old", 10.0)
    nothing = _insert_product(conn, tenant_id, "Nothing Found", 10.0)
    _insert_competitor_price(conn, tenant_id, fresh, "Fresh Shop", 9.0)
    _insert_competitor_price(conn, tenant_id, foreign, "Foreign Shop", 9.0, currency_code="USD")
    _insert_competitor_price(conn, tenant_id, old, "Old Shop", 9.0)
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE competitor_prices SET observed_at = NOW() - INTERVAL '2 years' WHERE mapping_id IN "
            "(SELECT mapping_id FROM competitor_product_mappings WHERE product_id = %s);",
            (old,),
        )

    report = price_coverage.get_price_coverage(conn, tenant_id, include_covered=True, limit=None)

    summary = report["summary"]
    assert summary["total_products"] == 4
    assert summary["with_market_price"] == 3
    assert summary["gaps_by_reason"][price_coverage.REASON_NO_MAPPING] == 1
    assert summary["stale_prices"] == 1
    assert summary["currency_mismatches"] == 1

    by_id = {item["product_id"]: item for item in report["products"]}
    assert by_id[nothing]["reason_code"] == price_coverage.REASON_NO_MAPPING
    assert by_id[nothing]["has_market_price"] is False
    assert by_id[old]["issues"] == [price_coverage.ISSUE_STALE]
    assert by_id[foreign]["issues"] == [price_coverage.ISSUE_CURRENCY]
    assert by_id[fresh]["has_market_price"] is True and by_id[fresh]["issues"] == []

    gaps_only = price_coverage.get_price_coverage(conn, tenant_id)["products"]
    assert {item["product_id"] for item in gaps_only} == {nothing, old, foreign}  # covered-without-issues is omitted
