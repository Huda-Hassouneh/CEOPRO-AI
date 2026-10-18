"""
Integration tests for dashboard/activity.py against a real PostgreSQL
instance. Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.ai.dashboard.activity import get_recent_activity

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


def test_returns_empty_list_for_a_brand_new_tenant(conn):
    tenant_id = _insert_company(conn)
    conn.commit()
    assert get_recent_activity(conn, tenant_id) == []


def test_includes_a_real_product_added_event(conn):
    tenant_id = _insert_company(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (str(uuid.uuid4()), tenant_id, json.dumps({"en": "Widget"})),
        )
    conn.commit()

    activity = get_recent_activity(conn, tenant_id)
    assert len(activity) == 1
    assert activity[0]["activity_type"] == "PRODUCT_ADDED"
    assert activity[0]["title"] == "Product Added"
    assert activity[0]["detail"] == "Widget"
    assert activity[0]["status"] is None


def test_includes_a_real_file_uploaded_event_with_its_own_status(conn):
    tenant_id = _insert_company(conn)
    source_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) "
            "VALUES (%s, %s, 'sales_data_august.xlsx', 'FILE_UPLOAD');",
            (source_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO ingestion_jobs (job_id, tenant_id, source_id, job_status) "
            "VALUES (%s, %s, %s, 'COMPLETED');",
            (str(uuid.uuid4()), tenant_id, source_id),
        )
    conn.commit()

    activity = get_recent_activity(conn, tenant_id)
    assert len(activity) == 1
    assert activity[0]["activity_type"] == "FILE_UPLOADED"
    assert activity[0]["detail"] == "sales_data_august.xlsx"
    assert activity[0]["status"] == "COMPLETED"


def test_includes_a_real_competitor_tracked_event(conn):
    tenant_id = _insert_company(conn)
    competitor_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
            "VALUES (%s, 'Rival Co', 'PRIVATE', %s, FALSE);",
            (competitor_id, tenant_id),
        )
        cursor.execute(
            "INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, TRUE);",
            (tenant_id, competitor_id),
        )
    conn.commit()

    activity = get_recent_activity(conn, tenant_id)
    assert len(activity) == 1
    assert activity[0]["activity_type"] == "COMPETITOR_TRACKED"
    assert activity[0]["detail"] == "Rival Co"


def test_orders_newest_first_and_respects_limit(conn):
    tenant_id = _insert_company(conn)
    now = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        for i, offset_days in enumerate([5, 1, 3]):
            cursor.execute(
                "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency, created_at) "
                "VALUES (%s, %s, %s, 10.0, 'JOD', %s);",
                (str(uuid.uuid4()), tenant_id, json.dumps({"en": f"Product {i}"}), now - timedelta(days=offset_days)),
            )
    conn.commit()

    activity = get_recent_activity(conn, tenant_id, limit=2)
    assert len(activity) == 2
    assert activity[0]["detail"] == "Product 1"  # offset_days=1, most recent
    assert activity[1]["detail"] == "Product 2"  # offset_days=3, next most recent
