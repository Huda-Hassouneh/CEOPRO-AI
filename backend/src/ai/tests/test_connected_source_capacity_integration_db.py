"""Native HTTP verification for connected-source capacity races."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import psycopg2
import pytest

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and APP_DB_PASSWORD are required for native B4 verification",
)


def _create_tenant(conn, label: str, *, full: bool = False) -> tuple[str, str]:
    from src.ai.core.security import create_access_token

    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id,business_name,country_code,primary_currency) "
            "VALUES (%s,%s,'JO','JOD')",
            (tenant_id, f"B4 {label}"),
        )
        cursor.execute(
            "INSERT INTO users (user_id,email,password_hash,full_name,email_verified_at) "
            "VALUES (%s,%s,'not-a-login-password',%s,NOW())",
            (user_id, f"b4-{label}-{user_id}@example.test", f"B4 {label}"),
        )
        cursor.execute(
            "INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,'owner')",
            (tenant_id, user_id),
        )
        cursor.execute(
            "INSERT INTO tenant_plan_assignments (tenant_id,plan_key,status,source) "
            "VALUES (%s,'starter','active','manual')",
            (tenant_id,),
        )
        if full:
            cursor.execute(
                "INSERT INTO data_sources (tenant_id,source_name,source_type,is_active) "
                "VALUES (%s,'Existing B4 connector','OWN_SYSTEM_CONNECTOR',TRUE)",
                (tenant_id,),
            )
        else:
            # A one-time upload is not a persistent source and must not consume
            # the connected-source allowance.
            cursor.execute(
                "INSERT INTO data_sources (tenant_id,source_name,source_type,is_active) "
                "VALUES (%s,'Existing B4 upload','CSV_UPLOAD',TRUE)",
                (tenant_id,),
            )
    token, _ = create_access_token(tenant_id, user_id, email_verified=True)
    return tenant_id, user_id, token


def _tenant_records(conn, tenant_ids: list[str], tables: tuple[str, ...]) -> dict:
    snapshot = {}
    with conn.cursor() as cursor:
        for table in tables:
            cursor.execute(
                f"SELECT to_jsonb(row_data) FROM {table} AS row_data "
                "WHERE tenant_id = ANY(%s::uuid[]) ORDER BY to_jsonb(row_data)::text",
                (tenant_ids,),
            )
            snapshot[table] = [row[0] for row in cursor.fetchall()]
    return snapshot


def test_twelve_authenticated_requests_compete_for_one_source_slot(
    monkeypatch,
):
    """One real connector registration may take the tenant's final source slot."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ai import db
    from src.ai.core.exceptions import register_exception_handlers
    from src.ai.routers import onboarding

    monkeypatch.setenv("APP_DB_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("APP_DB_POOL_MAX_SIZE", "20")
    db.close_pool()

    # This B4 test targets capacity and tenant scoping. Avoid DNS/network
    # access while leaving the authenticated HTTP route and DB work real.
    monkeypatch.setattr(onboarding, "_check_target", lambda _target: None)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(onboarding.router)

    admin = psycopg2.connect(DATABASE_URL, connect_timeout=5, gssencmode="disable", sslmode="disable")
    tenant_ids: list[str] = []
    try:
        with admin.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_setting('server_version_num')::int")
            database_name, version_num = cursor.fetchone()
            assert database_name == "keel_billing_test"
            assert version_num >= 170000
            cursor.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='ceopro_app'"
            )
            assert cursor.fetchone() == (False, False)

        full_tenant, full_user, full_token = _create_tenant(admin, "full", full=True)
        race_tenant, race_user, race_token = _create_tenant(admin, "race")
        tenant_ids = [full_tenant, race_tenant]
        admin.commit()

        # Verify both configured Starter limits are one and the source count is
        # the existing OWN_SYSTEM_CONNECTOR-only contract.
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT a.tenant_id, l.limit_value FROM tenant_plan_assignments a "
                "JOIN usage_plan_limits l ON l.plan_key=a.plan_key "
                "WHERE a.tenant_id=ANY(%s::uuid[]) AND l.feature_code='connected_data_sources'",
                (tenant_ids,),
            )
            limits = {str(tenant_id): limit for tenant_id, limit in cursor.fetchall()}
            cursor.execute(
                "SELECT tenant_id, COUNT(*) FROM data_sources "
                "WHERE tenant_id=ANY(%s::uuid[]) AND is_active=TRUE "
                "AND source_type='OWN_SYSTEM_CONNECTOR' GROUP BY tenant_id",
                (tenant_ids,),
            )
            counts = {str(tenant_id): count for tenant_id, count in cursor.fetchall()}
        assert limits == {full_tenant: 1, race_tenant: 1}
        assert counts == {full_tenant: 1}

        billing_tables = (
            "tenant_plan_assignments",
            "billing_subscriptions",
            "billing_trials",
            "billing_customers",
            "billing_payments",
            "tenant_usage_counters",
            "tenant_credit_balances",
            "usage_ledger",
            "usage_ledger_adjustments",
        )
        before = _tenant_records(admin, tenant_ids, billing_tables)
        admin.commit()

        # A tenant already at capacity cannot affect the other tenant's slot.
        with TestClient(app) as full_client:
            full_response = full_client.post(
                "/onboarding/connect/api",
                json={
                    "source_name": "B4 full tenant attempt",
                    "base_url": "https://connector.example.test",
                    "field_mapping": {},
                },
                headers={"Authorization": f"Bearer {full_token}"},
            )
        assert full_response.status_code == 402, full_response.text
        assert full_response.json()["detail"]["reason"] == "CAPACITY_REACHED"

        barrier = threading.Barrier(12)

        def submit(index: int):
            payload = {
                "source_name": f"B4 race connector {index}",
                "base_url": "https://connector.example.test",
                "field_mapping": {},
            }
            with TestClient(app) as client:
                barrier.wait(timeout=30)
                response = client.post(
                    "/onboarding/connect/api",
                    json=payload,
                    headers={"Authorization": f"Bearer {race_token}"},
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(submit, range(12)))

        succeeded = [(status, body) for status, body in results if status == 200]
        rejected = [(status, body) for status, body in results if status != 200]
        assert len(succeeded) == 1, results
        assert len(rejected) == 11, results
        assert all(status == 402 for status, _ in rejected), rejected
        assert all(body["detail"]["reason"] == "CAPACITY_REACHED" for _, body in rejected), rejected
        assert succeeded[0][1]["source_id"]

        # Failed attempts did not insert records; the other tenant's existing
        # full slot remains unchanged.
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id, source_type, COUNT(*) FROM data_sources "
                "WHERE tenant_id=ANY(%s::uuid[]) GROUP BY tenant_id,source_type",
                (tenant_ids,),
            )
            rows = {(str(tid), source_type): count for tid, source_type, count in cursor.fetchall()}
        assert rows == {
        (full_tenant, "OWN_SYSTEM_CONNECTOR"): 1,
        (race_tenant, "CSV_UPLOAD"): 1,
        (race_tenant, "OWN_SYSTEM_CONNECTOR"): 1,
    }

        # The application role for the full tenant cannot read the race
        # tenant's registered source, while the race tenant can see its own.
        scoped = db.app_role_connection(full_tenant, full_user)
        try:
            with scoped.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM data_sources WHERE tenant_id=%s", (race_tenant,))
                assert cursor.fetchone()[0] == 0
        finally:
            scoped.close()
        scoped = db.app_role_connection(race_tenant, race_user)
        try:
            with scoped.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM data_sources WHERE tenant_id=%s", (race_tenant,))
                assert cursor.fetchone()[0] == 2  # own CSV upload plus one connector
        finally:
            scoped.close()

        assert _tenant_records(admin, tenant_ids, billing_tables) == before
    finally:
        db.close_pool()
        admin.rollback()
        if tenant_ids:
            with admin.cursor() as cursor:
                cursor.execute("DELETE FROM companies WHERE tenant_id=ANY(%s::uuid[])", (tenant_ids,))
            admin.commit()
        admin.close()
