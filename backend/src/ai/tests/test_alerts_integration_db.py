"""Alerts come from the company's own live data and are read per person:
a failed import and a trial about to end show up, reading clears the
unread count, and another company sees none of it."""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.tests.signup_helpers import create_verified_test_account

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set")


def _admin(sql, params=()):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
    conn.close()


def _signup(client):
    email = f"alerts+{uuid.uuid4().hex[:8]}@example.com"
    body = create_verified_test_account(client, {"full_name": "Owner", "business_name": "Alert Co", "email": email,
                                                  "country_code": "JO", "primary_currency": "JOD", "password": "Alerts!Test2026"})
    return body, email


def test_alerts_from_live_data_are_read_per_company():
    from src.ai.main import app

    client = TestClient(app)
    owner, email = _signup(client)
    other, other_email = _signup(client)
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    try:
        source_id = str(uuid.uuid4())
        _admin("INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) VALUES (%s, %s, 'Uploads', 'FILE_UPLOAD');", (source_id, owner["tenant_id"]))
        _admin("INSERT INTO ingestion_jobs (tenant_id, source_id, job_status, file_name, ended_at) VALUES (%s, %s, 'FAILED', 'broken.csv', NOW());", (owner["tenant_id"], source_id))
        _admin("UPDATE billing_trials SET ends_at = NOW() + INTERVAL '2 days' WHERE tenant_id = %s;", (owner["tenant_id"],))

        listed = client.get("/alerts", headers=headers).json()
        kinds = {a["kind"] for a in listed["alerts"]}
        assert {"import_failed", "trial_ending"} <= kinds
        failed = next(a for a in listed["alerts"] if a["kind"] == "import_failed")
        assert failed["params"]["name"] == "broken.csv" and failed["link"] == "/connect-data" and failed["unread"]
        assert listed["unread"] >= 2

        assert client.post("/alerts/read", headers=headers).status_code == 200
        assert client.get("/alerts", headers=headers).json()["unread"] == 0

        other_alerts = client.get("/alerts", headers={"Authorization": f"Bearer {other['access_token']}"}).json()
        assert "import_failed" not in {a["kind"] for a in other_alerts["alerts"]}
    finally:
        for tenant, mail in ((owner["tenant_id"], email), (other["tenant_id"], other_email)):
            _admin("DELETE FROM ingestion_jobs WHERE tenant_id = %s;", (tenant,))
            _admin("DELETE FROM companies WHERE tenant_id = %s;", (tenant,))
            _admin("DELETE FROM users WHERE email = %s;", (mail,))
