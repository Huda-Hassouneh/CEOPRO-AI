"""
Integration tests for domain-level competitor discovery - the real fix for
"the system cannot rely only on exact product matches" (register_domain_
level_competitor() in discovery.py, classify_competitor()'s discovery-
method-aware confirmation logic, and tenant_discovery.py::discover_domain_
level_competitors_for_tenant()'s orchestration). Same convention as every
other live-DB test in this package: skipped unless AI_TEST_DATABASE_URL is
set. Real network calls (Places/Custom Search) are mocked throughout - this
verifies the persistence/classification wiring, not the vendor APIs.
"""
import json
import os
import uuid
from unittest.mock import patch

import psycopg2
import pytest

from src.ai.pricing.competitor_classification import SCOPE_BROAD_DOMAIN, TIER_CANDIDATE, TIER_STRATEGIC
from src.market_scraper.company_geo_profile import SCOPE_LEVEL_CITY, SCOPE_LEVEL_COUNTRY, set_tenant_search_scope
from src.market_scraper.discovery import CandidateSource, register_domain_level_competitor
from src.market_scraper.tenant_discovery import discover_domain_level_competitors_for_tenant

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


def test_domain_level_competitor_is_confirmed_without_any_product_mapping(conn):
    """The actual point of this whole feature: a real business found by
    industry alone, with zero competitor_product_mappings rows, still gets
    confirmed - requiring product overlap here would make domain-level
    discovery pointless."""
    tenant_id = _insert_company(conn, country_code="JO")
    candidate = CandidateSource(
        "electronics store", "https://downtown-electronics.example", "Downtown Electronics",
        latitude=31.9454, longitude=35.9284, city="Amman, Jordan",
    )

    result = register_domain_level_competitor(
        conn, tenant_id, str(uuid.uuid4()), candidate,
        discovery_method="PLACES_NEARBY", industry_sector="electronics_hobbyist", country_code="JO",
    )

    assert result["is_confirmed_competitor"] is True
    assert result["tier"] == TIER_STRATEGIC
    assert result["competitor_scope"] == SCOPE_BROAD_DOMAIN

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT industry_sector, latitude, longitude FROM global_competitors WHERE global_competitor_id = %s;",
            (result["competitor_id"],),
        )
        industry_sector, latitude, longitude = cursor.fetchone()
        assert industry_sector == "electronics_hobbyist"
        assert float(latitude) == pytest.approx(31.9454)
        assert float(longitude) == pytest.approx(35.9284)

        cursor.execute(
            "SELECT COUNT(*) FROM competitor_product_mappings WHERE tenant_id = %s;", (tenant_id,)
        )
        assert cursor.fetchone()[0] == 0  # no product mapping - this is the real distinguishing feature

        cursor.execute(
            "SELECT discovery_method FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, result["competitor_id"]),
        )
        assert cursor.fetchone()[0] == "PLACES_NEARBY"


def test_domain_level_competitor_still_excludes_a_manufacturer(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    candidate = CandidateSource(
        "electronics store", "https://example.com/factory", "Example Wholesale Distributor",
    )
    result = register_domain_level_competitor(
        conn, tenant_id, str(uuid.uuid4()), candidate, discovery_method="INDUSTRY_KEYWORD_SEARCH",
    )
    assert result["is_confirmed_competitor"] is False
    assert result["tier"] == TIER_CANDIDATE
    assert "manufacturer" in result["classification_reason"]


def test_domain_level_competitor_still_excludes_an_out_of_region_business(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    candidate = CandidateSource(
        "electronics store", "https://faraway-shop.example", "Faraway Shop",
    )
    result = register_domain_level_competitor(
        conn, tenant_id, str(uuid.uuid4()), candidate,
        discovery_method="INDUSTRY_KEYWORD_SEARCH", country_code="US",
    )
    assert result["is_confirmed_competitor"] is False
    assert result["tier"] == TIER_CANDIDATE


def test_rejects_an_invalid_discovery_method(conn):
    tenant_id = _insert_company(conn)
    candidate = CandidateSource("x", "https://example.com", "Example")
    with pytest.raises(ValueError, match="discovery_method must be one of"):
        register_domain_level_competitor(conn, tenant_id, str(uuid.uuid4()), candidate, discovery_method="PRODUCT_SEARCH")


def test_orchestration_runs_both_sources_and_registers_real_candidates(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    _insert_product(conn, tenant_id, "Arduino Nano")
    set_tenant_search_scope(
        conn, tenant_id, latitude=31.9539, longitude=35.9106, search_scope_level=SCOPE_LEVEL_CITY,
    )

    places_result = [CandidateSource(
        "electronics store", "https://places-found.example", "Places Found Co",
        latitude=31.945, longitude=35.928,
    )]
    industry_result = [CandidateSource(
        "electronics_hobbyist", "https://industry-found.example", "Industry Found Co",
    )]

    with patch("src.market_scraper.tenant_discovery.discover_nearby_places", return_value=places_result), \
         patch("src.market_scraper.tenant_discovery.discover_industry_candidates", return_value=industry_result):
        results = discover_domain_level_competitors_for_tenant(
            conn, tenant_id, str(uuid.uuid4()), google_places_api_key="fake-key",
        )

    urls = {r["website_url"] for r in results}
    assert "https://places-found.example" in urls
    assert "https://industry-found.example" in urls
    methods = {r["discovery_method"] for r in results}
    assert methods == {"PLACES_NEARBY", "INDUSTRY_KEYWORD_SEARCH"}


def test_orchestration_skips_places_when_tenant_has_no_coordinates(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    _insert_product(conn, tenant_id, "Arduino Nano")
    # deliberately no set_tenant_search_scope() call - no lat/lon on file

    industry_result = [CandidateSource("electronics_hobbyist", "https://industry-only.example", "Industry Only Co")]

    with patch("src.market_scraper.tenant_discovery.discover_nearby_places") as mock_places, \
         patch("src.market_scraper.tenant_discovery.discover_industry_candidates", return_value=industry_result):
        results = discover_domain_level_competitors_for_tenant(
            conn, tenant_id, str(uuid.uuid4()), google_places_api_key="fake-key",
        )

    mock_places.assert_not_called()
    assert len(results) == 1
    assert results[0]["discovery_method"] == "INDUSTRY_KEYWORD_SEARCH"


def test_domain_and_product_level_finds_converge_on_the_same_competitor_row(conn):
    """The real dedup claim: the same business found once via domain-level
    discovery and once via ordinary product-level discovery must land as
    ONE global_competitors row (website_identity_key), not two."""
    from src.market_scraper.discovery import evaluate_candidate, register_tenant_scoped_competitor

    tenant_id = _insert_company(conn, country_code="JO")
    product_id = _insert_product(conn, tenant_id, "Arduino Nano")

    domain_candidate = CandidateSource("electronics store", "https://same-shop.example/", "Same Shop")
    domain_result = register_domain_level_competitor(
        conn, tenant_id, str(uuid.uuid4()), domain_candidate, discovery_method="INDUSTRY_KEYWORD_SEARCH",
    )

    product_candidate = CandidateSource("Arduino Nano", "https://same-shop.example/arduino-nano", "Same Shop - Arduino Nano")
    decision = evaluate_candidate(product_candidate)
    product_result = register_tenant_scoped_competitor(
        conn, tenant_id, str(uuid.uuid4()), decision, product_id,
    )

    assert domain_result["competitor_id"] == product_result["competitor_id"]

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM global_competitors WHERE added_by_tenant_id = %s;", (tenant_id,)
        )
        assert cursor.fetchone()[0] == 1


def test_orchestration_skips_places_for_an_explicit_country_scope_even_with_coordinates(conn):
    """COUNTRY scope means 'no radius filter' by design - a radius-bounded
    Nearby Search isn't a meaningful operation for it, so Places is
    correctly skipped even though the tenant DOES have coordinates on
    file; the industry-keyword search still covers this scope via its own
    text-based geo_scope."""
    tenant_id = _insert_company(conn, country_code="JO")
    _insert_product(conn, tenant_id, "Arduino Nano")
    set_tenant_search_scope(
        conn, tenant_id, latitude=31.9539, longitude=35.9106, search_scope_level=SCOPE_LEVEL_COUNTRY,
    )

    industry_result = [CandidateSource("electronics_hobbyist", "https://country-scope.example", "Country Scope Co")]

    with patch("src.market_scraper.tenant_discovery.discover_nearby_places") as mock_places, \
         patch("src.market_scraper.tenant_discovery.discover_industry_candidates", return_value=industry_result):
        results = discover_domain_level_competitors_for_tenant(
            conn, tenant_id, str(uuid.uuid4()), google_places_api_key="fake-key",
        )

    mock_places.assert_not_called()
    assert len(results) == 1
    assert results[0]["discovery_method"] == "INDUSTRY_KEYWORD_SEARCH"


# map_products_on_domain_competitor_site() - the real fix for "a domain-
# level competitor is discovered but nothing ever scrapes their site":
# finds real product pages on that ONE known competitor's own domain and
# registers them through the ordinary product-level path, which is what
# actually creates the competitor_product_mappings/data_sources rows
# load_scrape_targets() requires.

def test_map_products_registers_real_matches_via_the_ordinary_product_level_path(conn):
    from src.market_scraper.tenant_discovery import map_products_on_domain_competitor_site

    tenant_id = _insert_company(conn, country_code="JO")
    product_id = _insert_product(conn, tenant_id, "Arduino Nano")

    search_action_result = [CandidateSource("Arduino Nano", "https://same-shop.example/arduino-nano", "Arduino Nano - Same Shop")]

    with patch("src.market_scraper.tenant_discovery.search_product_across_retailers", return_value=search_action_result), \
         patch("src.market_scraper.tenant_discovery.discover_products_via_sitemap", return_value=[]):
        results = map_products_on_domain_competitor_site(
            conn, tenant_id, str(uuid.uuid4()), "https://same-shop.example/", [{"product_id": product_id, "product_name": "Arduino Nano"}],
        )

    assert len(results) == 1
    assert results[0]["product_url"] == "https://same-shop.example/arduino-nano"

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM competitor_product_mappings WHERE tenant_id = %s;", (tenant_id,)
        )
        assert cursor.fetchone()[0] == 1  # the real mapping load_scrape_targets() needs


def test_map_products_combines_both_free_discovery_mechanisms(conn):
    from src.market_scraper.tenant_discovery import map_products_on_domain_competitor_site

    tenant_id = _insert_company(conn, country_code="JO")
    product_id = _insert_product(conn, tenant_id, "Arduino Nano")

    search_action_result = [CandidateSource("Arduino Nano", "https://same-shop.example/p1", "P1")]
    sitemap_result = [CandidateSource("Arduino Nano", "https://same-shop.example/p2", "P2")]

    with patch("src.market_scraper.tenant_discovery.search_product_across_retailers", return_value=search_action_result), \
         patch("src.market_scraper.tenant_discovery.discover_products_via_sitemap", return_value=sitemap_result):
        results = map_products_on_domain_competitor_site(
            conn, tenant_id, str(uuid.uuid4()), "https://same-shop.example/", [{"product_id": product_id, "product_name": "Arduino Nano"}],
        )

    urls = {r["product_url"] for r in results}
    assert urls == {"https://same-shop.example/p1", "https://same-shop.example/p2"}


def test_map_products_returns_empty_when_neither_mechanism_finds_anything(conn):
    from src.market_scraper.tenant_discovery import map_products_on_domain_competitor_site

    tenant_id = _insert_company(conn, country_code="JO")
    product_id = _insert_product(conn, tenant_id, "Arduino Nano")

    with patch("src.market_scraper.tenant_discovery.search_product_across_retailers", return_value=[]), \
         patch("src.market_scraper.tenant_discovery.discover_products_via_sitemap", return_value=[]):
        results = map_products_on_domain_competitor_site(
            conn, tenant_id, str(uuid.uuid4()), "https://empty-shop.example/", [{"product_id": product_id, "product_name": "Arduino Nano"}],
        )
    assert results == []


def test_confirmed_domain_competitor_triggers_a_real_product_mapping_attempt(conn):
    """The end-to-end wiring: discover_domain_level_competitors_for_tenant()
    itself calls map_products_on_domain_competitor_site() for a CONFIRMED
    find (never for an excluded manufacturer/out-of-region one - no point
    spending the crawl effort there)."""
    tenant_id = _insert_company(conn, country_code="JO")
    _insert_product(conn, tenant_id, "Arduino Nano")

    industry_result = [CandidateSource("electronics_hobbyist", "https://real-competitor.example", "Real Competitor Co")]
    mapped = [{"competitor_id": "x", "product_url": "https://real-competitor.example/arduino-nano"}]

    with patch("src.market_scraper.tenant_discovery.discover_industry_candidates", return_value=industry_result), \
         patch("src.market_scraper.tenant_discovery.map_products_on_domain_competitor_site", return_value=mapped) as mock_map:
        results = discover_domain_level_competitors_for_tenant(conn, tenant_id, str(uuid.uuid4()))

    assert results[0]["is_confirmed_competitor"] is True  # in-region, not a manufacturer - real confirmation
    mock_map.assert_called_once()
    assert results[0]["mapped_products"] == mapped


def test_excluded_manufacturer_never_triggers_a_product_mapping_attempt(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    _insert_product(conn, tenant_id, "Arduino Nano")

    industry_result = [CandidateSource("electronics_hobbyist", "https://example.com/factory", "Example Wholesale Distributor")]

    with patch("src.market_scraper.tenant_discovery.discover_industry_candidates", return_value=industry_result), \
         patch("src.market_scraper.tenant_discovery.map_products_on_domain_competitor_site") as mock_map:
        results = discover_domain_level_competitors_for_tenant(conn, tenant_id, str(uuid.uuid4()))

    assert results[0]["is_confirmed_competitor"] is False
    mock_map.assert_not_called()
    assert "mapped_products" not in results[0]
