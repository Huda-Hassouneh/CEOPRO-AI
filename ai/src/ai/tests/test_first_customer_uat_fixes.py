"""
Regression tests for real bugs found in the first-customer acceptance pass
(new tenant, real browser + API, 2026-10-06):

- The backend accepted a one-character password and blank full/business
  names at signup (password rules were enforced only in the browser).
- A malformed id on any {id} route (e.g. GET /products/not-a-uuid) reached
  Postgres as-is and came back as a generic 500.
- POST /pricing/recommend for an unknown product - including another
  tenant's, hidden by RLS - came back as a 500 instead of a 404.
- backend/.env.example set GROQ_MAX_TOKENS=400, overriding the tuned 1500
  default; at 400, gpt-oss-20b's hidden reasoning can consume the whole
  budget and return an empty answer.

The policy/config tests are pure; the HTTP ones use FastAPI's TestClient
with the database layer stubbed only where a test is about request
handling rather than SQL.
"""
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg2.errors
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-uat-regressions-0123456789abcdef")

from src.ai.core.security import create_access_token, ensure_password_policy  # noqa: E402
from src.ai.main import app  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[3]


# --- password policy -------------------------------------------------------

@pytest.mark.parametrize("password,missing", [
    ("a", "at least 8 characters"),
    ("alllowercase1!", "an uppercase letter"),
    ("ALLUPPERCASE1!", "a lowercase letter"),
    ("NoDigitsHere!", "a number"),
    ("NoSpecial123", "a special character"),
    ("correct horse battery staple", "an uppercase letter"),
])
def test_password_policy_rejects_each_missing_rule(password, missing):
    with pytest.raises(HTTPException) as info:
        ensure_password_policy(password)
    assert info.value.status_code == 422
    assert missing in info.value.detail


@pytest.mark.parametrize("password", ["Zaytouna#2026", "Str0ng!Passw0rd", "Argan!Atlas2026"])
def test_password_policy_accepts_passwords_the_frontend_accepts(password):
    ensure_password_policy(password)


def test_password_policy_rejects_input_bcrypt_would_silently_truncate():
    with pytest.raises(HTTPException) as info:
        ensure_password_policy("Aa1!" + "x" * 80)
    assert info.value.status_code == 422


def test_signup_rejects_a_weak_password_before_touching_the_database():
    client = TestClient(app, raise_server_exceptions=False)
    with patch("src.ai.routers.auth.db") as fake_db:
        response = client.post("/auth/signup", json={
            "email": "weak@example.com", "password": "a", "full_name": "Weak", "business_name": "Weak Co",
            "country_code": "JO", "primary_currency": "JOD",
        })
    assert response.status_code == 422
    assert "Password must contain" in response.json()["detail"]
    fake_db.app_role_connection.assert_not_called()


@pytest.mark.parametrize("full_name,business_name", [("", "Co"), ("Name", ""), ("   ", "Co"), ("Name", "   ")])
def test_signup_rejects_blank_names(full_name, business_name):
    client = TestClient(app, raise_server_exceptions=False)
    with patch("src.ai.routers.auth.db") as fake_db:
        response = client.post("/auth/signup", json={
            "email": "blank@example.com", "password": "Str0ng!Passw0rd", "full_name": full_name,
            "business_name": business_name, "country_code": "JO", "primary_currency": "JOD",
        })
    assert response.status_code == 422
    fake_db.app_role_connection.assert_not_called()


def test_reset_password_enforces_the_policy_before_consuming_a_code():
    client = TestClient(app, raise_server_exceptions=False)
    with patch("src.ai.routers.auth.db") as fake_db:
        response = client.post("/auth/password/reset", json={"email": "a@example.com", "code": "123456", "new_password": "weak"})
    assert response.status_code == 422
    fake_db.auth_lookup_connection.assert_not_called()


# --- malformed ids / unknown products ---------------------------------------

def _auth_headers():
    token, _ = create_access_token(tenant_id="11111111-1111-1111-1111-111111111111", user_id="22222222-2222-2222-2222-222222222222")
    return {"Authorization": f"Bearer {token}"}


def _connection_raising(exc):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = exc
    return conn


def test_malformed_path_id_is_a_404_not_a_500():
    client = TestClient(app, raise_server_exceptions=False)
    exc = psycopg2.errors.InvalidTextRepresentation('invalid input syntax for type uuid: "not-a-uuid"')
    with patch("src.ai.routers.products.db") as fake_db:
        fake_db.app_role_connection.return_value = _connection_raising(exc)
        response = client.get("/products/not-a-uuid", headers=_auth_headers())
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found."}


def test_malformed_body_id_is_a_422_not_a_500():
    client = TestClient(app, raise_server_exceptions=False)
    exc = psycopg2.errors.InvalidTextRepresentation('invalid input syntax for type uuid: "not-a-uuid"')
    with patch("src.ai.routers.pricing.db") as fake_db:
        fake_db.app_role_connection.return_value = _connection_raising(exc)
        response = client.post("/pricing/recommend", params={"product_id": "not-a-uuid"}, headers=_auth_headers())
    assert response.status_code == 422


def test_non_uuid_invalid_text_errors_still_surface_as_500():
    """Only bad-uuid input is a client error; any other invalid-text error is a real bug."""
    client = TestClient(app, raise_server_exceptions=False)
    exc = psycopg2.errors.InvalidTextRepresentation('invalid input syntax for type integer: "abc"')
    with patch("src.ai.routers.products.db") as fake_db:
        fake_db.app_role_connection.return_value = _connection_raising(exc)
        response = client.get("/products/abc", headers=_auth_headers())
    assert response.status_code == 500


def test_pricing_for_an_unknown_or_other_tenants_product_is_a_404():
    client = TestClient(app, raise_server_exceptions=False)
    with patch("src.ai.routers.pricing.db") as fake_db, \
            patch("src.ai.pricing.pipeline.data_access.load_own_product", return_value=None):
        fake_db.app_role_connection.return_value = MagicMock()
        response = client.post("/pricing/recommend", params={"product_id": "33333333-3333-3333-3333-333333333333"},
                               headers=_auth_headers())
    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}


# --- configuration -----------------------------------------------------------

def test_env_example_leaves_reasoning_headroom_for_the_default_llm():
    env_example = (BACKEND_ROOT / ".env.example").read_text()
    match = re.search(r"^GROQ_MAX_TOKENS=(\d+)\s*$", env_example, re.M)
    assert match, "GROQ_MAX_TOKENS must be set explicitly in .env.example"
    assert int(match.group(1)) >= 1000


# --- quick sale input validation ---------------------------------------------

@pytest.mark.parametrize("payload", [
    {"product_id": "33333333-3333-3333-3333-333333333333", "quantity": 0},
    {"product_id": "33333333-3333-3333-3333-333333333333", "quantity": -2},
    {"product_id": "33333333-3333-3333-3333-333333333333", "quantity": 1, "unit_price": -5},
])
def test_quick_sale_rejects_non_positive_quantities_and_negative_prices(payload):
    """These reached the database and failed a CHECK constraint (500)."""
    client = TestClient(app, raise_server_exceptions=False)
    with patch("src.ai.routers.sales.db") as fake_db:
        response = client.post("/sales/quick-sale", json=payload, headers=_auth_headers())
    assert response.status_code == 422
    fake_db.app_role_connection.assert_not_called()
