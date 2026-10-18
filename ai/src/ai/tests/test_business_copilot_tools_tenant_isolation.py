"""
Integration tests (real local Postgres, real restricted `ceopro_app` role) -
B10 in RAG_BUSINESS_COPILOT_ARCHITECTURE.md: every Business Copilot tool in
rag/tools.py must be tenant-isolated SERVER-SIDE, never relying on the LLM
to only ask about "its own" tenant. Same convention as
test_rls_integration_db.py (skipped unless AI_TEST_DATABASE_URL is set) and
reuses its own fixtures/helpers directly rather than duplicating the
two-tenant seed logic a second time.

Strategy: seed two tenants with their own products/sales/inventory/
competitors as the superuser (bypasses RLS for the seed itself, same as
every other fixture in this package), then call each tool with a
`conn`/`tenant_id` pair from ONE tenant's own `app_role_connection`-
equivalent (a real `ceopro_app`-role connection with `app.current_tenant_id`
set via SET LOCAL, the exact mechanism db_pool.py::PooledTenantConnection
uses) and assert tenant B's data never appears in the result - not "the
tool filtered it out in Python", but "RLS never returned tenant B's rows
to begin with", the same guarantee the rest of this codebase's security
model already rests on.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.dashboard import inventory as _inventory
from src.ai.dashboard import competitors as _competitors
from src.ai.dashboard import financial_summary as _financial_summary
from src.ai.routers import products as _products_router
from src.ai.tests.test_rls_integration_db import _ensure_role_key, _insert_user

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB tenant-isolation test",
)


def _app_database_url() -> str:
    parsed = urlparse(ADMIN_DATABASE_URL)
    netloc = f"ceopro_app:{APP_DB_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


@pytest.fixture
def admin_conn():
    connection = psycopg2.connect(ADMIN_DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture
def app_conn_for_tenant_a(two_tenants):
    """A real ceopro_app-role connection, scoped to tenant A via
    transaction-scoped SET LOCAL - the exact mechanism
    db_pool.py::PooledTenantConnection uses in production, not a
    simplified test-only stand-in."""
    connection = psycopg2.connect(_app_database_url())
    connection.autocommit = False
    cursor = connection.cursor()
    cursor.execute("SELECT set_config('app.current_tenant_id', %s, true);", (two_tenants["tenant_a"],))
    cursor.execute("SELECT set_config('app.current_user_id', %s, true);", (two_tenants["user_a"],))
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def two_tenants(admin_conn):
    """Seeds two tenants, each with a product, a sale (invoice), an
    inventory row, and a tracked competitor - enough real data for every
    tool under test in this file to have something to (incorrectly) leak
    if tenant isolation were broken."""
    cursor = admin_conn.cursor()
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())

    for tenant_id, name in [(tenant_a, "Tools Test Co A"), (tenant_b, "Tools Test Co B")]:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, name),
        )
    role_key = _ensure_role_key(cursor)
    user_a = _insert_user(cursor, "tools-user-a")
    user_b = _insert_user(cursor, "tools-user-b")

    for user_id, tenant_id in [(user_a, tenant_a), (user_b, tenant_b)]:
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role_key))

    product_a, product_b = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    for product_id, tenant_id, name, cost_price in [
        (product_a, tenant_a, "Tenant A Secret Widget", 3.0),
        (product_b, tenant_b, "Tenant B Secret Widget", 3.0),
    ]:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, cost_price, currency) "
            "VALUES (%s, %s, %s, 10.00, %s, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name}), cost_price),
        )
        cursor.execute(
            "INSERT INTO inventory (tenant_id, product_id, stock_quantity, reorder_level, safety_stock) VALUES (%s, %s, 1, 10, 5);",
            (tenant_id, product_id),
        )
        invoice_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency) "
            "VALUES (%s, %s, %s, %s, 100.0, 100.0, 'JOD');",
            (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", now - timedelta(days=2)),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) "
            "VALUES (%s, %s, %s, 10, 10.0, 100.0);",
            (tenant_id, invoice_id, product_id),
        )

    # global_competitors.competitor_name is globally unique (uq_competitor_global)
    # across ALL tenants - it's a shared identity table, tracking is
    # per-tenant via tenant_competitors. A fixed literal name would collide
    # across this fixture's repeated invocations within one pytest session
    # (the admin_conn fixture commits, it doesn't roll back - same as
    # test_rls_integration_db.py's own admin_conn), so each name is suffixed
    # with a fresh uuid to stay unique per test.
    global_competitor_a, global_competitor_b = str(uuid.uuid4()), str(uuid.uuid4())
    competitor_name_a = f"Tenant A Secret Competitor {global_competitor_a[:8]}"
    competitor_name_b = f"Tenant B Secret Competitor {global_competitor_b[:8]}"
    for gc_id, tenant_id, name in [
        (global_competitor_a, tenant_a, competitor_name_a),
        (global_competitor_b, tenant_b, competitor_name_b),
    ]:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, website_url) VALUES (%s, %s, %s);",
            (gc_id, name, f"https://{gc_id[:8]}.example.com"),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked, tier, product_match_rate, classified_at) "
            "VALUES (%s, %s, TRUE, 'STRATEGIC', 0.8, NOW());",
            (tenant_id, gc_id),
        )

    return {
        "tenant_a": tenant_a, "tenant_b": tenant_b,
        "user_a": user_a, "user_b": user_b,
        "product_a": product_a, "product_b": product_b,
        "competitor_name_a": competitor_name_a, "competitor_name_b": competitor_name_b,
    }


def test_list_products_never_returns_the_other_tenants_product(app_conn_for_tenant_a, two_tenants):
    result = _products_router.list_products(app_conn_for_tenant_a, two_tenants["tenant_a"])
    names = [p["product_name"] for p in result["products"]]
    assert "Tenant A Secret Widget" in names
    assert "Tenant B Secret Widget" not in names


def test_list_products_with_mismatched_tenant_id_argument_still_sees_nothing_of_tenant_b(app_conn_for_tenant_a, two_tenants):
    """The connection itself is scoped to tenant A (via SET LOCAL) - even
    if a caller passed tenant B's id as the tenant_id argument (a bug, or
    a compromised/confused caller), RLS - not the Python argument - is
    what actually governs what rows come back. This is the real assertion
    B10 cares about: the tool must not be trustable via its own argument."""
    result = _products_router.list_products(app_conn_for_tenant_a, two_tenants["tenant_b"])
    names = [p["product_name"] for p in result["products"]]
    assert "Tenant B Secret Widget" not in names


def test_get_top_selling_products_never_returns_the_other_tenants_product(app_conn_for_tenant_a, two_tenants):
    result = _financial_summary.get_product_profitability(app_conn_for_tenant_a, two_tenants["tenant_a"])
    names = [row["product_name"] for row in result["most_profitable"] + result["no_cost_data"]]
    assert "Tenant B Secret Widget" not in names


def test_analyze_revenue_change_never_includes_the_other_tenants_product_in_movers(app_conn_for_tenant_a, two_tenants):
    result = _financial_summary.analyze_revenue_change(app_conn_for_tenant_a, two_tenants["tenant_a"])
    mover_names = [m["product_name"] for m in result.get("top_movers", [])]
    assert "Tenant B Secret Widget" not in mover_names


def test_get_low_stock_products_never_returns_the_other_tenants_product(app_conn_for_tenant_a, two_tenants):
    result = _inventory.get_low_stock_products(app_conn_for_tenant_a, two_tenants["tenant_a"])
    names = [row["product_name"] for row in result]
    assert "Tenant A Secret Widget" in names  # sanity: tenant A's own low-stock row IS visible
    assert "Tenant B Secret Widget" not in names


def test_get_inventory_summary_counts_only_reflect_this_tenant(app_conn_for_tenant_a, two_tenants):
    result = _inventory.get_inventory_status(app_conn_for_tenant_a, two_tenants["tenant_a"])
    # Only tenant A's one product should be counted - if tenant B's row
    # leaked in, tracked_products would be 2, not 1.
    assert result["tracked_products"] == 1


def test_list_competitors_never_returns_the_other_tenants_competitor(app_conn_for_tenant_a, two_tenants):
    result = _competitors.get_competitor_directory(app_conn_for_tenant_a, two_tenants["tenant_a"])
    all_names = [row["name"] for row in result["strategic"] + result["relevant"]]
    assert two_tenants["competitor_name_a"] in all_names
    assert two_tenants["competitor_name_b"] not in all_names


def test_no_tenant_context_sees_no_products_from_either_tenant(two_tenants):
    """The same 'fails closed' guarantee test_rls_integration_db.py's own
    test_app_role_with_no_tenant_context_sees_nothing() already proves for
    raw table access - re-verified here through the actual tool function
    a Business Copilot request would call, not just a raw SELECT."""
    connection = psycopg2.connect(_app_database_url())
    connection.autocommit = False
    try:
        result = _products_router.list_products(connection, two_tenants["tenant_a"])
        assert result["products"] == []
    finally:
        connection.rollback()
        connection.close()
