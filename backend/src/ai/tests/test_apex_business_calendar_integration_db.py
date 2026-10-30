"""Days are the company's local days.

Tenant transactions run in companies.timezone, so a sale at 23:30 UTC is
counted on the next day for a company in Amman (UTC+3) - in the daily chart,
in "today", and in the last-N-days windows.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from src.ai.core.business_time import business_today, window_start
from src.ai.dashboard import metrics
from src.infrastructure.db_pool import TenantConnectionPool, forget_tenant_timezone

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set",
)


def _app_database_url() -> str:
    parsed = urlparse(ADMIN_DATABASE_URL)
    return urlunparse(parsed._replace(netloc=f"ceopro_app:{APP_DB_PASSWORD}@{parsed.hostname}:{parsed.port}"))


@pytest.fixture
def amman_company():
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    tenant_id, user_id, product_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with admin.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency, timezone) VALUES (%s, 'Calendar Co', 'JO', 'JOD', 'Asia/Amman');",
            (tenant_id,),
        )
        cursor.execute("INSERT INTO users (user_id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'Cal');", (user_id, f"cal-{user_id}@example.com"))
        cursor.execute("SELECT role_key FROM system_roles LIMIT 1;")
        cursor.execute("INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, %s);", (tenant_id, user_id, cursor.fetchone()[0]))
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 2, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": "Mint Tea"})),
        )
    yield admin, tenant_id, user_id, product_id
    admin.close()


def _sale_at(admin, tenant_id, product_id, at, quantity=1):
    invoice_id = str(uuid.uuid4())
    with admin.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invoices (invoice_id, tenant_id, invoice_number, issue_date, subtotal, total_amount, currency, payment_status) VALUES (%s, %s, %s, %s, %s, %s, 'JOD', 'PAID');",
            (invoice_id, tenant_id, f"INV-{invoice_id[:8]}", at, 2 * quantity, 2 * quantity),
        )
        cursor.execute(
            "INSERT INTO invoice_items (tenant_id, invoice_id, product_id, quantity, unit_price, total_price) VALUES (%s, %s, %s, %s, 2, %s);",
            (tenant_id, invoice_id, product_id, quantity, 2 * quantity),
        )


def test_tenant_transactions_run_in_the_company_time_zone(amman_company):
    _admin, tenant_id, user_id, _product = amman_company
    forget_tenant_timezone(tenant_id)
    pool = TenantConnectionPool(_app_database_url(), minconn=1, maxconn=1)
    try:
        conn = pool.get_tenant_connection(tenant_id, user_id)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW TimeZone;")
                assert cursor.fetchone()[0] == "Asia/Amman"
            conn.commit()  # survives a commit, like the tenant context itself
            with conn.cursor() as cursor:
                cursor.execute("SHOW TimeZone;")
                assert cursor.fetchone()[0] == "Asia/Amman"
            local_today = datetime.now(timezone(timedelta(hours=3))).date()
            assert business_today(conn) == local_today
            assert window_start(conn, 30) == local_today - timedelta(days=29)
        finally:
            conn.close()
    finally:
        pool.closeall()


def test_a_late_evening_utc_sale_lands_on_the_next_local_day(amman_company):
    admin, tenant_id, user_id, product_id = amman_company
    forget_tenant_timezone(tenant_id)
    # 23:30 UTC eight days ago = 02:30 in Amman, seven days ago (local).
    utc_day = datetime.now(timezone.utc).date() - timedelta(days=8)
    at = datetime(utc_day.year, utc_day.month, utc_day.day, 23, 30, tzinfo=timezone.utc)
    _sale_at(admin, tenant_id, product_id, at, quantity=3)
    pool = TenantConnectionPool(_app_database_url(), minconn=1, maxconn=1)
    try:
        conn = pool.get_tenant_connection(tenant_id, user_id)
        try:
            trend = metrics.get_sales_trend(conn, tenant_id, 30)
        finally:
            conn.close()
    finally:
        pool.closeall()
    by_day = {p["date"]: p["units"] for p in trend["points"]}
    local_day = (at + timedelta(hours=3)).date().isoformat()
    assert by_day[local_day] == 3
    assert by_day[utc_day.isoformat()] == 0
    assert len(trend["points"]) == 30
    assert sum(p["units"] for p in trend["points"]) == 3
