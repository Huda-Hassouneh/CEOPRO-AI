"""
Regression tests for the Connect Data page's "Recent Data Activity" table,
found empty in first-customer acceptance testing even after three real
imports: the frontend had no endpoint to read (a hard-coded empty list),
and the uploaded file's name was never stored, so the dashboard feed read
"Manual File Upload" for every import. Live-DB, skipped unless
AI_TEST_DATABASE_URL is set.
"""
import os
import uuid

import psycopg2
import pytest

from src.ai.dashboard.activity import get_recent_activity
from src.ai.extraction import job_management

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
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _import(conn, tenant_id, file_name, source_type="CSV_UPLOAD", status="COMPLETED"):
    source_id = job_management.resolve_or_create_data_source(conn, tenant_id, source_type, "Manual File Upload")
    job_id = job_management.create_ingestion_job(conn, tenant_id, source_id, file_name=file_name)
    job_management.finalize_ingestion_job(conn, tenant_id, job_id, status)
    conn.commit()  # created_at is the transaction's timestamp - one import per transaction, like real uploads
    return job_id


def test_a_brand_new_tenant_has_no_import_history(conn):
    tenant_id = _insert_company(conn)
    assert job_management.list_recent_imports(conn, tenant_id) == []


def test_imports_are_listed_newest_first_with_their_real_file_names(conn):
    tenant_id = _insert_company(conn)
    _import(conn, tenant_id, "sales_june.csv")
    _import(conn, tenant_id, "sales_august.xlsx", source_type="XLSX_UPLOAD")
    _import(conn, tenant_id, "broken.pdf", source_type="PDF_UPLOAD", status="FAILED")

    imports = job_management.list_recent_imports(conn, tenant_id)

    assert [(i["file_name"], i["file_type"], i["status"]) for i in imports] == [
        ("broken.pdf", "pdf", "FAILED"),
        ("sales_august.xlsx", "xlsx", "COMPLETED"),
        ("sales_june.csv", "csv", "COMPLETED"),
    ]


def test_dashboard_activity_names_the_uploaded_file(conn):
    tenant_id = _insert_company(conn)
    _import(conn, tenant_id, "  sales_june.csv  ")
    activity = get_recent_activity(conn, tenant_id)
    assert activity[0]["detail"] == "sales_june.csv"


def test_connector_and_scraper_jobs_are_not_shown_as_file_imports(conn):
    tenant_id = _insert_company(conn)
    _import(conn, tenant_id, None, source_type="SHOPIFY_API")
    assert job_management.list_recent_imports(conn, tenant_id) == []


def test_import_history_never_includes_another_tenants_files(conn):
    mine, theirs = _insert_company(conn), _insert_company(conn)
    _import(conn, theirs, "their_secret_sales.csv")
    assert job_management.list_recent_imports(conn, mine) == []
