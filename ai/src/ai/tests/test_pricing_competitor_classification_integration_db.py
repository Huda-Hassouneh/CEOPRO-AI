"""
Integration test for competitor_classification.py against a real
PostgreSQL instance running the actual Final_schema.sql (+ migrations/).
Same convention as test_pricing_integration_db.py: skipped unless
AI_TEST_DATABASE_URL is set.

Connects as the real ceopro_app role (not the admin/superuser DSN in
AI_TEST_DATABASE_URL) and sets app.current_tenant_id per test, same real
RLS/service-actor pattern test_market_integration_db.py's own app_url()/
scoped_app_connection() already establishes - companies/products/
global_competitors/tenant_competitors/competitor_product_mappings all
carry a real tenant-isolation policy keyed on get_current_tenant(), so an
insert with no tenant context set is correctly rejected, not a bug to
route around with a superuser DSN or a broader grant.
"""

import json
import os
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.pricing.competitor_classification import (
    SCOPE_BROAD_DOMAIN, SCOPE_NICHE_ITEM, SCOPE_PARTIAL_OVERLAP,
    TIER_CANDIDATE, TIER_RELEVANT, TIER_STRATEGIC, classify_competitor, compute_product_match_rate,
)
from src.market_scraper.company_target_markets import get_tenant_target_markets, set_tenant_target_markets

ADMIN_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not APP_PASSWORD,
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required - skipping live-DB integration test",
)


def _app_url():
    parsed = urlparse(ADMIN_URL)
    host = f"ceopro_app:{APP_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=host))


@pytest.fixture
def conn():
    connection = psycopg2.connect(_app_url())
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(
    conn, country_code: str = "JO", operating_countries=None, latitude=None, longitude=None,
    business_type=None, search_scope_level=None, default_search_radius_km=None,
) -> str:
    """
    Real tenant bootstrap, not a superuser shortcut: get_current_tenant()
    (every RLS policy this file's inserts rely on) requires BOTH
    app.current_tenant_id AND app.current_user_id to be set AND an ACTIVE
    tenant_users row linking them - so this creates a real users row and
    the tenant's first tenant_users membership too, exactly the bootstrap
    case tenant_users' own insert_tenant_users_onboarding policy exists
    for (session's own tenant_id/user_id, only while that tenant has zero
    members yet).

    Session-scoped (is_local=false), not local to the transaction: same
    real reason test_market_integration_db.py's own scoped_app_connection()
    already uses false - classify_competitor() commits internally, and a
    local (SET LOCAL-equivalent) GUC would be wiped by that commit, making
    this same connection's own read-back queries fail RLS afterward.
    """
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id', %s, false);", (tenant_id,))
        cursor.execute("SELECT set_config('app.current_user_id', %s, false);", (user_id,))
        cursor.execute(
            "INSERT INTO companies "
            "(tenant_id, business_name, business_type, country_code, primary_currency, operating_countries, "
            " latitude, longitude, search_scope_level, default_search_radius_km) "
            "VALUES (%s, %s, %s, %s, 'JOD', %s, %s, %s, COALESCE(%s, 'PROVINCE'), %s);",
            (
                tenant_id, f"Test Co {tenant_id[:8]}", business_type, country_code, operating_countries or [],
                latitude, longitude, search_scope_level, default_search_radius_km,
            ),
        )
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'Test User');",
            (user_id, f"test-{user_id[:8]}@example.com"),
        )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner');",
            (tenant_id, user_id),
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


def _insert_competitor(
    conn, tenant_id: str, is_manufacturer: bool = False, country_code: str = None,
    latitude=None, longitude=None,
) -> str:
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors "
            "(global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer, "
            " country_code, latitude, longitude) "
            "VALUES (%s, %s, 'PRIVATE', %s, %s, %s, %s, %s);",
            (
                competitor_id, f"Competitor {competitor_id[:8]}", tenant_id, is_manufacturer, country_code,
                latitude, longitude,
            ),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id) VALUES (%s, %s);",
            (tenant_id, competitor_id),
        )
    return competitor_id


def _map_product(conn, tenant_id: str, competitor_id: str, product_id: str):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, is_active) "
            "VALUES (%s, %s, %s, TRUE);",
            (tenant_id, competitor_id, product_id),
        )


def test_match_rate_is_zero_with_no_mapped_products(conn):
    tenant_id = _insert_company(conn)
    _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id)
    assert compute_product_match_rate(conn, tenant_id, competitor_id) == 0.0


def test_match_rate_reflects_overlap_ratio(conn):
    tenant_id = _insert_company(conn)
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")  # unmapped - keeps ratio at 50%
    competitor_id = _insert_competitor(conn, tenant_id)
    _map_product(conn, tenant_id, competitor_id, product_a)
    assert compute_product_match_rate(conn, tenant_id, competitor_id) == 0.5


def test_classify_confirms_an_in_region_non_manufacturer_above_threshold(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.product_match_rate == 1.0

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_tracked, is_confirmed_competitor, product_match_rate FROM tenant_competitors "
            "WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        is_tracked, is_confirmed, match_rate = cursor.fetchone()
    assert is_tracked is True
    assert is_confirmed is True
    assert float(match_rate) == 1.0


def test_classify_excludes_a_manufacturer_regardless_of_match_rate(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert "manufacturer" in result.reason

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_tracked FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone()[0] is False


def test_classify_excludes_a_seller_outside_the_operating_region(conn):
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["AE"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="US")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.in_operating_region is False


def test_classify_allows_an_operating_countries_match_beyond_primary(conn):
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["AE"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="AE")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.in_operating_region is True
    assert result.is_confirmed_competitor is True


def test_classify_does_not_exclude_a_competitor_with_unknown_country(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code=None)
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.in_operating_region is True
    assert result.is_confirmed_competitor is True


def test_classify_still_confirms_and_tracks_below_threshold_overlap(conn):
    """Real bug fix: a below-threshold seller is RELEVANT-tier, not
    excluded - it already passed the manufacturer/region gates, so it's
    a real, in-region competitor and must stay confirmed/tracked, just
    not STRATEGIC. Only TIER_CANDIDATE (manufacturer or out-of-region)
    is ever excluded from tracking."""
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)  # 1/3 = 33%, below default 60%

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.tier == TIER_RELEVANT
    assert result.product_match_rate == pytest.approx(1 / 3)

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_tracked, is_confirmed_competitor FROM tenant_competitors "
            "WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        is_tracked, is_confirmed = cursor.fetchone()
    assert is_tracked is True
    assert is_confirmed is True


def test_classify_honors_a_custom_threshold(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)  # 33% overlap

    result = classify_competitor(conn, tenant_id, competitor_id, threshold=0.3)
    assert result.is_confirmed_competitor is True


def test_classify_rejects_invalid_threshold(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _insert_competitor(conn, tenant_id)
    with pytest.raises(ValueError, match="threshold"):
        classify_competitor(conn, tenant_id, competitor_id, threshold=1.5)


def test_tier_is_strategic_when_confirmed(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.tier == TIER_STRATEGIC

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tier FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone()[0] == TIER_STRATEGIC


def test_tier_is_relevant_when_below_threshold_but_otherwise_real(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)  # 1/3 = 33%, below default 60%

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True  # RELEVANT is still a real, tracked competitor
    assert result.tier == TIER_RELEVANT

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tier FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone()[0] == TIER_RELEVANT


def test_tier_is_candidate_for_a_manufacturer(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.tier == TIER_CANDIDATE


def test_tier_is_candidate_for_an_out_of_region_seller(conn):
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["AE"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="US")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.tier == TIER_CANDIDATE


def test_scope_is_niche_item_for_a_single_mapped_product(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    _insert_product(conn, tenant_id, "Widget D")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)  # exactly one product - 1/4 = 25%

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.matched_product_count == 1
    assert result.competitor_scope == SCOPE_NICHE_ITEM

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT competitor_scope FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone()[0] == SCOPE_NICHE_ITEM


def test_scope_is_broad_domain_when_most_of_the_catalog_overlaps(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    product_b = _insert_product(conn, tenant_id, "Widget B")
    _insert_product(conn, tenant_id, "Widget C")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)
    _map_product(conn, tenant_id, competitor_id, product_b)  # 2/3 = 67% - broad, and >=2 products

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.matched_product_count == 2
    assert result.competitor_scope == SCOPE_BROAD_DOMAIN


def test_scope_is_partial_overlap_between_the_two_extremes(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    product_b = _insert_product(conn, tenant_id, "Widget B")
    for i in range(6):
        _insert_product(conn, tenant_id, f"Widget X{i}")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)
    _map_product(conn, tenant_id, competitor_id, product_b)  # 2/8 = 25%, and 2 products (not niche)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.matched_product_count == 2
    assert result.competitor_scope == SCOPE_PARTIAL_OVERLAP


def test_scope_honors_a_custom_broad_domain_threshold(conn):
    tenant_id = _insert_company(conn, country_code="JO")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    product_b = _insert_product(conn, tenant_id, "Widget B")
    for i in range(6):
        _insert_product(conn, tenant_id, f"Widget X{i}")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)
    _map_product(conn, tenant_id, competitor_id, product_b)  # 25% overlap

    result = classify_competitor(conn, tenant_id, competitor_id, broad_domain_threshold=0.2)
    assert result.competitor_scope == SCOPE_BROAD_DOMAIN


def test_distance_km_is_none_when_either_side_has_no_coordinates(conn):
    tenant_id = _insert_company(conn, country_code="JO")  # no lat/lon
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(
        conn, tenant_id, is_manufacturer=False, country_code="JO", latitude=31.95, longitude=35.93,
    )
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.distance_km is None


def test_distance_km_is_computed_and_persisted_when_both_sides_have_coordinates(conn):
    tenant_id = _insert_company(conn, country_code="JO", latitude=31.9539, longitude=35.9106)
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(
        conn, tenant_id, is_manufacturer=False, country_code="JO", latitude=31.9454, longitude=35.9284,
    )
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.distance_km is not None
    assert 0 < result.distance_km < 5  # two real, nearby Amman points

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT distance_km FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        assert float(cursor.fetchone()[0]) == pytest.approx(result.distance_km)


# --- Generic target-market scope (search_scope_level/GLOBAL/radius) -----


def test_global_scope_includes_a_competitor_from_any_country(conn):
    tenant_id = _insert_company(conn, country_code="JO", search_scope_level="GLOBAL")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.in_operating_region is True


def test_non_global_scope_still_excludes_a_country_mismatch(conn):
    """The actual fix for 'a Jordanian retailer should not automatically
    get a Chinese manufacturer as a direct competitor': once a real
    country_code is on file (previously never populated by discovery at
    all - see discovery.py::infer_country_code_from_domain()), a non-
    GLOBAL scope tenant correctly excludes a real country mismatch."""
    tenant_id = _insert_company(conn, country_code="JO", search_scope_level="COUNTRY")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert "CN" in result.reason


def test_city_scope_excludes_a_competitor_beyond_the_configured_radius(conn):
    """'If the user targets one city/governorate, results outside that
    geographic scope should not be treated as direct competitors' -
    distance_km was already computed but never used as a gate before this
    fix; now a real, known distance beyond the tenant's own radius
    excludes, same as an out-of-country seller."""
    tenant_id = _insert_company(
        conn, country_code="JO", latitude=31.9539, longitude=35.9106,
        search_scope_level="CITY", default_search_radius_km=25,
    )
    product_a = _insert_product(conn, tenant_id, "Widget A")
    # Amman vs. Irbid, Jordan - same country, ~70km apart, well beyond a
    # 25km CITY radius.
    competitor_id = _insert_competitor(
        conn, tenant_id, is_manufacturer=False, country_code="JO", latitude=32.5556, longitude=35.8500,
    )
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.distance_km > 25


def test_city_scope_includes_a_competitor_within_the_configured_radius(conn):
    tenant_id = _insert_company(
        conn, country_code="JO", latitude=31.9539, longitude=35.9106,
        search_scope_level="CITY", default_search_radius_km=25,
    )
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(
        conn, tenant_id, is_manufacturer=False, country_code="JO", latitude=31.9454, longitude=35.9284,
    )
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True


def test_radius_gate_does_not_exclude_when_distance_is_unknown(conn):
    """Honesty contract unchanged: a competitor with no coordinates on
    file is never excluded on distance alone, even under a radius-gated
    scope - absence of evidence, not evidence of absence."""
    tenant_id = _insert_company(
        conn, country_code="JO", latitude=31.9539, longitude=35.9106,
        search_scope_level="CITY", default_search_radius_km=25,
    )
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.distance_km is None


def test_country_scope_never_applies_a_radius_even_with_known_coordinates(conn):
    """COUNTRY (and GLOBAL) scope means no distance ring at all, by
    company_geo_profile.py's own design - a far-away same-country
    competitor is never excluded on distance under this scope."""
    tenant_id = _insert_company(
        conn, country_code="JO", latitude=31.9539, longitude=35.9106, search_scope_level="COUNTRY",
    )
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(
        conn, tenant_id, is_manufacturer=False, country_code="JO", latitude=32.5556, longitude=35.8500,
    )
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.distance_km > 25  # real distance is still computed/persisted, just not gated on


# --- Business-type-aware manufacturer gate -------------------------------


def test_manufacturer_tenant_is_not_excluded_from_manufacturer_competitors(conn):
    """The actual fix for 'a retailer should not automatically get a
    factory/manufacturer unless the user explicitly includes that type':
    a tenant whose OWN business_type reads as a manufacturer/wholesaler
    has its real rivals (other manufacturers) correctly NOT excluded."""
    tenant_id = _insert_company(conn, country_code="JO", business_type="Electronics Manufacturer")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.tier == TIER_STRATEGIC


def test_retailer_tenant_still_excludes_a_manufacturer_competitor(conn):
    tenant_id = _insert_company(conn, country_code="JO", business_type="Electronics Retailer")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.tier == TIER_CANDIDATE


def test_unset_business_type_still_excludes_a_manufacturer_competitor(conn):
    """No business_type on file at all (the common case for an existing
    tenant pre-dating this fix) keeps the original, safe default: exclude
    manufacturers, same as before this change."""
    tenant_id = _insert_company(conn, country_code="JO", business_type=None)
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="JO")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False


# --- Explicit commercial Target Markets ------------------------------------
#
# company_target_markets.py - a real, separate, human-declared "I want to
# compete here" list, never inferred from operating_countries/country_code/
# business_type/products. These tests exercise it through the actual
# public contract other code depends on: set_tenant_target_markets()/
# get_tenant_target_markets() (same functions src/ai/routers/settings.py's
# PUT/GET /settings/company/target-markets call) feeding real classify_
# competitor() runs against a real Postgres instance.

def test_a_declared_target_market_country_is_never_auto_populated(conn):
    """The core 'never invent' guarantee: setting operating_countries
    alone (no explicit PUT to target-markets) leaves company_target_markets
    completely empty - no code path here silently derives one from the
    other."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO", "AE"])
    assert get_tenant_target_markets(conn, tenant_id) == []


def test_out_of_region_competitor_stays_excluded_without_a_declared_target_market(conn):
    """Baseline this whole feature is added on top of, unchanged: a
    competitor outside operating_countries is excluded exactly like before
    Target Markets existed, as long as nothing was ever explicitly
    declared for it."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.tier == TIER_CANDIDATE


def test_declaring_the_competitors_country_as_a_target_market_includes_it(conn):
    """The actual feature: a competitor outside operating_countries/search
    radius is no longer excluded once its country is an EXPLICITLY
    declared target market - a real commercial-expansion signal
    operating_countries/search scope were never designed to express."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO"], search_scope_level="COUNTRY")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    set_tenant_target_markets(conn, tenant_id, [{"market_type": "COUNTRY", "country_code": "CN"}])
    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True
    assert result.tier == TIER_STRATEGIC
    assert "declared target market" in result.reason


def test_target_market_override_also_bypasses_the_radius_gate(conn):
    """A declared target market country makes a CITY/PROVINCE-radius
    exclusion irrelevant too, not just the plain country mismatch - a
    tenant's real target market is a country-level commercial decision,
    not bounded by a local discovery radius that was never meant to
    filter it. Same real coordinates/radius as
    test_city_scope_excludes_a_competitor_beyond_the_configured_radius
    above (same country on both sides, so this actually exercises the
    RADIUS branch of _in_target_market_scope, not the country-mismatch
    one)."""
    tenant_id = _insert_company(
        conn, country_code="JO", latitude=31.9539, longitude=35.9106,
        search_scope_level="CITY", default_search_radius_km=25,
    )
    product_a = _insert_product(conn, tenant_id, "Widget A")
    # Amman vs. Irbid, Jordan - same country, ~70km apart, well beyond a
    # 25km CITY radius.
    competitor_id = _insert_competitor(
        conn, tenant_id, is_manufacturer=False, country_code="JO", latitude=32.5556, longitude=35.8500,
    )
    _map_product(conn, tenant_id, competitor_id, product_a)

    set_tenant_target_markets(conn, tenant_id, [{"market_type": "COUNTRY", "country_code": "JO"}])
    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True


def test_removing_a_declared_target_market_excludes_the_competitor_again(conn):
    """set_tenant_target_markets() is a real replace/PUT - clearing the
    list (an explicit, valid choice) removes the earlier override, and the
    next classify_competitor() run reverts to the ordinary region gate."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    set_tenant_target_markets(conn, tenant_id, [{"market_type": "COUNTRY", "country_code": "CN"}])
    assert classify_competitor(conn, tenant_id, competitor_id).is_confirmed_competitor is True

    set_tenant_target_markets(conn, tenant_id, [])
    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.tier == TIER_CANDIDATE


def test_target_market_declaration_never_overrides_the_manufacturer_exclusion(conn):
    """The manufacturer gate and the target-market override are
    independent checks, evaluated in a fixed order - declaring a
    manufacturer's own country as a target market must not make KEEL
    suddenly treat it as a real retail rival for a non-manufacturer
    tenant; only _tenant_business_type_signals_manufacturer() (the
    tenant's OWN declared business_type) can do that."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO"], business_type="Electronics Retailer")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    set_tenant_target_markets(conn, tenant_id, [{"market_type": "COUNTRY", "country_code": "CN"}])
    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert "manufacturer" in result.reason


def test_a_region_target_market_never_affects_classification(conn):
    """REGION-type target markets are free-text discovery-bias evidence
    only (see company_target_markets.py's own docstring) - they carry no
    ISO country code, so classify_competitor()'s country-evidence gate has
    nothing unambiguous to act on and must not treat a REGION declaration
    as if it were a COUNTRY override."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO"])
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    set_tenant_target_markets(conn, tenant_id, [{"market_type": "REGION", "region_name": "East Asia"}])
    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert result.tier == TIER_CANDIDATE


def test_a_global_target_market_includes_a_competitor_from_any_country(conn):
    """A GLOBAL-type target market is the one target-market declaration
    that DOES bypass the country/radius gate entirely - same 'compete
    everywhere' contract as search_scope_level=GLOBAL, triggered here by
    the tenant's own explicit commercial declaration instead."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO"], search_scope_level="COUNTRY")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=False, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    set_tenant_target_markets(conn, tenant_id, [{"market_type": "GLOBAL"}])
    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is True


def test_a_global_target_market_still_excludes_a_manufacturer(conn):
    """GLOBAL target market bypasses geography, never the manufacturer
    gate - the two checks stay independent regardless of which
    target-market type triggered the geographic bypass."""
    tenant_id = _insert_company(conn, country_code="JO", operating_countries=["JO"], business_type="Electronics Retailer")
    product_a = _insert_product(conn, tenant_id, "Widget A")
    competitor_id = _insert_competitor(conn, tenant_id, is_manufacturer=True, country_code="CN")
    _map_product(conn, tenant_id, competitor_id, product_a)

    set_tenant_target_markets(conn, tenant_id, [{"market_type": "GLOBAL"}])
    result = classify_competitor(conn, tenant_id, competitor_id)
    assert result.is_confirmed_competitor is False
    assert "manufacturer" in result.reason


def test_declared_target_markets_are_tenant_isolated(conn):
    """Tenant A's declared target markets are never visible to, or usable
    by, Tenant B - get_tenant_target_markets() is scoped by the real
    tenant_id argument against the real tenant-owned table, not a global
    list. Two independent connections (each with its own RLS session
    context), same real pattern as cross-tenant isolation tests elsewhere
    in this codebase, since _insert_company()'s context is session-scoped
    per connection."""
    tenant_a = _insert_company(conn, country_code="JO", operating_countries=["JO"])
    set_tenant_target_markets(conn, tenant_a, [{"market_type": "COUNTRY", "country_code": "AE"}])
    assert get_tenant_target_markets(conn, tenant_a) == [
        {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
    ]

    conn_b = psycopg2.connect(_app_url())
    try:
        conn_b.autocommit = False
        tenant_b = _insert_company(conn_b, country_code="DE", operating_countries=["DE"])
        assert get_tenant_target_markets(conn_b, tenant_b) == []
        assert get_tenant_target_markets(conn_b, tenant_a) == []
    finally:
        conn_b.rollback()
        conn_b.close()
