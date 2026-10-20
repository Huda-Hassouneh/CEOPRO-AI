"""
The shared Command Center (core/tenant_cache.py) against the real database
and the real HTTP app: a write shows on the very next screen, companies
never see each other's numbers, and the dashboard and the alerts bell share
one computation.
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from src.ai.dashboard import command_center
from src.ai.tests.signup_helpers import create_verified_test_account

pytestmark = pytest.mark.skipif(
    not os.getenv("AI_TEST_DATABASE_URL") or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB cache test",
)


@pytest.fixture
def client():
    from src.ai.main import app

    return TestClient(app)


def _company(client, name):
    session = create_verified_test_account(client, {
        "full_name": "Owner", "business_name": name, "email": f"cc+{uuid.uuid4().hex[:8]}@example.com",
        "country_code": "JO", "primary_currency": "JOD", "password": "Cache!Test-2026"})
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    product = client.post("/products", headers=headers, json={
        "product_name": {"en": f"{name} Olive Oil"}, "current_price": 8.5, "currency": "JOD"})
    assert product.status_code in (200, 201), product.text
    return headers, product.json()["product_id"]


def test_a_sale_shows_on_the_next_dashboard_load_and_stays_within_its_company(client):
    a_headers, a_product = _company(client, "Cache A")
    b_headers, _ = _company(client, "Cache B")

    before = client.get("/dashboard/command-center", headers=a_headers).json()["today"]
    b_before = client.get("/dashboard/command-center", headers=b_headers).json()["today"]
    assert before["orders"] == 0 and b_before["orders"] == 0

    sale = client.post("/sales/quick-sale", headers=a_headers, json={"product_id": a_product, "quantity": 3})
    assert sale.status_code == 200, sale.text

    after = client.get("/dashboard/command-center", headers=a_headers).json()["today"]
    assert after["orders"] == 1 and after["units"] == 3  # not the cached "before"
    assert client.get("/dashboard/command-center", headers=b_headers).json()["today"]["orders"] == 0


def test_the_dashboard_and_the_alerts_bell_share_one_computation(client, monkeypatch):
    headers, _ = _company(client, "Cache C")
    calls = []
    real = command_center.build_command_center

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(command_center, "build_command_center", counting)
    assert client.get("/dashboard/command-center", headers=headers).status_code == 200
    assert client.get("/alerts", headers=headers).status_code == 200
    assert len(calls) == 1
