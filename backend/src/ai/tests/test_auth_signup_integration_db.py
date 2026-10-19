"""
Live-DB regression test for a real bug found during end-to-end acceptance
testing: chk_email_format (Final_schema.sql) did not allow '+' in the
email local part, so a perfectly valid, common real-world email (RFC 5321
sub-addressing, e.g. name+tag@gmail.com) was rejected at signup with an
unhandled psycopg2.errors.CheckViolation - surfaced to a real browser as a
generic "Unable to connect" error, not even a clear validation message.

Unlike test_auth_completeness.py (mocked cursor/connection - never
actually exercises the real CHECK constraint), this hits the real
Postgres database the fix (migrations/20261005000000_fix_email_format_
allow_plus_addressing.sql) was applied to, so it would have caught the
original bug.

Skipped unless AI_TEST_DATABASE_URL and APP_DB_PASSWORD are both set.
"""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not APP_DB_PASSWORD,
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB signup integration test",
)


def _cleanup_user(email: str):
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute("DELETE FROM tenant_users WHERE user_id IN (SELECT user_id FROM users WHERE email = %s);", (email,))
        cursor.execute("DELETE FROM companies WHERE tenant_id IN "
                        "(SELECT tenant_id FROM tenant_users WHERE user_id IN (SELECT user_id FROM users WHERE email = %s));", (email,))
        cursor.execute("DELETE FROM users WHERE email = %s;", (email,))
    admin.close()


def test_signup_accepts_a_real_plus_addressed_email():
    """The exact real-world case that failed live: RFC 5321 sub-addressing."""
    from src.ai.main import app  # local import - app construction needs env already loaded

    client = TestClient(app)
    email = f"amir.nabulsi+{uuid.uuid4().hex[:8]}@example.com"
    try:
        response = client.post("/auth/signup", json={
            "full_name": "Amir Nabulsi",
            "business_name": "Nabulsi Home Goods",
            "email": email,
            "country_code": "JO",
            "primary_currency": "JOD",
            "password": "FirstCustomer!2026",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["access_token"]
        assert body["tenant_id"]
    finally:
        _cleanup_user(email)


def test_signup_rejects_a_genuinely_malformed_email_with_a_clean_400_not_a_500():
    """Defense-in-depth: any future CheckViolation on signup must come back
    as a clean 400, never an unhandled 500 (the actual shape of the bug -
    the frontend could only show a generic connection error)."""
    from src.ai.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/auth/signup", json={
        "full_name": "Test User",
        "business_name": "Test Co",
        "email": "not-an-email-at-all",
        "country_code": "JO",
        "primary_currency": "JOD",
        "password": "Str0ng!Passw0rd",
    })
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


def test_signup_sets_the_companys_own_timezone_and_currency_not_jordans():
    """companies.timezone/supported_currencies default to 'Asia/Amman'/['JOD']
    in the schema; signup never set them, so a Moroccan tenant got Amman time."""
    from src.ai.main import app

    client = TestClient(app)
    email = f"owner+{uuid.uuid4().hex[:8]}@atlas-example.ma"
    try:
        response = client.post("/auth/signup", json={
            "full_name": "Salma Idrissi", "business_name": "Atlas Couture", "email": email,
            "country_code": "MA", "primary_currency": "MAD", "password": "FirstCustomer!2026",
        })
        assert response.status_code == 200, response.text
        admin = psycopg2.connect(ADMIN_DATABASE_URL)
        with admin.cursor() as cursor:
            cursor.execute("SELECT timezone, supported_currencies FROM companies WHERE tenant_id = %s;", (response.json()["tenant_id"],))
            assert cursor.fetchone() == ("Africa/Casablanca", ["MAD"])
        admin.close()
    finally:
        _cleanup_user(email)
