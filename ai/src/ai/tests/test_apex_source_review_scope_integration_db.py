"""The competitor-source review queue lists discovered websites only - never
the business's own uploads, which are data_sources too."""
import os
import uuid

import psycopg2
import pytest

from src.market_scraper import data_access

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_DATABASE_URL, reason="AI_TEST_DATABASE_URL not set")


def test_uploads_are_not_listed_or_counted_as_competitor_sources():
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        tenant_id = str(uuid.uuid4())
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, 'Scope Co', 'JO', 'JOD');", (tenant_id,))
            cursor.execute(
                "INSERT INTO data_sources (tenant_id, source_name, source_type, policy_status) VALUES (%s, 'Manual File Upload', 'CSV_UPLOAD', 'RESTRICTED');",
                (tenant_id,),
            )
            cursor.execute(
                "INSERT INTO data_sources (tenant_id, source_name, source_type, source_url, policy_status) VALUES (%s, 'Rival Shop', 'WEB_SCRAPE', 'https://rival.example.jo', 'RESTRICTED');",
                (tenant_id,),
            )
        listed = data_access.list_tenant_sources(conn, tenant_id)
        assert [s["source_name"] for s in listed] == ["Rival Shop"]
        assert data_access.count_tenant_sources_by_status(conn, tenant_id) == {"ALLOWED": 0, "RESTRICTED": 1, "BLOCKED": 0}
    finally:
        conn.rollback()
        conn.close()
