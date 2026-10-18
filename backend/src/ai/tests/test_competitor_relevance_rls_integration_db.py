"""
Competitor relevance (category-aware classification, confidence, evidence,
refresh) exercised as the REAL restricted `ceopro_app` role with tenant
context set - the only way to prove Row-Level Security does not break (or
leak through) the new code. Every other competitor test connects as the
superuser, which bypasses RLS entirely and therefore proves nothing about it
(the lesson of PENDING_ACTIONS.md #32). Needs AI_TEST_DATABASE_URL and
APP_DB_PASSWORD; skipped otherwise.
"""
import json
import os
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.dashboard.competitors import get_competitor_directory
from src.ai.pricing.competitor_classification import TIER_CANDIDATE, TIER_STRATEGIC, classify_competitor
from src.market_scraper.discovery import (
    CandidateSource, refresh_tenant_competitors, register_domain_level_competitor, register_manual_competitor,
)

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB RLS test",
)


def _app_url() -> str:
    parsed = urlparse(ADMIN_DATABASE_URL)
    return urlunparse(parsed._replace(netloc=f"ceopro_app:{APP_DB_PASSWORD}@{parsed.hostname}:{parsed.port}"))


@pytest.fixture
def admin():
    connection = psycopg2.connect(ADMIN_DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


def _seed_tenant(admin, products=("Cheeseburger", "Double Beef Burger", "Chicken Burger")) -> dict:
    cursor = admin.cursor()
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO companies (tenant_id, business_name, business_type, country_code, primary_currency) "
        "VALUES (%s, 'Burger Co', 'Burger restaurant', 'JO', 'JOD');", (tenant_id,),
    )
    cursor.execute("INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'x');", (user_id, f"{user_id}@example.com"))
    cursor.execute("SELECT role_key FROM system_roles LIMIT 1;")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO system_roles (role_key, role_name) VALUES ('OWNER', 'Owner');")
        row = ("OWNER",)
    cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, row[0]))
    for name in products:
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s, 5, 'JOD');",
            (tenant_id, json.dumps({"en": name})),
        )
    return {"tenant_id": tenant_id, "user_id": user_id}


def _app_conn(tenant: dict):
    connection = psycopg2.connect(_app_url())
    connection.autocommit = False
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_tenant_id', %s, false);", (tenant["tenant_id"],))
        cursor.execute("SELECT set_config('app.current_user_id', %s, false);", (tenant["user_id"],))
    connection.commit()
    return connection


def _register(conn, tenant, title, host, **kwargs):
    return register_domain_level_competitor(
        conn, tenant["tenant_id"], tenant["user_id"],
        CandidateSource("restaurant", f"https://{host}", title, **kwargs),
        discovery_method="PLACES_NEARBY", country_code="JO",
    )


def test_category_classification_works_under_rls(admin):
    tenant = _seed_tenant(admin)
    conn = _app_conn(tenant)
    try:
        pizza = _register(conn, tenant, "Napoli Pizza", "napoli.example", place_types=("pizza_restaurant",), rating=4.4, rating_count=80)
        donut = _register(conn, tenant, "Krispy Donuts", "krispy.example")
        assert pizza["tier"] == TIER_STRATEGIC
        assert donut["tier"] == TIER_CANDIDATE

        directory = get_competitor_directory(conn, tenant["tenant_id"])
        conn.commit()
        assert [c["name"] for c in directory["strategic"]] == ["Napoli Pizza"]
        assert directory["strategic"][0]["rating"] == 4.4
        assert directory["strategic"][0]["confidence_breakdown"]
    finally:
        conn.close()


def test_classification_writes_shared_evidence_records_visible_only_to_the_tenant(admin):
    tenant, other = _seed_tenant(admin), _seed_tenant(admin)
    conn = _app_conn(tenant)
    try:
        result = _register(conn, tenant, "Napoli Pizza", "napoli.example", place_types=("pizza_restaurant",))
        with conn.cursor() as cursor:
            cursor.execute("SELECT evidence_id FROM tenant_competitors WHERE global_competitor_id = %s;", (result["competitor_id"],))
            evidence_id = cursor.fetchone()[0]
            assert evidence_id is not None
            cursor.execute(
                "SELECT category, source_module, confidence_score, explanation_text, model_version, country_context "
                "FROM evidence_records WHERE evidence_id = %s;", (evidence_id,),
            )
            category, source_module, confidence, explanation, model_version, country = cursor.fetchone()
        assert category == "FACT" and source_module == "competitor_classification"
        assert 0 <= float(confidence) <= 1 and "STRATEGIC" in explanation and country == "JO"
    finally:
        conn.close()

    other_conn = _app_conn(other)
    try:
        with other_conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM evidence_records WHERE evidence_id = %s;", (evidence_id,))
            assert cursor.fetchone()[0] == 0  # RLS: another tenant cannot see it
    finally:
        other_conn.close()


def test_rescoring_an_unchanged_competitor_does_not_write_more_evidence(admin):
    tenant = _seed_tenant(admin)
    conn = _app_conn(tenant)
    try:
        result = _register(conn, tenant, "Napoli Pizza", "napoli.example", place_types=("pizza_restaurant",))
        before = classify_competitor(conn, tenant["tenant_id"], result["competitor_id"]).evidence_id
        after = classify_competitor(conn, tenant["tenant_id"], result["competitor_id"]).evidence_id
        assert before == after
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM evidence_records WHERE tenant_id = %s;", (tenant["tenant_id"],))
            assert cursor.fetchone()[0] == 1
    finally:
        conn.close()


def test_a_tier_change_writes_a_new_evidence_record(admin):
    tenant = _seed_tenant(admin)
    conn = _app_conn(tenant)
    try:
        result = _register(conn, tenant, "Napoli Pizza", "napoli.example", place_types=("pizza_restaurant",))
        first = classify_competitor(conn, tenant["tenant_id"], result["competitor_id"]).evidence_id
        with admin.cursor() as cursor:  # tenant pivots to desserts -> pizza no longer competes
            cursor.execute("UPDATE products SET deleted_at = NOW() WHERE tenant_id = %s;", (tenant["tenant_id"],))
            cursor.execute(
                "INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s, 3, 'JOD');",
                (tenant["tenant_id"], json.dumps({"en": "Glazed Donut"})),
            )
            cursor.execute("UPDATE companies SET business_type = 'Donut shop' WHERE tenant_id = %s;", (tenant["tenant_id"],))
        second = classify_competitor(conn, tenant["tenant_id"], result["competitor_id"])
        assert second.tier == TIER_CANDIDATE and second.evidence_id != first
    finally:
        conn.close()


def test_refresh_runs_under_rls_repairs_names_and_never_touches_another_tenant(admin):
    tenant, other = _seed_tenant(admin), _seed_tenant(admin)
    for t in (tenant, other):
        with admin.cursor() as cursor:
            competitor_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, website_identity_key, "
                "visibility, added_by_tenant_id) VALUES (%s, 'Some Product Title 123', 'https://www.shop.example', "
                "'shop.example', 'PRIVATE', %s);", (competitor_id, t["tenant_id"]),
            )
            cursor.execute(
                "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, discovery_method) VALUES (%s, %s, 'PRODUCT_SEARCH');",
                (t["tenant_id"], competitor_id),
            )

    conn = _app_conn(tenant)
    try:
        summary = refresh_tenant_competitors(conn, tenant["tenant_id"])
        assert summary["names_repaired"] == 1 and summary["reclassified"] == 1
    finally:
        conn.close()

    with admin.cursor() as cursor:
        cursor.execute(
            "SELECT competitor_name FROM global_competitors WHERE added_by_tenant_id = %s;", (other["tenant_id"],),
        )
        assert cursor.fetchone()[0] == "Some Product Title 123"  # untouched
        cursor.execute(
            "SELECT competitor_name FROM global_competitors WHERE added_by_tenant_id = %s;", (tenant["tenant_id"],),
        )
        assert cursor.fetchone()[0] == "shop.example"


def test_tenant_cannot_see_or_rescore_another_tenants_competitors(admin):
    a, b = _seed_tenant(admin), _seed_tenant(admin)
    conn_a = _app_conn(a)
    try:
        _register(conn_a, a, "Napoli Pizza", "napoli.example", place_types=("pizza_restaurant",))
    finally:
        conn_a.close()

    conn_b = _app_conn(b)
    try:
        assert get_competitor_directory(conn_b, b["tenant_id"]) == {"strategic": [], "relevant": [], "possible": []}
        assert refresh_tenant_competitors(conn_b, b["tenant_id"])["reclassified"] == 0
    finally:
        conn_b.close()


def test_a_shared_global_competitor_is_classified_without_writing_the_shared_row(admin):
    """GLOBAL rows are read-only to tenants under RLS (write_private_competitors).
    Classifying one must work and must not error trying to persist its
    category onto the shared row."""
    tenant = _seed_tenant(admin)
    competitor_id = str(uuid.uuid4())
    with admin.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url, visibility) "
            "VALUES (%s, %s, 'https://shared-pizza.example', 'GLOBAL');",
            (competitor_id, f"Shared Pizza Chain {competitor_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, discovery_method) VALUES (%s, %s, 'PLACES_NEARBY');",
            (tenant["tenant_id"], competitor_id),
        )
    conn = _app_conn(tenant)
    try:
        result = classify_competitor(conn, tenant["tenant_id"], competitor_id)
        assert result.tier == TIER_STRATEGIC  # category derived from the name at classify time
    finally:
        conn.close()
    with admin.cursor() as cursor:
        cursor.execute("SELECT category_path FROM global_competitors WHERE global_competitor_id = %s;", (competitor_id,))
        assert cursor.fetchone()[0] is None  # shared row not modified by a tenant


def test_manual_competitor_is_never_excluded_by_category_under_rls(admin):
    tenant = _seed_tenant(admin)
    conn = _app_conn(tenant)
    try:
        result = register_manual_competitor(conn, tenant["tenant_id"], "Krispy Donuts", "https://krispy.example")
        assert result["tier"] != TIER_CANDIDATE
    finally:
        conn.close()
