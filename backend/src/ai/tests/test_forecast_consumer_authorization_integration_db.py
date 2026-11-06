"""Forecast service guard regressions; no queued jobs or forecast writes.

Contract tests use explicit DB answers, not a mocked authorization success.
Opt-in live cases use existing fixtures with ceopro_app and server-enforced
read-only transactions. They never seed data, run migrations or connect Redis.
"""
import logging
import os
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.ai.core import usage
from src.ai.forecasting import authorization as auth
from src.ai.forecasting import consumer as worker

TENANT = "22222222-2222-4222-8222-222222222222"
OTHER = "11111111-1111-4111-8111-111111111111"
PRODUCT = "33333333-3333-4333-8333-333333333333"
HUMAN = "44444444-4444-4444-8444-444444444444"
SYSTEM = auth.SYSTEM_ACTOR_USER_ID
VALID = ("ceopro_app", "ceopro_app", False, False, "on", SYSTEM, TENANT, TENANT)


class Connection:
    """Explicit DB outcomes for negative contracts; not an RLS emulator."""
    def __init__(self, context=VALID, product=True, principal=True):
        self.context, self.product, self.principal = context, product, principal
        self.queries = []
        self.closed = self.rolled_back = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if "keel_active_principal" in sql:
            self.row = (self.principal,)
        elif "pg_roles" in sql:
            self.row = self.context
        elif "public.products" in sql:
            self.row = (1,) if self.product else None
        else:
            raise AssertionError("Unexpected query")

    def fetchone(self):
        return self.row

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def plan(monkeypatch):
    lookup = MagicMock(return_value={"status": "active", "entitlements": [usage.DEMAND_PREDICTION]})
    # Leave require_entitlement itself real, including its active/module checks.
    monkeypatch.setattr(usage, "get_plan", lookup)
    return lookup


def consumer():
    instance = worker.ForecastRequestConsumer.__new__(worker.ForecastRequestConsumer)
    instance.actor_user_id = SYSTEM
    instance.stream_key = "unit:forecast"
    instance.group_id = "unit-group"
    return instance


def test_valid_service_checks_real_entitlement_logic_and_product(plan):
    conn = Connection()
    auth.require_forecast_service_authorization(conn, TENANT, SYSTEM, PRODUCT)
    plan.assert_called_once_with(conn, TENANT)
    assert conn.queries[-1][1] == (TENANT, PRODUCT)


@pytest.mark.parametrize("actor", [None, "", HUMAN])
def test_service_rejects_absent_or_human_actor(plan, actor):
    conn = Connection()
    with pytest.raises(HTTPException) as error:
        auth.require_forecast_service_authorization(conn, TENANT, actor, PRODUCT)
    assert error.value.status_code == 403
    assert conn.queries == []
    plan.assert_not_called()


@pytest.mark.parametrize("tenant", [None, "", "not-a-uuid"])
def test_service_rejects_invalid_event_tenant(plan, tenant):
    with pytest.raises(HTTPException) as error:
        auth.require_forecast_service_authorization(Connection(), tenant, SYSTEM, PRODUCT)
    assert error.value.status_code == 403
    plan.assert_not_called()


@pytest.mark.parametrize("index,value", [
    (0, "ceopro_billing_setup"), (1, "keel_dev_admin"), (2, True), (3, True), (4, "off"),
    (5, None), (5, HUMAN), (6, None), (6, OTHER), (7, OTHER),
])
def test_service_rejects_role_actor_or_tenant_context_mismatch(plan, index, value):
    context = list(VALID)
    context[index] = value
    with pytest.raises(HTTPException) as error:
        auth.require_forecast_service_authorization(Connection(tuple(context)), TENANT, SYSTEM, PRODUCT)
    assert error.value.status_code == 403
    plan.assert_not_called()


@pytest.mark.parametrize("state", ["suspended", "deleted"])
def test_inactive_tenant_resolution_fails_closed_before_entitlement(plan, state):
    # The database's established resolver returns NULL for either state.
    conn = Connection((*VALID[:-1], None))
    with pytest.raises(HTTPException) as error:
        auth.require_forecast_service_authorization(conn, TENANT, SYSTEM, PRODUCT)
    assert error.value.status_code == 403
    plan.assert_not_called()


def test_missing_context_row_fails_closed(plan):
    with pytest.raises(HTTPException) as error:
        auth.require_forecast_service_authorization(Connection(None), TENANT, SYSTEM, PRODUCT)
    assert error.value.status_code == 403
    plan.assert_not_called()


@pytest.mark.parametrize("status,modules,reason", [
    ("none", [], "SUBSCRIPTION_INACTIVE"),
    ("expired", [usage.DEMAND_PREDICTION], "SUBSCRIPTION_INACTIVE"),
    ("past_due", [usage.DEMAND_PREDICTION], "SUBSCRIPTION_INACTIVE"),
    ("active", [], "NOT_INCLUDED"),
])
def test_service_enforces_existing_entitlement_failures(plan, status, modules, reason):
    plan.return_value = {"status": status, "entitlements": modules}
    conn = Connection()
    with pytest.raises(usage.PlanLimitReached) as error:
        auth.require_forecast_service_authorization(conn, TENANT, SYSTEM, PRODUCT)
    assert error.value.reason == reason
    assert len(conn.queries) == 1  # no product read or generation after denial


@pytest.mark.parametrize("active", [True, False])
def test_human_guard_keeps_membership_and_revocation_behavior(plan, active):
    conn = Connection(principal=active)
    if active:
        auth.require_forecast_authorization(conn, TENANT, HUMAN)
        plan.assert_called_once_with(conn, TENANT)
    else:  # removed/suspended membership is rejected by keel_active_principal
        with pytest.raises(HTTPException) as error:
            auth.require_forecast_authorization(conn, TENANT, HUMAN)
        assert error.value.status_code == 403
        plan.assert_not_called()
    assert conn.queries[0][1] == (HUMAN, TENANT)


@pytest.mark.parametrize("configured", [None, "", HUMAN, "not-a-uuid"])
def test_constructor_rejects_unconfigured_or_non_system_identity(monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("AI_SERVICE_ACTOR_USER_ID", raising=False)
    else:
        monkeypatch.setenv("AI_SERVICE_ACTOR_USER_ID", configured)
    redis = MagicMock()
    monkeypatch.setattr(worker, "get_redis_client", redis)
    with pytest.raises(RuntimeError, match="AI_SERVICE_ACTOR_USER_ID"):
        worker.ForecastRequestConsumer()
    redis.assert_not_called()


def test_constructor_accepts_explicit_system_identity_without_real_redis(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_ACTOR_USER_ID", SYSTEM)
    client = MagicMock()
    monkeypatch.setattr(worker, "get_redis_client", lambda **kwargs: client)
    instance = worker.ForecastRequestConsumer()
    assert instance.actor_user_id == SYSTEM
    client.xgroup_create.assert_called_once_with(instance.stream_key, instance.group_id, id="0", mkstream=True)


def test_foreign_or_deleted_product_never_reaches_generation(plan, monkeypatch):
    conn = Connection(product=False)
    monkeypatch.setattr(worker, "app_role_connection", lambda *args: conn)
    generate = MagicMock()
    monkeypatch.setattr(worker, "generate_or_reuse_forecast", generate)
    with pytest.raises(HTTPException) as error:
        consumer()._handle_message({"tenant_id": TENANT, "product_id": PRODUCT})
    assert error.value.status_code == 404
    generate.assert_not_called()
    assert conn.closed and conn.rolled_back


def test_callback_revalidates_changed_context_before_persistence(plan, monkeypatch):
    conn = Connection()
    monkeypatch.setattr(worker, "app_role_connection", lambda *args: conn)
    def generate(*args, authorization_check):
        conn.context = (*VALID[:-1], None)
        authorization_check()
        pytest.fail("must reject before persistence")
    monkeypatch.setattr(worker, "generate_or_reuse_forecast", generate)
    with pytest.raises(HTTPException) as error:
        consumer()._handle_message({"tenant_id": TENANT, "product_id": PRODUCT})
    assert error.value.status_code == 403
    assert conn.closed and conn.rolled_back


class MemoryQueue:
    """No Redis connection or submitted job; only the bounded wrapper contract."""
    def __init__(self):
        self.attempts, self.acked, self.dead, self.deleted = 0, [], [], []

    def hincrby(self, *args):
        self.attempts += 1
        return self.attempts

    def xack(self, *args):
        self.acked.append(args[-1])

    def xadd(self, stream, payload):
        self.dead.append((stream, payload))

    def hdel(self, *args):
        self.deleted.append(args[-1])


def test_authorization_denial_preserves_bounded_retries_and_dead_letter(plan, monkeypatch):
    instance = consumer()
    instance.client = MemoryQueue()
    monkeypatch.setattr(worker, "app_role_connection", lambda *args: Connection(None))
    generate = MagicMock()
    monkeypatch.setattr(worker, "generate_or_reuse_forecast", generate)
    for attempt in range(worker.MAX_ATTEMPTS):
        instance._process_message("unit-1", {"tenant_id": TENANT, "product_id": PRODUCT})
        assert len(instance.client.acked) == int(attempt + 1 == worker.MAX_ATTEMPTS)
    generate.assert_not_called()
    assert len(instance.client.dead) == 1
    stream, payload = instance.client.dead[0]
    assert stream == worker.DEAD_STREAM
    assert payload["attempts"] == str(worker.MAX_ATTEMPTS)
    assert payload["original_message_id"] == "unit-1"


def test_authorized_success_acknowledges_with_system_attribution(plan, monkeypatch, caplog):
    instance = consumer()
    instance.client = MemoryQueue()
    conn = Connection()
    monkeypatch.setattr(worker, "app_role_connection", lambda *args: conn)
    def generate(*args, authorization_check):
        authorization_check()
        return {"forecast_id": "unit-result", "reused": False}
    monkeypatch.setattr(worker, "generate_or_reuse_forecast", generate)
    monkeypatch.setattr(worker, "regenerate_all_structured_summaries", lambda *args: None)
    monkeypatch.setattr(worker, "minio_client", lambda: None)
    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        instance._process_message("unit-1", {"tenant_id": TENANT, "product_id": PRODUCT})
    assert instance.client.acked == instance.client.deleted == ["unit-1"]
    assert instance.client.dead == []
    assert "forecast_id=unit-result" in caplog.text
    assert "Message unit-1 processed and acknowledged actor=" + SYSTEM in caplog.text
    assert HUMAN not in caplog.text
    assert conn.closed and not conn.rolled_back


# Opt-in live checks. These fixtures are deliberately read-only: existing
# acceptance data, not the mutating AI_TEST_DATABASE_URL suite infrastructure.
@pytest.fixture
def live(monkeypatch):
    import psycopg2.extensions
    from src.infrastructure.db_pool import TenantConnectionPool
    dsn = os.getenv("AI_TEST_FORECAST_AUTH_DATABASE_URL")
    names = ("TENANT_ID", "PRODUCT_ID", "USER_ID", "OTHER_TENANT_ID")
    ids = {name: os.getenv("AI_TEST_FORECAST_AUTH_" + name) for name in names}
    if not dsn or not all(ids.values()):
        pytest.skip("Explicit read-only forecast authorization database and existing fixture IDs required")
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")
    readonly_dsn = psycopg2.extensions.make_dsn(dsn, options="-c default_transaction_read_only=on")
    pool = TenantConnectionPool(readonly_dsn, minconn=1, maxconn=1)
    conn = pool.get_tenant_connection(ids["TENANT_ID"], SYSTEM)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_user,rolsuper,rolbypassrls,current_setting('transaction_read_only') "
                           "FROM pg_roles WHERE rolname=current_user")
            assert cursor.fetchone() == ("ceopro_app", False, False, "on")
            cursor.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                           "WHERE oid IN ('public.products'::regclass,'public.demand_forecasts'::regclass,"
                           "'public.evidence_records'::regclass)")
            tables = cursor.fetchall()
            assert len(tables) == 3 and all(rls and forced for _, rls, forced in tables)
    finally:
        conn.close()
    try:
        yield pool, ids
    finally:
        pool.closeall()


def test_live_entitled_system_context_and_human_principal_stay_distinct(live):
    pool, ids = live
    with pool.get_tenant_connection(ids["TENANT_ID"], SYSTEM) as conn:
        auth.require_forecast_service_authorization(conn, ids["TENANT_ID"], SYSTEM, ids["PRODUCT_ID"])
        with pytest.raises(HTTPException) as error:
            auth.require_forecast_authorization(conn, ids["TENANT_ID"], SYSTEM)
        assert error.value.status_code == 403
    with pool.get_tenant_connection(ids["TENANT_ID"], ids["USER_ID"]) as conn:
        auth.require_forecast_authorization(conn, ids["TENANT_ID"], ids["USER_ID"])


@pytest.mark.parametrize("setting,value", [
    ("app.current_user_id", ""), ("app.current_user_id", HUMAN),
    ("app.current_tenant_id", ""), ("app.current_tenant_id", OTHER),
])
def test_live_absent_or_changed_actor_tenant_is_denied(live, setting, value):
    pool, ids = live
    with pool.get_tenant_connection(ids["TENANT_ID"], SYSTEM) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT set_config(%s,%s,true)", (setting, value))
        with pytest.raises(HTTPException) as error:
            auth.require_forecast_service_authorization(conn, ids["TENANT_ID"], SYSTEM, ids["PRODUCT_ID"])
        assert error.value.status_code == 403


def test_live_foreign_or_missing_product_is_rejected(live):
    pool, ids = live
    with pool.get_tenant_connection(ids["TENANT_ID"], SYSTEM) as conn:
        with pytest.raises(HTTPException) as error:
            auth.require_forecast_service_authorization(conn, ids["TENANT_ID"], SYSTEM, PRODUCT)
        assert error.value.status_code == 404


def test_live_event_tenant_cannot_override_connection_tenant(live):
    pool, ids = live
    with pool.get_tenant_connection(ids["TENANT_ID"], SYSTEM) as conn:
        with pytest.raises(HTTPException) as error:
            auth.require_forecast_service_authorization(conn, ids["OTHER_TENANT_ID"], SYSTEM, ids["PRODUCT_ID"])
        assert error.value.status_code == 403


def test_live_sequential_pool_reuse_preserves_tenant_context_and_entitlements(live):
    pool, ids = live
    pids = []
    for tenant in (ids["TENANT_ID"], ids["OTHER_TENANT_ID"], ids["TENANT_ID"]):
        with pool.get_tenant_connection(tenant, SYSTEM) as conn:
            conn.commit()
            conn.rollback()
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid(),get_current_tenant()::text,"
                               "current_setting('app.current_user_id')")
                pid, resolved, actor = cursor.fetchone()
                assert (resolved, actor) == (tenant, SYSTEM)
                pids.append(pid)
            if tenant == ids["TENANT_ID"]:
                auth.require_forecast_service_authorization(conn, tenant, SYSTEM, ids["PRODUCT_ID"])
            else:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT count(*) FROM products WHERE tenant_id=%s AND product_id=%s",
                                   (ids["TENANT_ID"], ids["PRODUCT_ID"]))
                    assert cursor.fetchone()[0] == 0
                with pytest.raises(usage.PlanLimitReached) as error:
                    auth.require_forecast_service_authorization(conn, tenant, SYSTEM, ids["PRODUCT_ID"])
                assert error.value.reason == "SUBSCRIPTION_INACTIVE"
    assert len(set(pids)) == 1  # the same real socket was reused B -> A -> B


def test_live_nonmember_human_and_nonexistent_tenant_are_denied(live):
    pool, ids = live
    with pool.get_tenant_connection(ids["TENANT_ID"], HUMAN) as conn:
        with pytest.raises(HTTPException) as error:
            auth.require_forecast_authorization(conn, ids["TENANT_ID"], HUMAN)
        assert error.value.status_code == 403
    with pool.get_tenant_connection(OTHER, SYSTEM) as conn:
        with pytest.raises(HTTPException) as error:
            auth.require_forecast_service_authorization(conn, OTHER, SYSTEM, ids["PRODUCT_ID"])
        assert error.value.status_code == 403


def test_live_consumer_uses_real_guard_without_generation_or_summary_writes(live, monkeypatch, caplog):
    pool, ids = live
    monkeypatch.setattr(worker, "app_role_connection", pool.get_tenant_connection)
    def no_write_generation(conn, tenant, product, horizon, authorization_check):
        authorization_check()
        conn.commit()  # read-only; proves the connection rebinds the same context
        authorization_check()
        return {"forecast_id": "read-only-test", "reused": True}
    monkeypatch.setattr(worker, "generate_or_reuse_forecast", no_write_generation)
    monkeypatch.setattr(worker, "regenerate_all_structured_summaries", lambda *args: None)
    monkeypatch.setattr(worker, "minio_client", lambda: None)
    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        instance = consumer()
        for tenant in (ids["TENANT_ID"], ids["OTHER_TENANT_ID"], ids["TENANT_ID"]):
            payload = {"tenant_id": tenant, "product_id": ids["PRODUCT_ID"]}
            if tenant == ids["TENANT_ID"]:
                instance._handle_message(payload)
            else:
                with pytest.raises(usage.PlanLimitReached) as error:
                    instance._handle_message(payload)
                assert error.value.reason == "SUBSCRIPTION_INACTIVE"
    assert caplog.text.count("Forecast system execution actor=" + SYSTEM) == 2
    assert "forecast_id=read-only-test" in caplog.text
    assert ids["USER_ID"] not in caplog.text


def test_live_existing_product_api_path_retains_human_authorization(live, monkeypatch):
    from uuid import UUID
    from src.ai.core.security import TenantContext
    from src.ai.routers import dashboard
    pool, ids = live
    monkeypatch.setattr(dashboard.db, "app_role_connection", pool.get_tenant_connection)
    def no_write_generation(conn, tenant, product, authorization_check):
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.current_user_id')")
            assert cursor.fetchone()[0] == ids["USER_ID"]
        authorization_check()  # real human principal/entitlement check
        return {"status": "OK", "reused": True}
    monkeypatch.setattr(dashboard, "_generate_or_reuse_forecast", no_write_generation)
    ctx = TenantContext(tenant_id=ids["TENANT_ID"], user_id=ids["USER_ID"])
    result = dashboard.dashboard_generate_product_forecast_endpoint(UUID(ids["PRODUCT_ID"]), ctx)
    assert result == {"status": "OK", "reused": True}
