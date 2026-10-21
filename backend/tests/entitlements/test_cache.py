"""Native database tests for shared ENT-009 entitlement cache generations."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest

from src.ai import db
from src.ai.core import entitlements


def _read_versions(tenant_id: str, user_id: str) -> tuple[int, int]:
    conn = db.app_role_connection(tenant_id, user_id)
    try:
        return entitlements._versions(conn, tenant_id)
    finally:
        conn.rollback()
        conn.close()


def test_committed_cancellation_invalidates_another_instance(
    owner_db, assigned, monkeypatch
):
    tenant_id, user_id = assigned
    first_instance_cache: dict = {}
    second_instance_cache: dict = {}
    monkeypatch.setattr(entitlements, "_cache", first_instance_cache)
    assert entitlements._plan(tenant_id, user_id)["status"] == "active"
    monkeypatch.setattr(entitlements, "_cache", second_instance_cache)
    assert entitlements._plan(tenant_id, user_id)["status"] == "active"

    with owner_db.cursor() as cursor:
        cursor.execute(
            "UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",
            (tenant_id,),
        )

    for instance_cache in (first_instance_cache, second_instance_cache):
        monkeypatch.setattr(entitlements, "_cache", instance_cache)
        assert entitlements._plan(tenant_id, user_id)["status"] == "cancelled"


def test_committed_plan_change_invalidates_another_instance(
    owner_db, assigned, monkeypatch
):
    tenant_id, user_id = assigned
    restricted_plan = "entver_" + uuid.uuid4().hex[:18]
    with owner_db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO usage_plans(plan_key,display_name) VALUES(%s,'Disposable ENT-009 test plan')",
            (restricted_plan,),
        )
    first_instance_cache: dict = {}
    second_instance_cache: dict = {}
    monkeypatch.setattr(entitlements, "_cache", first_instance_cache)
    initial = entitlements._plan(tenant_id, user_id)
    assert "market_intelligence" in initial["entitlements"]
    monkeypatch.setattr(entitlements, "_cache", second_instance_cache)
    assert "market_intelligence" in entitlements._plan(tenant_id, user_id)["entitlements"]

    try:
        with owner_db.cursor() as cursor:
            cursor.execute(
                "UPDATE tenant_plan_assignments SET plan_key=%s WHERE tenant_id=%s",
                (restricted_plan, tenant_id),
            )
        for instance_cache in (first_instance_cache, second_instance_cache):
            monkeypatch.setattr(entitlements, "_cache", instance_cache)
            changed = entitlements._plan(tenant_id, user_id)
            assert changed["entitlements"] == set()
    finally:
        with owner_db.cursor() as cursor:
            cursor.execute(
                "UPDATE tenant_plan_assignments SET plan_key='standard' WHERE tenant_id=%s",
                (tenant_id,),
            )
            cursor.execute("DELETE FROM usage_plans WHERE plan_key=%s", (restricted_plan,))


def test_trial_cache_expires_at_exact_timestamp_without_database_write(
    owner_db, assigned, monkeypatch
):
    tenant_id, user_id = assigned
    end = datetime.now(UTC) + timedelta(seconds=0.35)
    with owner_db.cursor() as cursor:
        cursor.execute(
            "UPDATE tenant_plan_assignments SET status='trialing',source='trial' WHERE tenant_id=%s",
            (tenant_id,),
        )
        cursor.execute(
            "INSERT INTO billing_trials(tenant_id,plan_key,started_at,ends_at) VALUES(%s,'standard',%s,%s)",
            (tenant_id, datetime.now(UTC) - timedelta(days=13), end),
        )
    initial = entitlements._plan(tenant_id, user_id)
    assert initial["status"] == "trialing"

    time.sleep(0.45)
    refreshed = entitlements._plan(tenant_id, user_id)
    assert refreshed["status"] == "expired"
    with owner_db.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM tenant_plan_assignments WHERE tenant_id=%s",
            (tenant_id,),
        )
        assert cursor.fetchone()[0] == "trialing", "expiry is derived; no write is performed"


def test_version_check_failure_does_not_serve_warmed_cache(
    assigned, monkeypatch
):
    tenant_id, user_id = assigned
    assert entitlements._plan(tenant_id, user_id)["status"] == "active"

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("version store unavailable")

    monkeypatch.setattr(db, "app_role_connection", unavailable)
    with pytest.raises(RuntimeError, match="version store unavailable"):
        entitlements._plan(tenant_id, user_id)


def test_version_rows_are_tenant_scoped_for_restricted_role(
    assigned, other_tenant, billing_connections
):
    tenant_id, user_id = assigned
    own = _read_versions(tenant_id, user_id)
    conn = billing_connections(tenant_id, user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id FROM entitlement_version_state WHERE tenant_id=%s",
                (other_tenant,),
            )
            assert cursor.fetchall() == []
            assert entitlements._versions(conn, other_tenant)[0] == 0
            cursor.execute("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cursor.fetchone() == ("ceopro_app", False, False)
        conn.rollback()
    finally:
        conn.close()
    assert own[0] > 0


def test_concurrent_assignment_updates_increment_generation_atomically(
    owner_db, assigned
):
    import psycopg2

    tenant_id, user_id = assigned
    start, _ = _read_versions(tenant_id, user_id)
    database_url = os.environ["BILLING_TEST_DATABASE_URL"]
    errors: list[str] = []

    def update(index: int) -> None:
        connection = psycopg2.connect(database_url, connect_timeout=5)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE tenant_plan_assignments SET current_period_end=%s WHERE tenant_id=%s",
                    (datetime.now(UTC).date() + timedelta(days=index + 2), tenant_id),
                )
            connection.commit()
        except Exception as exc:  # collected for assertion in the test thread
            connection.rollback()
            errors.append(type(exc).__name__)
        finally:
            connection.close()

    workers = [threading.Thread(target=update, args=(index,)) for index in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert not any(worker.is_alive() for worker in workers)
    assert errors == []
    end, _ = _read_versions(tenant_id, user_id)
    assert end == start + 4


def test_catalog_change_advances_shared_generation(owner_db, assigned):
    tenant_id, user_id = assigned
    before = _read_versions(tenant_id, user_id)[1]
    key = "entver_" + uuid.uuid4().hex[:18]
    with owner_db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO usage_plans(plan_key,display_name) VALUES(%s,'Disposable generation test')",
            (key,),
        )
    after_insert = _read_versions(tenant_id, user_id)[1]
    assert after_insert == before + 1
    with owner_db.cursor() as cursor:
        cursor.execute("DELETE FROM usage_plans WHERE plan_key=%s", (key,))
    assert _read_versions(tenant_id, user_id)[1] > after_insert


def test_override_change_advances_tenant_generation(owner_db, assigned):
    tenant_id, user_id = assigned
    before, _ = _read_versions(tenant_id, user_id)
    with owner_db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenant_entitlement_overrides(tenant_id,feature_code,limit_value,contract_ref,approved_by,reason) "
            "VALUES(%s,'tracked_products',0,'entver-test','test','generation test')",
            (tenant_id,),
        )
    after_insert, _ = _read_versions(tenant_id, user_id)
    assert after_insert == before + 1
    with owner_db.cursor() as cursor:
        cursor.execute(
            "DELETE FROM tenant_entitlement_overrides WHERE tenant_id=%s AND feature_code='tracked_products'",
            (tenant_id,),
        )
    assert _read_versions(tenant_id, user_id)[0] == after_insert + 1
