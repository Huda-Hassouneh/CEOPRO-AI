from copy import deepcopy
from datetime import date
from types import SimpleNamespace

from src.ai.routers import billing


class _Connection:
    def __init__(self, role="owner"):
        self.role = role
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _query, _params=None):
        pass

    def fetchone(self):
        return (self.role,)

    def commit(self):
        pass

    def close(self):
        self.closed = True


def _plan():
    return {
        "plan_key": "growth",
        "display_name": "Plus",
        "status": "active",
        "assigned": True,
        "source": "stripe",
        "period_code": "monthly",
        "period_start": date(2026, 10, 1),
        "period_end": date(2026, 10, 31),
        "trial_ends_at": None,
        "entitlements": ["market_intelligence", "competitor_management"],
        "features": {
            "rag_assistant": {
                "unit": "tokens", "aggregation_type": "sum",
                "reset_cycle": "billing_period", "limit": 500,
            },
            "tracked_competitors": {
                "unit": "competitors", "aggregation_type": "max",
                "reset_cycle": "lifetime", "limit": None,
            },
            "document_storage_mb": {
                "unit": "mb", "aggregation_type": "max",
                "reset_cycle": "lifetime", "limit": 0,
            },
            "connected_data_sources": {
                "unit": "sources", "aggregation_type": "max",
                "reset_cycle": "lifetime", "limit": 5,
            },
        },
    }


def test_subscription_exposes_versioned_established_rights_without_changing_existing_fields(monkeypatch):
    tenant_id = "tenant-b2"
    user_id = "user-b2"
    plan = _plan()
    original_plan = deepcopy(plan)
    app_conn = _Connection()
    system_conn = _Connection()
    calls = {"plan": [], "credits": 0, "current_usage": 0}
    legacy_features = [{
        "feature_code": "tracked_products", "limit": 250, "current_usage": 7,
    }]
    legacy_credits = {"data": {"limit": 10, "used": 2}}

    monkeypatch.setattr(
        billing.db, "app_role_connection",
        lambda actual_tenant, actual_user: (
            app_conn if (actual_tenant, actual_user) == (tenant_id, user_id)
            else (_ for _ in ()).throw(AssertionError("wrong tenant connection"))
        ),
    )
    monkeypatch.setattr(billing.db, "system_connection", lambda: system_conn)
    monkeypatch.setattr(
        billing.usage, "get_plan",
        lambda _conn, actual_tenant: calls["plan"].append(actual_tenant) or plan,
    )
    monkeypatch.setattr(
        billing.usage, "current_usage",
        lambda _conn, actual_tenant, actual_plan: (
            calls.__setitem__("current_usage", calls["current_usage"] + 1) or legacy_features
        ) if (actual_tenant == tenant_id and actual_plan is plan)
        else (_ for _ in ()).throw(AssertionError("current usage used another tenant/plan")),
    )
    monkeypatch.setattr(billing.store, "current_subscription", lambda _conn, _tenant: None)
    monkeypatch.setattr(billing.store, "trial", lambda _conn, _tenant: None)
    monkeypatch.setattr(billing.store, "customer_id", lambda _conn, _tenant: None)
    monkeypatch.setattr(billing.store, "trial_eligibility", lambda *_args: None)
    monkeypatch.setattr(billing.credits, "summary", lambda _conn, _tenant: calls.__setitem__("credits", calls["credits"] + 1) or legacy_credits)
    monkeypatch.setattr(billing.config, "payments_enabled", lambda: False)

    result = billing.get_subscription(SimpleNamespace(tenant_id=tenant_id, user_id=user_id))

    rights = result["effectiveRights"]
    assert rights["version"] == 1
    assert rights["basis"] == "configured_plan"
    items = {item["featureCode"]: item for item in rights["items"]}
    assert set(items) == {
        "market_intelligence", "demand_prediction", "competitor_management",
        "sentiment_analysis", "rag_assistant", "document_extraction",
        "marketing_image_generation", "tracked_competitors", "tracked_products",
        "connected_data_sources", "document_storage_mb",
    }
    assert items["market_intelligence"]["state"] == "enabled"
    assert items["demand_prediction"]["state"] == "disabled"
    assert items["tracked_products"]["state"] == "absent"
    assert items["document_storage_mb"]["state"] == "explicit_zero"
    assert items["document_storage_mb"]["limit"] == 0
    assert items["document_storage_mb"]["unit"] == "mb"
    assert items["rag_assistant"]["state"] == "limited"
    assert items["rag_assistant"]["limit"] == 500
    assert items["rag_assistant"]["unit"] == "tokens"
    assert items["tracked_competitors"]["state"] == "unlimited"
    assert items["tracked_competitors"]["limit"] is None
    assert items["connected_data_sources"]["aggregationType"] == "max"
    assert "market_perception" not in items
    assert "report_generation" not in items
    assert "team_members" not in items
    assert "ai_credits" not in items and "data_credits" not in items and "web_searches" not in items

    # Existing response fields and converted billing-page values are preserved.
    assert result["planId"] == "growth"
    assert result["hasAccess"] is True
    assert result["limits"] == {"products": 250}
    assert result["usage"] == {"products": 7}
    assert result["features"] is legacy_features
    assert result["credits"] is legacy_credits
    assert result["entitlements"] == plan["entitlements"]

    # One tenant-scoped plan read supplies both the legacy response and B1 projection.
    assert calls["plan"] == [tenant_id]
    assert calls["current_usage"] == 1
    assert calls["credits"] == 1
    assert plan == original_plan
    assert app_conn.closed and system_conn.closed
    assert "tenant_id" not in rights
