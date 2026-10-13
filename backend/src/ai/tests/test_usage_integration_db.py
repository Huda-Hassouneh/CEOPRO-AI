"""
Integration tests for core/usage.py (plan allowances) against a real
PostgreSQL instance, including tenant isolation through the restricted
ceopro_app role. Skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD
are set, like every other live-DB test here.
"""
import os
import threading
import uuid
from datetime import date

import psycopg2
import pytest

from src.ai.core import usage
from src.ai.tests.test_conversation_store_integration_db import _app_conn
from src.ai.tests.test_rls_integration_db import _ensure_role_key, _insert_user

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB integration test",
)


@pytest.fixture
def admin_conn():
    connection = psycopg2.connect(ADMIN_DATABASE_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture
def two_tenants(admin_conn):
    cursor = admin_conn.cursor()
    role_key = _ensure_role_key(cursor)
    out = {}
    for label in ("a", "b"):
        tenant_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Usage Test Co {label} {tenant_id[:6]}"),
        )
        user_id = _insert_user(cursor, f"usage-user-{label}")
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, role_key))
        out[f"tenant_{label}"], out[f"user_{label}"] = tenant_id, user_id
    return out


def _assign(admin_conn, tenant_id, plan_key, status="active", start=None, end=None):
    admin_conn.cursor().execute(
        "INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, current_period_start, current_period_end) "
        "VALUES (%s, %s, %s, %s, %s);",
        (tenant_id, plan_key, status, start, end),
    )


def _usage_of(items, code):
    return next(item for item in items if item["feature_code"] == code)


def test_a_company_without_an_assignment_gets_the_default_plan_and_a_calendar_month(admin_conn, two_tenants):
    plan = usage.get_plan(admin_conn, two_tenants["tenant_a"], today=date(2026, 10, 7))
    assert plan["plan_key"] == usage.DEFAULT_PLAN_KEY and plan["assigned"] is False and plan["status"] == "active"
    assert (plan["period_start"], plan["period_end"]) == (date(2026, 10, 1), date(2026, 10, 31))
    assert plan["features"][usage.RAG_ASSISTANT]["aggregation_type"] == "sum"


def test_an_assigned_plan_and_its_billing_period_are_used(admin_conn, two_tenants):
    _assign(admin_conn, two_tenants["tenant_a"], "standard", start=date(2026, 9, 15), end=date(2026, 10, 14))
    plan = usage.get_plan(admin_conn, two_tenants["tenant_a"], today=date(2026, 10, 7))
    assert plan["plan_key"] == "standard" and plan["features"][usage.RAG_ASSISTANT]["limit"] == 400
    assert (plan["period_start"], plan["period_end"]) == (date(2026, 9, 15), date(2026, 10, 14))


def test_reservations_stop_exactly_at_the_limit_and_released_ones_come_back(admin_conn, two_tenants):
    tenant_a, tenant_b = two_tenants["tenant_a"], two_tenants["tenant_b"]
    _assign(admin_conn, tenant_a, "standard")
    usage.reserve(admin_conn, tenant_a, usage.RAG_ASSISTANT, 399)
    last = usage.reserve(admin_conn, tenant_a, usage.RAG_ASSISTANT)
    with pytest.raises(usage.PlanLimitReached) as reached:
        usage.reserve(admin_conn, tenant_a, usage.RAG_ASSISTANT)
    detail = reached.value.as_http().detail
    assert (detail["reason"], detail["current_usage"], detail["limit"], detail["remaining"]) == ("QUOTA_EXHAUSTED", 400, 400, 0)
    assert detail["reset_cycle"] == "billing_period" and detail["period_end"] and "Billing" in detail["message"]
    usage.release(admin_conn, last)  # e.g. the language model failed: not counted
    usage.reserve(admin_conn, tenant_a, usage.RAG_ASSISTANT)
    # The other company is unaffected.
    usage.reserve(admin_conn, tenant_b, usage.RAG_ASSISTANT)
    assert _usage_of(usage.current_usage(admin_conn, tenant_b), usage.RAG_ASSISTANT)["current_usage"] == 1


def test_concurrent_reservations_never_overshoot_the_limit(admin_conn, two_tenants):
    tenant_a = two_tenants["tenant_a"]
    _assign(admin_conn, tenant_a, "standard")
    usage.reserve(admin_conn, tenant_a, usage.RAG_ASSISTANT, 390)
    granted, errors = [], []

    def worker():
        conn = psycopg2.connect(ADMIN_DATABASE_URL)
        try:
            usage.reserve(conn, tenant_a, usage.RAG_ASSISTANT)
            conn.commit()
            granted.append(1)
        except usage.PlanLimitReached:
            conn.rollback()
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(25)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(granted) == 10
    assert _usage_of(usage.current_usage(admin_conn, tenant_a), usage.RAG_ASSISTANT)["current_usage"] == 400


def test_unlimited_plans_never_block_and_inactive_subscriptions_do(admin_conn, two_tenants):
    tenant_a, tenant_b = two_tenants["tenant_a"], two_tenants["tenant_b"]
    _assign(admin_conn, tenant_a, "custom")
    usage.reserve(admin_conn, tenant_a, usage.RAG_ASSISTANT, 10_000_000)
    assert _usage_of(usage.current_usage(admin_conn, tenant_a), usage.RAG_ASSISTANT)["is_unlimited"] is True
    _assign(admin_conn, tenant_b, "pro", status="past_due")
    with pytest.raises(usage.PlanLimitReached) as reached:
        usage.reserve(admin_conn, tenant_b, usage.RAG_ASSISTANT)
    assert reached.value.reason == "SUBSCRIPTION_INACTIVE"


def test_capacity_features_are_counted_live(admin_conn, two_tenants):
    tenant_a = two_tenants["tenant_a"]
    _assign(admin_conn, tenant_a, "standard")
    cursor = admin_conn.cursor()
    for i in range(5):
        cursor.execute(
            "INSERT INTO products (tenant_id, product_name, current_price, currency) VALUES (%s, %s, 5, 'JOD');",
            (tenant_a, f'{{"en": "Mug {i}"}}'),
        )
    items = usage.current_usage(admin_conn, tenant_a)
    assert _usage_of(items, usage.TRACKED_PRODUCTS)["current_usage"] == 5
    usage.ensure_capacity(admin_conn, tenant_a, usage.TRACKED_PRODUCTS)  # 5 of 100
    cursor.execute(
        "INSERT INTO rag_documents_metadata (tenant_id, file_name, storage_bucket_path, file_size_bytes) VALUES (%s, 'big.pdf', 'x', %s);",
        (tenant_a, 5000 * 1048576),
    )
    with pytest.raises(usage.PlanLimitReached) as reached:
        usage.ensure_capacity(admin_conn, tenant_a, usage.DOCUMENT_STORAGE_MB, 200)  # 5000 + 200 MB > 5120 MB
    assert reached.value.reason == "CAPACITY_REACHED"


def test_the_app_role_counts_only_its_own_company_and_cannot_change_plans(two_tenants):
    tenant_a, user_a, tenant_b = two_tenants["tenant_a"], two_tenants["user_a"], two_tenants["tenant_b"]
    conn = _app_conn(tenant_a, user_a)
    try:
        usage.reserve(conn, tenant_a, usage.RAG_ASSISTANT, 3)
        assert _usage_of(usage.current_usage(conn, tenant_a), usage.RAG_ASSISTANT)["current_usage"] == 3
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM tenant_usage_counters WHERE tenant_id = %s;", (tenant_b,))
            assert cursor.fetchone()[0] == 0
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO tenant_plan_assignments (tenant_id, plan_key) VALUES (%s, 'custom');", (tenant_a,))
    finally:
        conn.rollback()
        conn.close()
