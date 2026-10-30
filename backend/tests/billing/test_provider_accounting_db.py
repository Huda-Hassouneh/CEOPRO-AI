"""Owner HTTP -> shared set_price -> restricted SQL -> synthetic Data settlement."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import errors

from src.ai.billing import credits
from src.ai.core.security import TenantContext
from src.ai.routers import platform

URL = "/platform/billing/provider-accounting"


def price(**changes):
    return dict(budget_kind="data", provider="synthetic_" + uuid4().hex[:16], operation="search", unit="request",
                unit_cost_usd="0.000123456789", safety_margin="0.15", charged_on_failure=True,
                cost_is_final=True, source="SYNTHETIC provider invoice", verified_at=date.today().isoformat(),
                reason="SYNTHETIC disposable verification", **changes)


@pytest.fixture
def owner_client(billing_connections, platform_owner_context):
    app = FastAPI()
    app.include_router(platform.router)
    app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext(*platform_owner_context)
    with TestClient(app) as client:
        yield client, app


def rows(conn, query, args=()):
    with conn.cursor() as cursor:
        cursor.execute(query, args)
        return cursor.fetchall()


def test_owner_save_read_audit_and_custom_pricing_separation(owner_client, owner_db, platform_owner_context):
    client, _ = owner_client
    before = rows(owner_db, "SELECT row_to_json(r) FROM billing_custom_cost_rates r")
    body = price()
    first = client.put(URL, json=body)
    assert first.status_code == 200, first.text
    listed = client.get(URL)
    assert listed.status_code == 200
    saved = next(r for r in listed.json()["schedules"] if r["provider"] == body["provider"])
    assert Decimal(saved["unit_cost_usd"]) == Decimal(body["unit_cost_usd"])
    assert saved["configured_by"] == platform_owner_context[1]
    assert saved["reason"] == body["reason"]
    body.update(unit_cost_usd="0", charged_on_failure=False, cost_is_final=False, safety_margin=None)
    assert client.put(URL, json=body).status_code == 200
    audits = rows(owner_db, "SELECT old_value,new_value,approved_by,reason FROM entitlement_audit_log "
                 "WHERE action='set_price' AND subject=%s ORDER BY created_at",
                 (f"data:{body['provider']}:search:request",))
    assert len(audits) == 2 and audits[0][0] is None
    assert audits[1][0]["unit_cost_usd"] == float(Decimal("0.000123456789"))
    assert audits[1][1]["charged_on_failure"] is False and audits[1][1]["cost_is_final"] is False
    assert audits[1][2:] == (platform_owner_context[1], body["reason"])
    assert rows(owner_db, "SELECT row_to_json(r) FROM billing_custom_cost_rates r") == before


@pytest.mark.parametrize("field,value", [
    ("budget_kind", "invalid"), ("provider", " "), ("operation", ""), ("unit", "invalid"),
    ("unit_cost_usd", "-0.01"), ("unit_cost_usd", "NaN"), ("unit_cost_usd", "0.0000000000001"),
    ("unit_cost_usd", "100000000"), ("safety_margin", "2.01"), ("charged_on_failure", "false"),
    ("source", " "), ("reason", ""), ("verified_at", None),
])
def test_invalid_prices_are_rejected(owner_client, field, value):
    client, _ = owner_client
    body = price()
    body[field] = value
    assert client.put(URL, json=body).status_code == 422


@pytest.mark.parametrize("role", ["owner", "admin", "staff"])
def test_tenant_roles_cannot_read_or_write(owner_client, tenant, owner_db, role):
    client, app = owner_client
    rows(owner_db, "UPDATE tenant_users SET role_key=%s WHERE tenant_id=%s RETURNING user_id", (role, tenant[0]))
    app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext(*tenant)
    assert client.get(URL).status_code == 403
    assert client.put(URL, json=price()).status_code == 403


def test_unauthenticated_access_rejected(owner_client):
    client, app = owner_client
    app.dependency_overrides.clear()
    assert client.get(URL).status_code == 401
    assert client.put(URL, json=price()).status_code == 401


def test_restricted_password_owner_login(owner_db, platform_owner_context):
    """Also exercise the real ceopro_app password path, without SET ROLE fixtures."""
    from src.ai import db
    conn = db.app_role_connection(*platform_owner_context)
    try:
        assert rows(conn, "SELECT current_user")[0][0] == "ceopro_app"
        listed = rows(conn, "SELECT public.billing_provider_accounting('list')")[0][0]
        assert isinstance(listed, list)
    finally:
        conn.close()


def test_inactive_owner_and_direct_sql_cannot_bypass(owner_client, owner_db, platform_owner_context, billing_connections, tenant):
    client, _ = owner_client
    uid = platform_owner_context[1]
    try:
        rows(owner_db, "UPDATE users SET platform_disabled_at=NOW() WHERE user_id=%s RETURNING user_id", (uid,))
        assert client.get(URL).status_code == 403
        assert client.put(URL, json=price()).status_code == 403
    finally:
        rows(owner_db, "UPDATE users SET platform_disabled_at=NULL WHERE user_id=%s RETURNING user_id", (uid,))
    conn = billing_connections(*tenant)
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            rows(conn, "SELECT public.billing_provider_accounting('list')")
        conn.rollback()
        with pytest.raises(errors.InsufficientPrivilege):
            rows(conn, "UPDATE provider_cost_schedules SET unit_cost_usd=0")
    finally:
        conn.close()


def test_brave_http_price_drives_data_only_settlement(owner_client, owner_db, tenant, monkeypatch):
    from src.market_scraper.provider_billing import metered_request
    client, _ = owner_client
    body = price()
    body.update(provider="brave_search", unit_cost_usd="0.03", safety_margin="0")
    # The disposable DB is shared with other tests: restore this known schedule
    # afterwards, retaining immutable synthetic ledger/audit evidence.
    old = rows(owner_db, "SELECT unit_cost_usd,safety_margin,charged_on_failure,cost_is_final,source,verified_at,configured_by "
               "FROM provider_cost_schedules WHERE budget_kind='data' AND provider='brave_search' AND operation='search' AND unit='request'")[0]
    custom_before = rows(owner_db, "SELECT row_to_json(r) FROM billing_custom_cost_rates r")
    today = date.today()
    rows(owner_db, "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source) "
         "VALUES(%s,'starter','active',%s,%s,'manual') RETURNING tenant_id", (tenant[0], today.replace(day=1), today + timedelta(days=30)))
    monkeypatch.delenv("KEEL_TEST_DISABLE_METERING", raising=False)
    before_ai = rows(owner_db, "SELECT row_to_json(r) FROM tenant_credit_balances r WHERE tenant_id=%s AND budget_kind='ai'", (tenant[0],))
    try:
        assert client.put(URL, json=body).status_code == 200
        schedule = credits.schedule(owner_db, "data", "brave_search", "search")
        assert schedule["request"]["cost"] == Decimal("0.03")
        sent = []
        def send():
            sent.append(1)
            reserved = rows(owner_db, "SELECT reserved_credits FROM tenant_credit_balances WHERE tenant_id=%s AND budget_kind='data'", (tenant[0],))[0][0]
            assert reserved > 0
            return {"web": {"results": []}}
        with credits.metering(tenant[0], "assistant_question", actor_user_id=tenant[1]):
            metered_request("https://api.search.brave.com/res/v1/web/search", send)
        assert sent == [1]
        ledger = rows(owner_db, "SELECT status,measured_units,actual_cost_usd,consumed_credits FROM usage_ledger WHERE tenant_id=%s AND budget_kind='data'", (tenant[0],))
        value = credits.policy(owner_db)["credit_usd_value"]
        expected = credits._to_credits(Decimal("0.03"), value)
        assert ledger == [("consumed", {"request": 1}, Decimal("0.03"), expected)]
        assert rows(owner_db, "SELECT reserved_credits,consumed_credits,consumed_cost_usd FROM tenant_credit_balances WHERE tenant_id=%s AND budget_kind='data'", (tenant[0],)) == [(0, expected, Decimal("0.03"))]
        assert rows(owner_db, "SELECT row_to_json(r) FROM tenant_credit_balances r WHERE tenant_id=%s AND budget_kind='ai'", (tenant[0],)) == before_ai
        assert rows(owner_db, "SELECT row_to_json(r) FROM billing_custom_cost_rates r") == custom_before
    finally:
        rows(owner_db, "UPDATE provider_cost_schedules SET unit_cost_usd=%s,safety_margin=%s,charged_on_failure=%s,cost_is_final=%s,source=%s,verified_at=%s,configured_by=%s "
             "WHERE budget_kind='data' AND provider='brave_search' AND operation='search' AND unit='request' RETURNING schedule_id", old)
