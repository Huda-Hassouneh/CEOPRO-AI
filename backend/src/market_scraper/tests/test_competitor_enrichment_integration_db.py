"""
Live-DB tests for competitor enrichment (migration 20261017000000): a
website-less Places find is registered and deduplicated by place_id, the
ledger records outcomes and increments attempts, a retry is additive, the
tenant cannot see another tenant's ledger, and data_completeness explains
price gaps from the real policy status. Skipped unless AI_TEST_DATABASE_URL
is set; Google/network calls are mocked.
"""
import os
import uuid
from unittest.mock import patch

import psycopg2
import pytest

from src.market_scraper import competitor_enrichment as ce
from src.market_scraper.discovery import CandidateSource, register_domain_level_competitor

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _register(conn, tenant_id, **overrides):
    candidate = CandidateSource(
        product_name="burger restaurant", url=overrides.pop("url", "https://burgerhub.example"),
        title=overrides.pop("title", "Burger Hub"), **overrides,
    )
    result = register_domain_level_competitor(conn, tenant_id, str(uuid.uuid4()), candidate, "PLACES_NEARBY")
    conn.commit()
    return result["competitor_id"]


def test_a_business_with_no_website_is_registered_once_by_place_id(conn):
    tenant_id = _insert_company(conn)
    first = _register(conn, tenant_id, url="", title="Corner Grill", place_id="ChIJ_abc", latitude=31.95, longitude=35.91)
    again = _register(conn, tenant_id, url="", title="Corner Grill (renamed)", place_id="ChIJ_abc")
    assert first == again
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT website_url, website_identity_key, google_place_id FROM global_competitors WHERE global_competitor_id = %s;",
            (first,),
        )
        assert cursor.fetchone() == (None, "place:ChIJ_abc", "ChIJ_abc")


def test_a_url_less_candidate_without_a_place_id_is_refused(conn):
    tenant_id = _insert_company(conn)
    with pytest.raises(ValueError):
        register_domain_level_competitor(conn, tenant_id, str(uuid.uuid4()), CandidateSource("x", "", "Nameless"), "PLACES_NEARBY")


def test_a_missing_key_is_recorded_in_the_ledger_and_attempts_accumulate(conn, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    with patch.object(ce.direct_search, "_robots_allowed_cached", return_value=False):
        ce.enrich_competitor(conn, tenant_id, competitor_id, places_api_key=None)
        ce.enrich_competitor(conn, tenant_id, competitor_id, facets=[ce.FACET_PROFILE], places_api_key=None)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT status, reason_code, attempts FROM competitor_enrichment "
            "WHERE tenant_id = %s AND global_competitor_id = %s AND facet = 'PROFILE';",
            (tenant_id, competitor_id),
        )
        assert cursor.fetchone() == ("BLOCKED", "NO_CREDENTIALS", 2)


def test_a_retry_adds_profile_data_without_overwriting_what_exists(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id, phone="+962 6 111", address="Amman")
    details = {
        "place_id": "p9", "website": "https://burgerhub.example", "formatted_address": "Other address",
        "formatted_phone_number": "+962 6 999", "rating": 4.4, "user_ratings_total": 120, "types": ["restaurant"],
    }
    with patch.object(ce, "_places_get", return_value={"result": details, "candidates": [{"place_id": "p9", "name": "Burger Hub"}]}), \
         patch.object(ce.direct_search, "_robots_allowed_cached", return_value=False):
        results = ce.enrich_competitor(conn, tenant_id, competitor_id, facets=[ce.FACET_PROFILE], places_api_key="k")
    assert results[ce.FACET_PROFILE]["status"] == ce.STATUS_SUCCEEDED
    with conn.cursor() as cursor:
        cursor.execute("SELECT address, phone, rating, rating_count, google_place_id FROM global_competitors WHERE global_competitor_id = %s;", (competitor_id,))
        address, phone, rating, rating_count, place_id = cursor.fetchone()
    assert (address, phone) == ("Amman", "+962 6 111")  # existing values kept
    assert (float(rating), rating_count, place_id) == (4.4, 120, "p9")  # gaps filled


def test_the_ledger_is_tenant_isolated_and_cascades_with_the_competitor_row(conn):
    tenant_a, tenant_b = _insert_company(conn), _insert_company(conn)
    competitor_id = _register(conn, tenant_a)
    ce._write_ledger(conn, tenant_a, competitor_id, ce.FACET_PROFILE, ce.STATUS_FAILED, ce.NO_MATCH, "x")
    assert ce.load_data_completeness(conn, tenant_b) == {}
    assert ce.load_data_completeness(conn, tenant_a, competitor_id)[competitor_id]["facets"][ce.FACET_PROFILE]["reason_code"] == ce.NO_MATCH


def test_completeness_explains_why_prices_and_reviews_are_empty(conn):
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    facets = ce.load_data_completeness(conn, tenant_id, competitor_id)[competitor_id]["facets"]
    assert facets[ce.FACET_PRICES]["reason_code"] == ce.NO_PRODUCTS_MAPPED
    assert facets[ce.FACET_REVIEWS]["reason_code"] == ce.NOT_ATTEMPTED
    assert facets[ce.FACET_SOCIAL_CONTENT]["reason_code"] == ce.NO_SOCIAL_LINKS
    assert facets[ce.FACET_PROFILE]["status"] == ce.STATUS_PENDING


def _candidates_picked(conn, tenant_id, mode):
    """Which competitors enrich_tenant_competitors(mode) would attempt (enrich_competitor stubbed)."""
    seen = []
    with patch.object(ce, "enrich_competitor", side_effect=lambda c, t, cid, **kw: seen.append(cid) or {}):
        ce.enrich_tenant_competitors(conn, tenant_id, mode=mode, limit=50)
    return seen


def test_due_mode_skips_permanent_misses_but_force_mode_retries_them_and_fixed_setup_blocks(conn):
    tenant_id = _insert_company(conn)
    permanent = _register(conn, tenant_id, url="https://permanent.example", title="Permanent")
    transient = _register(conn, tenant_id, url="https://transient.example", title="Transient")
    blocked_key = _register(conn, tenant_id, url="https://nokey.example", title="No Key")
    done = _register(conn, tenant_id, url="https://done.example", title="Done")
    for cid in (permanent, transient, blocked_key, done):
        # SOCIAL_LINKS and REVIEWS are settled for all four, so only PROFILE decides who is picked.
        ce._write_ledger(conn, tenant_id, cid, ce.FACET_SOCIAL_LINKS, ce.STATUS_SUCCEEDED)
        ce._write_ledger(conn, tenant_id, cid, ce.FACET_REVIEWS, ce.STATUS_SUCCEEDED)
    ce._write_ledger(conn, tenant_id, done, ce.FACET_PROFILE, ce.STATUS_SUCCEEDED)
    ce._write_ledger(conn, tenant_id, permanent, ce.FACET_PROFILE, ce.STATUS_FAILED, ce.NO_MATCH, "x")
    ce._write_ledger(conn, tenant_id, transient, ce.FACET_PROFILE, ce.STATUS_FAILED, ce.PROVIDER_ERROR, "x")
    ce._write_ledger(conn, tenant_id, blocked_key, ce.FACET_PROFILE, ce.STATUS_BLOCKED, ce.NO_CREDENTIALS, "x")
    with conn.cursor() as cursor:  # make the transient failure's scheduled retry due
        cursor.execute("UPDATE competitor_enrichment SET next_retry_at = NOW() - INTERVAL '1 minute' WHERE global_competitor_id = %s;", (transient,))
    conn.commit()

    assert set(_candidates_picked(conn, tenant_id, "due")) == {transient}
    assert set(_candidates_picked(conn, tenant_id, "force")) == {permanent, transient, blocked_key}


def test_the_sweep_function_lists_only_tenants_with_work(conn):
    busy, idle = _insert_company(conn), _insert_company(conn)
    _register(conn, busy)
    _register(conn, idle)
    for facet in (ce.FACET_PROFILE, ce.FACET_SOCIAL_LINKS):
        ce._write_ledger(conn, idle, _only_competitor(conn, idle), facet, ce.STATUS_SUCCEEDED)
    # `busy` has a competitor whose PROFILE was never attempted
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM list_tenants_with_due_enrichment();")
        tenants = {str(r[0]) for r in cursor.fetchall()}
    assert busy in tenants and idle not in tenants


def _only_competitor(conn, tenant_id):
    with conn.cursor() as cursor:
        cursor.execute("SELECT global_competitor_id FROM tenant_competitors WHERE tenant_id = %s;", (tenant_id,))
        return str(cursor.fetchone()[0])


def test_price_coverage_reports_each_product_with_its_real_reason(conn):
    from src.market_scraper.price_coverage import REASON_NO_MAPPING, REASON_TERMS, get_price_coverage
    tenant_id = _insert_company(conn)
    competitor_id = _register(conn, tenant_id)
    with conn.cursor() as cursor:
        for name in ("Mapped but unreviewed", "Unmatched"):
            cursor.execute(
                "INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s::jsonb, 5, 'JOD') RETURNING product_id;",
                (tenant_id, '{"en": "%s"}' % name),
            )
            if name.startswith("Mapped"):
                product_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO data_sources (tenant_id, source_name, source_type, policy_status) VALUES (%s, 'x', 'WEB_SCRAPE', 'RESTRICTED') RETURNING source_id;", (tenant_id,))
        source_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO competitor_product_mappings (tenant_id, global_competitor_id, product_id, competitor_product_url, source_id) VALUES (%s, %s, %s, 'https://x.example/p', %s);",
            (tenant_id, competitor_id, product_id, source_id),
        )
    conn.commit()
    result = get_price_coverage(conn, tenant_id)
    reasons = {i["product_name"]: i["reason_code"] for i in result["products"]}
    assert reasons == {"Mapped but unreviewed": REASON_TERMS, "Unmatched": REASON_NO_MAPPING}
    assert result["summary"]["coverage_pct"] == 0.0
    assert next(i for i in result["products"] if i["reason_code"] == REASON_TERMS)["source_ids"] == [str(source_id)]


def test_price_lookup_picks_only_unpriced_products_stores_a_quote_and_skips_recent_lookups(conn):
    from src.market_scraper.price_lookup import pipeline
    from src.market_scraper.price_lookup.models import PriceQuote
    tenant_id = _insert_company(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency, metadata) VALUES (%s, '{\"en\": \"Nutella Hazelnut Spread 350g\"}'::jsonb, 3.5, 'JOD', '{\"barcode\": \"3017-6204-22003\"}'::jsonb) RETURNING product_id;",
            (tenant_id,),
        )
        product_id = str(cursor.fetchone()[0])
    conn.commit()

    contexts = pipeline.products_needing_a_price(conn, tenant_id, limit=10)
    assert [c.product_id for c in contexts] == [product_id]
    assert contexts[0].barcode == "3017620422003"  # read from products.metadata, digits only

    quote = PriceQuote("web_offers", "Nutella Hazelnut Spread 350g", 3.4, "JOD", seller="Shop", url="https://shop.example/p", rating=4.6, review_count=12)
    assert pipeline._store(conn, tenant_id, contexts[0], quote, 1.0, True) is True
    assert pipeline._store(conn, tenant_id, contexts[0], quote, 1.0, True) is False  # same listing: updated, not duplicated
    pipeline._record_lookup(conn, tenant_id, contexts[0], pipeline.OUTCOME_FOUND, ["web_offers"], 1)
    conn.commit()

    assert pipeline.products_needing_a_price(conn, tenant_id, limit=10) == []  # it now has a reference price
    from src.market_scraper.price_coverage import get_price_coverage
    summary = get_price_coverage(conn, tenant_id, include_covered=True)
    assert summary["summary"]["with_reference_price_only"] == 1
    assert summary["products"][0]["price_basis"] == "market_reference"
