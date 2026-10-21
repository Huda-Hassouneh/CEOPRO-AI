"""Read-only, tenant-scoped pricing history over existing evidence tables."""
import json
import os
import uuid

import psycopg2
import pytest
from fastapi import HTTPException

from src.ai import db
from src.ai.core.security import TenantContext
from src.ai.pricing import pipeline
from src.ai.routers.pricing import pricing_recommendation_history

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    yield connection
    connection.rollback()
    connection.close()


def _tenant_product(conn, label):
    tenant_id, user_id, product_id = (str(uuid.uuid4()) for _ in range(3))
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) VALUES (%s, %s, 'JO', 'JOD')",
            (tenant_id, label),
        )
        cursor.execute(
            "INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, 'test-hash')",
            (user_id, f"pricing-history-{user_id}@example.com"),
        )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (%s, %s, 'owner')",
            (tenant_id, user_id),
        )
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) VALUES (%s, %s, %s, 25, 'JOD')",
            (product_id, tenant_id, json.dumps({"en": "History product"})),
        )
    conn.commit()
    return tenant_id, user_id, product_id


def test_history_is_paginated_and_tenant_scoped_under_restricted_role(conn):
    tenant_id, user_id, product_id = _tenant_product(conn, "Pricing History Owner")
    other_tenant, _, other_product = _tenant_product(conn, "Other Pricing History Owner")
    for _ in range(3):
        result = pipeline.run_price_recommendation(conn, tenant_id, product_id)
        assert result["status"] == "OK"
    foreign_result = pipeline.run_price_recommendation(conn, other_tenant, other_product)
    assert foreign_result["status"] == "OK"

    app_conn = db.app_role_connection(tenant_id, user_id)
    try:
        with app_conn.cursor() as cursor:
            cursor.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            assert cursor.fetchone() == ("ceopro_app", False, False)
        first = pricing_recommendation_history(
            product_id, limit=2, offset=0, ctx=TenantContext(tenant_id, user_id),
        )
        assert len(first["items"]) == 2
        assert first["has_more"] is True
        assert all(item["data_basis"] == "INTERNAL_ONLY" for item in first["items"])
        assert all(item["user_decision"] == "PENDING" for item in first["items"])
        assert all(item["explanation"] for item in first["items"])

        final = pricing_recommendation_history(
            product_id, limit=2, offset=2, ctx=TenantContext(tenant_id, user_id),
        )
        assert len(final["items"]) == 1
        assert final["has_more"] is False

        with pytest.raises(HTTPException) as hidden:
            pricing_recommendation_history(
                other_product, limit=20, offset=0, ctx=TenantContext(tenant_id, user_id),
            )
        assert hidden.value.status_code == 404
    finally:
        app_conn.close()

