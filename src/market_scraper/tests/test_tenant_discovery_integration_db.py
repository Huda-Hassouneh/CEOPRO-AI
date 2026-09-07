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


def test_registers_a_social_only_competitor_with_no_e_commerce_website(conn):
    """
    The actual "vital business pillar" claim, proven end-to-end: a
    competitor that ONLY exists as an Instagram profile - no website_url
    at all in the ordinary sense - still gets a real global_competitors
    row, with website_identity_key correctly keyed on the handle (not
    the bare "instagram.com" host, which every Instagram business
    shares) so two different Instagram competitors never collide.
    """
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Espresso Machine")

    product_candidates = [
        CandidateSource("Espresso Machine", "https://www.instagram.com/acmecoffee/", "Acme Coffee Co (@acmecoffee)"),
    ]
    with patch("src.market_scraper.tenant_discovery.discover_product_candidates", return_value=[]), \
         patch("src.market_scraper.tenant_discovery.discover_social_profile_candidates", return_value=product_candidates):
        results = discover_competitors_for_tenant(conn, tenant_id, actor_user_id=str(uuid.uuid4()))

    assert len(results) == 1
    assert results[0]["competitor_name"] == "Acme Coffee Co (@acmecoffee)"

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT website_url, website_identity_key FROM global_competitors WHERE added_by_tenant_id = %s;",
            (tenant_id,),
        )
        website_url, identity_key = cursor.fetchone()
    assert website_url == "https://www.instagram.com/acmecoffee/"
    assert identity_key == "instagram.com/acmecoffee"


def test_include_social_only_false_skips_the_social_search(conn):
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Espresso Machine")

    with patch("src.market_scraper.tenant_discovery.discover_product_candidates", return_value=[]), \
         patch("src.market_scraper.tenant_discovery.discover_social_profile_candidates") as mocked_social:
        discover_competitors_for_tenant(
            conn, tenant_id, actor_user_id=str(uuid.uuid4()), include_social_only=False,
        )

    mocked_social.assert_not_called()


def test_sitemap_domains_contribute_candidates_when_vertical_has_a_seeded_entry(conn):
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Resistor Kit")  # electronics_hobbyist keyword

    sitemap_candidate = [CandidateSource("Resistor Kit", "https://seeedstudio.example/resistor-kit", "resistor kit")]
    with patch("src.market_scraper.tenant_discovery.discover_product_candidates", return_value=[]), \
         patch("src.market_scraper.tenant_discovery.discover_social_profile_candidates", return_value=[]), \
         patch("src.market_scraper.tenant_discovery.SITEMAP_DOMAINS_BY_VERTICAL", {"electronics_hobbyist": ["seeedstudio.example"]}), \
         patch("src.market_scraper.tenant_discovery.discover_products_via_sitemap", return_value=sitemap_candidate) as mocked_sitemap:
        results = discover_competitors_for_tenant(conn, tenant_id, actor_user_id=str(uuid.uuid4()))

    mocked_sitemap.assert_called_once_with("seeedstudio.example", "Resistor Kit", limit=2)
    assert len(results) == 1
    assert results[0]["product_url"] == "https://seeedstudio.example/resistor-kit"


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


def test_same_domain_found_under_two_different_titles_dedupes_to_one_row(conn):
    """
    The real bug this was written to catch: two discovery calls finding
    the SAME seller domain via different search paths (different result
    titles - exactly what Custom Search vs. a sitemap/SearchAction pass
    would produce for one real business) must land on one global_
    competitors row, not two. Pre-fix, the ON CONFLICT target was
    LOWER(competitor_name), so two different titles for one domain
    silently created two rows.
    """
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Espresso Machine")
    _insert_product(conn, tenant_id, "Pour Over Kettle")

    first_pass = [CandidateSource("Espresso Machine", "https://acmecoffee.example/espresso-machine", "Buy Espresso Machine - Acme Coffee Co")]
    second_pass = [CandidateSource("Pour Over Kettle", "https://acmecoffee.example/pour-over-kettle", "Acme Coffee | Pour Over Kettles")]

    with patch("src.market_scraper.tenant_discovery.discover_product_candidates", side_effect=[first_pass, second_pass]):
        results = discover_competitors_for_tenant(conn, tenant_id, actor_user_id=str(uuid.uuid4()))

    assert len(results) == 2
    assert results[0]["competitor_id"] == results[1]["competitor_id"]

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*), MAX(website_identity_key) FROM global_competitors WHERE added_by_tenant_id = %s;",
            (tenant_id,),
        )
        count, identity_key = cursor.fetchone()
    assert count == 1
    assert identity_key == "acmecoffee.example"


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
