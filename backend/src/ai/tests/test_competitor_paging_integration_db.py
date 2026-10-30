"""
The competitor directory pages past its first page against the real
database: "matching" counts what the filters select, pages don't overlap or
skip anyone, and search narrows the count.
"""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.tests.signup_helpers import create_verified_test_account

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB competitor paging test",
)
COMPETITORS = 230


@pytest.fixture
def company():
    from src.ai.main import app

    client = TestClient(app)
    session = create_verified_test_account(client, {"full_name": "Owner", "business_name": "Paging Co", "email": f"paging+{uuid.uuid4().hex[:8]}@example.com",
                                                     "country_code": "JO", "primary_currency": "JOD", "password": "Paging!Test-2026"})
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    with conn, conn.cursor() as cursor:
        for i in range(COMPETITORS):
            competitor_id = str(uuid.uuid4())
            cursor.execute("INSERT INTO global_competitors (global_competitor_id, competitor_name, visibility, added_by_tenant_id, is_manufacturer) "
                           "VALUES (%s, %s, 'PRIVATE', %s, FALSE);", (competitor_id, f"{'Bakery' if i % 10 == 0 else 'Store'} {i:03d}", session["tenant_id"]))
            cursor.execute("INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) VALUES (%s, %s, %s);",
                           (session["tenant_id"], competitor_id, i < 3))
    conn.close()
    return client, {"Authorization": f"Bearer {session['access_token']}"}


def test_pages_cover_every_competitor_once(company):
    client, headers = company
    seen, offset = [], 0
    while True:
        page = client.get("/discovery/competitors", params={"limit": 100, "offset": offset, "sort": "name"}, headers=headers).json()
        assert page["matching"] == COMPETITORS
        seen += [c["competitor_id"] for c in page["competitors"]]
        offset += len(page["competitors"])
        if not page["competitors"] or offset >= page["matching"]:
            break
    assert len(seen) == COMPETITORS == len(set(seen))


def test_filters_change_the_matching_count(company):
    client, headers = company
    assert client.get("/discovery/competitors", params={"q": "Bakery"}, headers=headers).json()["matching"] == COMPETITORS // 10
    tracked = client.get("/discovery/competitors", params={"status": "tracked"}, headers=headers).json()
    assert tracked["matching"] == 3 and tracked["counts"]["all"] == COMPETITORS
