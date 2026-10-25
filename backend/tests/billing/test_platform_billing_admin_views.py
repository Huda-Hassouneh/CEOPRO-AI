from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.ai.core.security import TenantContext
from src.ai.routers import platform


class _Cursor:
    def __init__(self, result):
        self.result = result
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        self.query, self.params = query, params

    def fetchone(self):
        return (self.result,)


class _Connection:
    def __init__(self, result):
        self.cursor_instance = _Cursor(result)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class _ContractCursor(_Cursor):
    def __init__(self, has_company=True, active_subscription=False):
        super().__init__(None)
        self.has_company = has_company
        self.active_subscription = active_subscription

    def fetchone(self):
        if "keel_active_principal" in self.query:
            return (True,)
        if "FROM public.companies" in self.query:
            return ("tenant-a",) if self.has_company else None
        if "FROM public.billing_subscriptions" in self.query:
            return ("active",) if self.active_subscription else None
        return None


class _ContractConnection(_Connection):
    def __init__(self, has_company=True, active_subscription=False):
        super().__init__(None)
        self.cursor_instance = _ContractCursor(has_company, active_subscription)


def _client(monkeypatch, role, connection=None):
    app = FastAPI()
    app.include_router(platform.router)
    app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext("platform-tenant", "owner-user")
    monkeypatch.setattr(platform.service, "command", lambda *_args, **_kwargs: {"role": role})
    if connection is not None:
        monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    return TestClient(app, raise_server_exceptions=False)


def test_global_billing_view_is_owner_only_before_database_connection(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("Non-owner must be rejected before database access")

    monkeypatch.setattr(platform.db, "app_role_connection", forbidden)
    with _client(monkeypatch, "admin") as client:
        response = client.get("/platform/billing/admin-views/subscriptions")
    assert response.status_code == 403


def test_owner_billing_view_uses_the_guarded_read_function_and_bounded_paging(monkeypatch):
    connection = _Connection({"subscriptions": [{"tenant_id": "tenant-a"}]})
    with _client(monkeypatch, "owner", connection) as client:
        response = client.get("/platform/billing/admin-views/subscriptions?limit=25&offset=50")

    assert response.status_code == 200
    assert response.json() == {"subscriptions": [{"tenant_id": "tenant-a"}]}
    assert connection.cursor_instance.query == "SELECT public.billing_platform_owner_read(%s,%s,%s);"
    assert connection.cursor_instance.params == ("subscriptions", 25, 50)
    assert connection.committed and connection.closed


def test_billing_read_view_rejects_out_of_range_page_size(monkeypatch):
    connection = _Connection({})
    with _client(monkeypatch, "owner", connection) as client:
        response = client.get("/platform/billing/admin-views/plans?limit=201")
    assert response.status_code == 422


def test_billing_read_migration_repeats_platform_owner_check_and_only_grants_execute():
    migration = Path(__file__).parents[2] / "src" / "infrastructure" / "database" / "migrations" / "20261102000000_platform_owner_billing_read.sql"
    source = migration.read_text(encoding="utf-8")
    assert "SECURITY DEFINER" in source
    assert "keel_active_principal(v_actor,v_tenant)" in source
    assert "m.role_key='owner'" in source
    assert "platform_disabled_at IS NOT NULL" in source
    assert "GRANT EXECUTE ON FUNCTION public.billing_platform_owner_read" in source
    assert "GRANT SELECT ON" not in source


def test_custom_contract_assignment_is_denied_to_tenant_admin_before_privileged_connection(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("Non-owner must be rejected before opening the administrative connection")

    monkeypatch.setattr(platform.db, "system_connection", forbidden)
    monkeypatch.setattr(platform.service, "command", lambda *_args, **_kwargs: {"role": "admin"})
    body = platform.CustomContractAssignment(
        tenant_id="00000000-0000-0000-0000-000000000001", contract_ref="C-1", approval_reference="approved-1",
        reason="synthetic test", limits={"tracked_products": 10},
    )
    with pytest.raises(HTTPException) as error:
        platform.assign_custom_contract(body, TenantContext("platform-tenant", "owner-user"))
    assert error.value.status_code == 403


def test_custom_contract_assignment_refuses_a_current_stripe_subscription(monkeypatch):
    connection = _ContractConnection(active_subscription=True)
    monkeypatch.setattr(platform.db, "system_connection", lambda: connection)
    monkeypatch.setattr(platform.billing_admin, "set_custom_contract", lambda **_kwargs: pytest.fail("must not assign over Stripe"))
    monkeypatch.setattr(platform.service, "command", lambda *_args, **_kwargs: {"role": "owner"})
    body = platform.CustomContractAssignment(
        tenant_id="00000000-0000-0000-0000-000000000001", contract_ref="C-1", approval_reference="approved-1",
        reason="synthetic test", limits={"tracked_products": 10},
    )
    with pytest.raises(HTTPException) as error:
        platform.assign_custom_contract(body, TenantContext("platform-tenant", "owner-user"))
    assert error.value.status_code == 409
    assert error.value.detail["reason"] == "provider_subscription_transition_required"
    assert connection.closed


def test_custom_contract_assignment_calls_audited_existing_billing_authority(monkeypatch):
    connection = _ContractConnection()
    calls = {}
    monkeypatch.setattr(platform.db, "system_connection", lambda: connection)
    monkeypatch.setattr(platform.billing_admin, "set_custom_contract", lambda _conn, **kwargs: calls.update(kwargs))
    monkeypatch.setattr(platform.service, "command", lambda *_args, **_kwargs: {"role": "owner"})
    body = platform.CustomContractAssignment(
        tenant_id="00000000-0000-0000-0000-000000000001", contract_ref="C-1", approval_reference="approved-1",
        reason="synthetic test", limits={"tracked_products": 10}, included_features=["market_intelligence"],
    )
    response = platform.assign_custom_contract(body, TenantContext("platform-tenant", "owner-user"))
    assert response["state"] == "assigned"
    assert calls["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    assert calls["approved_by"] == "owner-user"
    assert calls["reason"] == "approved-1: synthetic test"
    assert calls["limits"] == {"tracked_products": 10}
    assert connection.committed and connection.closed


def test_custom_contract_rejects_non_integer_allowances():
    # Pydantic validation is exercised through a tiny route using the same request model.
    from fastapi import APIRouter
    from src.ai.routers.platform import CustomContractAssignment

    app = FastAPI()
    router = APIRouter()

    @router.post("/contract")
    def validate_contract(body: CustomContractAssignment):
        return body.model_dump(mode="json")

    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/contract", json={
            "tenant_id": "00000000-0000-0000-0000-000000000001", "contract_ref": "C-1", "approval_reference": "approved-1",
            "reason": "test", "limits": {"tracked_products": 1.5},
        })
    assert response.status_code == 422
