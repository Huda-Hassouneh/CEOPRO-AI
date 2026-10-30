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


def test_plan_feature_mutation_requires_platform_owner_before_admin_database(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("Non-owner must be rejected before opening the administrative connection")

    monkeypatch.setattr(platform.db, "system_connection", forbidden)
    with _client(monkeypatch, "admin") as client:
        response = client.patch("/platform/billing/plans/standard/features", json={
            "feature_code": "team_seats", "included": True, "limit_value": 12,
            "reason": "synthetic authorization regression",
        })
    assert response.status_code == 403


def test_plan_feature_mutation_uses_audited_catalog_service_and_commits(monkeypatch):
    connection = _Connection(None)
    calls = {}
    monkeypatch.setattr(platform.db, "system_connection", lambda: pytest.fail("Administrative runtime access forbidden"))
    scopes = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda tid, uid: scopes.append((tid, uid)) or connection)
    monkeypatch.setattr(platform.billing_admin, "owner_catalog_command", lambda _conn, **kwargs: calls.update(kwargs) or {
        "plan_key": kwargs["plan_key"], "feature_code": kwargs["feature_code"], "included": kwargs["included"],
        "limit_value": kwargs["limit_value"], "catalog_versioned": True, "existing_assignments_preserved": True,
    })
    monkeypatch.setattr(platform.service, "command", lambda *_args, **_kwargs: {"role": "owner"})
    with _client(monkeypatch, "owner") as client:
        response = client.patch("/platform/billing/plans/standard/features", json={
            "feature_code": "team_seats", "included": True, "limit_value": 12,
            "reason": "synthetic owner catalog test",
        })
    assert response.status_code == 200
    assert response.json()["existing_assignments_preserved"] is True
    assert calls == {"plan_key": "standard", "feature_code": "team_seats", "included": True,
                     "limit_value": 12, "reason": "synthetic owner catalog test"}
    assert scopes == [("platform-tenant", "owner-user")]
    assert connection.committed and connection.closed


def test_plan_feature_mutation_rejects_boolean_as_numeric_limit(monkeypatch):
    with _client(monkeypatch, "owner") as client:
        response = client.patch("/platform/billing/plans/standard/features", json={
            "feature_code": "team_seats", "included": True, "limit_value": True,
        })
    assert response.status_code == 422


def test_plan_status_mutation_requires_platform_owner_and_calls_audited_service(monkeypatch):
    connection = _Connection(None)
    calls = {}
    monkeypatch.setattr(platform.db, "system_connection", lambda: pytest.fail("Administrative runtime access forbidden"))
    scopes = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda tid, uid: scopes.append((tid, uid)) or connection)
    monkeypatch.setattr(platform.billing_admin, "owner_catalog_command", lambda _conn, **kwargs: calls.update(kwargs) or {
        "plan_key": kwargs["plan_key"], "is_active": kwargs["active"], "existing_assignments_preserved": True,
    })
    monkeypatch.setattr(platform.service, "command", lambda *_args, **_kwargs: {"role": "owner"})
    with _client(monkeypatch, "owner") as client:
        response = client.patch("/platform/billing/plans/growth/status", json={
            "active": False, "reason": "synthetic availability regression",
        })
    assert response.status_code == 200
    assert response.json()["existing_assignments_preserved"] is True
    assert calls == {"plan_key": "growth", "active": False,
                     "reason": "synthetic availability regression"}
    assert scopes == [("platform-tenant", "owner-user")]
    assert connection.committed and connection.closed


def test_plan_status_mutation_rejects_tenant_admin_before_admin_database(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("Non-owner must be rejected before opening the administrative connection")

    monkeypatch.setattr(platform.db, "system_connection", forbidden)
    with _client(monkeypatch, "admin") as client:
        response = client.patch("/platform/billing/plans/growth/status", json={"active": False})
    assert response.status_code == 403


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


def _vendor_rate_body(**overrides):
    body = {
        "budget_kind": "ai", "provider": "synthetic-provider", "operation": "inference",
        "unit": "input_token", "unit_cost_usd": "0.00002", "source": "synthetic invoice reference",
        "verification_evidence": "Synthetic test fixture; no real rate is asserted",
        "verified_at": "2026-10-24", "effective_from": "2026-10-25T00:00:00Z",
        "policy_version_id": "00000000-0000-0000-0000-000000000001",
        "feature_code": "rag_assistant", "usage_basis": "limit_value",
        "units_per_feature_unit": "4", "operational_multiplier": "1.2",
        "variability_reserve": "1.1", "required_for_price": True,
        "usage_assumption": {},
    }
    body.update(overrides)
    return body


def test_vendor_rate_save_uses_owner_guard_and_one_atomic_rate_binding_transaction(monkeypatch):
    connection = _Connection(None)
    calls = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    monkeypatch.setattr(platform.custom_offers, "feature_catalog", lambda _conn: [{"featureCode": "document_storage_mb"}])
    monkeypatch.setattr(platform.custom_offers, "module_catalog", lambda: [])
    def command(_conn, action, payload):
        calls.append((action, payload))
        if action == "rate_create":
            return {"cost_rate_id": "rate-synthetic", "status": "verified"}
        if action == "binding_create":
            return {"binding_id": "binding-synthetic", "status": "draft"}
        raise AssertionError(action)
    monkeypatch.setattr(platform.custom_offers, "pricing_admin_command", command)
    with _client(monkeypatch, "owner") as client:
        response = client.post("/platform/billing/custom-plan-pricing/vendor-rates", json=_vendor_rate_body())
    assert response.status_code == 201
    assert response.json()["cost_rate"]["cost_rate_id"] == "rate-synthetic"
    assert response.json()["binding"]["binding_id"] == "binding-synthetic"
    assert [call[0] for call in calls] == ["rate_create", "binding_create"]
    assert calls[1][1]["cost_rate_id"] == "rate-synthetic"
    assert calls[1][1]["cost_category"] == "vendor"
    assert connection.committed and connection.closed


def test_vendor_rate_save_rolls_back_rate_when_binding_creation_fails(monkeypatch):
    connection = _Connection(None)
    calls = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    def command(_conn, action, payload):
        calls.append(action)
        if action == "rate_create":
            return {"cost_rate_id": "rate-synthetic", "status": "verified"}
        raise platform.custom_offers.CustomOfferError(422, "pricing_configuration_invalid", "invalid synthetic binding")
    monkeypatch.setattr(platform.custom_offers, "pricing_admin_command", command)
    with _client(monkeypatch, "owner") as client:
        response = client.post("/platform/billing/custom-plan-pricing/vendor-rates", json=_vendor_rate_body())
    assert response.status_code == 422
    assert calls == ["rate_create", "binding_create"]
    assert not connection.committed and connection.closed


def test_vendor_rate_save_denies_non_owner_before_database_access(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("Tenant/platform admin cannot mutate owner cost data")
    monkeypatch.setattr(platform.db, "app_role_connection", forbidden)
    with _client(monkeypatch, "admin") as client:
        response = client.post("/platform/billing/custom-plan-pricing/vendor-rates", json=_vendor_rate_body())
    assert response.status_code == 403


def test_vendor_rate_save_rejects_invalid_units_and_future_verification_dates(monkeypatch):
    connection = _Connection(None)
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    with _client(monkeypatch, "owner") as client:
        invalid_unit = client.post("/platform/billing/custom-plan-pricing/vendor-rates", json=_vendor_rate_body(unit="credits"))
        future_verification = client.post("/platform/billing/custom-plan-pricing/vendor-rates", json=_vendor_rate_body(verified_at="2999-01-01"))
    assert invalid_unit.status_code == 422
    assert future_verification.status_code == 422
    assert not connection.committed


def test_vendor_rate_with_feature_requires_a_selected_draft_policy(monkeypatch):
    with _client(monkeypatch, "owner") as client:
        response = client.post("/platform/billing/custom-plan-pricing/vendor-rates", json=_vendor_rate_body(policy_version_id=None))
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "draft_policy_required"


def _infrastructure_rate_body(**overrides):
    body = {
        "policy_version_id": "00000000-0000-0000-0000-000000000001",
        "feature_code": "document_storage_mb", "provider": "synthetic-storage",
        "operation": "object-storage", "unit": "GB-month", "unit_cost_usd": "0.0002",
        "source": "Synthetic fixture only; not a commercial rate", "verified_at": "2026-10-24",
        "effective_from": "2026-10-25T00:00:00Z", "usage_basis": "estimated_usage",
        "units_per_feature_unit": "0.001", "operational_multiplier": "1.1",
        "variability_reserve": "1.2", "required_for_price": True, "usage_assumption": {},
    }
    body.update(overrides)
    return body


def test_infrastructure_rate_save_reuses_owner_pricing_commands_atomically(monkeypatch):
    connection = _Connection(None)
    calls = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    monkeypatch.setattr(platform.custom_offers, "feature_catalog", lambda _conn: [{"featureCode": "document_storage_mb"}])
    monkeypatch.setattr(platform.custom_offers, "module_catalog", lambda: [])
    def command(_conn, action, payload):
        calls.append((action, payload))
        if action == "rate_create":
            return {"cost_rate_id": "infra-rate", "status": "verified"}
        if action == "binding_create":
            return {"binding_id": "infra-binding", "status": "draft"}
        raise AssertionError(action)
    monkeypatch.setattr(platform.custom_offers, "pricing_admin_command", command)
    with _client(monkeypatch, "owner") as client:
        response = client.post("/platform/billing/custom-plan-pricing/infrastructure-rates", json=_infrastructure_rate_body())
    assert response.status_code == 201
    assert [action for action, _ in calls] == ["rate_create", "binding_create"]
    assert calls[0][1]["budget_kind"] == "infrastructure"
    assert calls[1][1]["cost_category"] == "infrastructure"
    assert calls[1][1]["usage_basis"] == "estimated_usage"
    assert response.json()["binding"]["binding_id"] == "infra-binding"
    assert connection.committed and connection.closed


def test_infrastructure_rate_binding_failure_rolls_back_rate(monkeypatch):
    connection = _Connection(None)
    calls = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    monkeypatch.setattr(platform.custom_offers, "feature_catalog", lambda _conn: [{"featureCode": "document_storage_mb"}])
    monkeypatch.setattr(platform.custom_offers, "module_catalog", lambda: [])
    def command(_conn, action, _payload):
        calls.append(action)
        if action == "rate_create":
            return {"cost_rate_id": "infra-rate", "status": "verified"}
        raise platform.custom_offers.CustomOfferError(422, "pricing_configuration_invalid", "invalid synthetic binding")
    monkeypatch.setattr(platform.custom_offers, "pricing_admin_command", command)
    with _client(monkeypatch, "owner") as client:
        response = client.post("/platform/billing/custom-plan-pricing/infrastructure-rates", json=_infrastructure_rate_body())
    assert response.status_code == 422
    assert calls == ["rate_create", "binding_create"]
    assert not connection.committed and connection.closed


def test_infrastructure_rate_catalog_lists_only_python_bound_infrastructure_costs(monkeypatch):
    connection = _Connection(None)
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    def command(_conn, action, payload):
        if action == "rate_list":
            return {"cost_rates": [{"cost_rate_id": "infra-rate", "provider": "storage", "operation": "object-storage", "unit": "GB-month", "unit_cost_usd": "0.0002", "source": "fixture", "verified_at": "2026-10-24", "effective_from": "2026-10-25T00:00:00Z", "effective_to": None, "verification_evidence": "fixture"}]}
        if action == "policy_list":
            return {"policies": [{"policy_version_id": "policy-1", "version_number": 2, "status": "draft"}]}
        if action == "binding_list":
            return {"bindings": [
                {"binding_id": "binding-1", "policy_version_id": "policy-1", "cost_rate_id": "infra-rate", "feature_code": "document_storage_mb", "cost_category": "infrastructure", "usage_basis": "estimated_usage", "units_per_feature_unit": "0.001", "operational_multiplier": "1.1", "variability_reserve": "1.2"},
                {"binding_id": "binding-2", "policy_version_id": "policy-1", "cost_rate_id": "vendor-rate", "feature_code": "rag_assistant", "cost_category": "vendor"},
            ]}
        raise AssertionError(action)
    monkeypatch.setattr(platform.custom_offers, "pricing_admin_command", command)
    with _client(monkeypatch, "owner") as client:
        response = client.get("/platform/billing/custom-plan-pricing/infrastructure-rates")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    row = response.json()["items"][0]
    assert row["id"] == "infra-rate"
    assert row["featureId"] == "document_storage_mb"
    assert row["policy_status"] == "draft"
    assert connection.committed and connection.closed


def test_infrastructure_rate_requires_a_supported_python_feature_before_writes(monkeypatch):
    connection = _Connection(None)
    calls = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    monkeypatch.setattr(platform.custom_offers, "feature_catalog", lambda _conn: [{"featureCode": "document_storage_mb"}])
    monkeypatch.setattr(platform.custom_offers, "module_catalog", lambda: [])
    monkeypatch.setattr(platform.custom_offers, "pricing_admin_command", lambda *_args: calls.append(_args))
    with _client(monkeypatch, "owner") as client:
        response = client.post("/platform/billing/custom-plan-pricing/infrastructure-rates", json=_infrastructure_rate_body(feature_code="not_executable"))
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unsupported_feature"
    assert calls == []
    assert not connection.committed and connection.closed


def test_infrastructure_rate_requires_owner_and_timezone_safe_unit(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("Non-owner cannot access infrastructure cost data")
    monkeypatch.setattr(platform.db, "app_role_connection", forbidden)
    with _client(monkeypatch, "admin") as client:
        denied = client.post("/platform/billing/custom-plan-pricing/infrastructure-rates", json=_infrastructure_rate_body())
        bad_unit = client.post("/platform/billing/custom-plan-pricing/infrastructure-rates", json=_infrastructure_rate_body(unit="../secrets"))
    assert denied.status_code == 403
    assert bad_unit.status_code == 422


def test_feature_catalog_is_platform_owner_only_and_metadata_update_is_audited(monkeypatch):
    connection = _Connection({"features": [{"feature_code": "team_seats", "display_name": "Team seats"}]})
    calls = []
    monkeypatch.setattr(platform.db, "app_role_connection", lambda *_args: connection)
    class Cursor(_Cursor):
        def execute(self, query, params=None):
            self.query, self.params = query, params
            calls.append((query, params))
        def fetchone(self):
            return ({"feature_code": "team_seats", "display_name": "Seats", "display_name_ar": "Ø§Ù„Ù…Ù‚Ø§Ø¹Ø¯"},)
    connection.cursor_instance = Cursor(None)
    with _client(monkeypatch, "owner") as client:
        response = client.patch("/platform/billing/feature-catalog/team_seats", json={
            "name": "Seats", "name_ar": "Ø§Ù„Ù…Ù‚Ø§Ø¹Ø¯", "description": "Available seats",
            "description_ar": "Ø§Ù„Ù…Ù‚Ø§Ø¹Ø¯ Ø§Ù„Ù…ØªØ§Ø­Ø©", "reason": "Synthetic metadata test",
        })
    assert response.status_code == 200
    assert calls[0][1][0] == "update_metadata"
    assert connection.committed
    with _client(monkeypatch, "admin") as client:
        denied = client.get("/platform/billing/feature-catalog")
    assert denied.status_code == 403
