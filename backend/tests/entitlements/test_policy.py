"""Real dependency/HTTP contracts; no AI model or provider network requests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.billing import credits
from src.ai.core import entitlements, usage
from src.ai.core.exceptions import register_exception_handlers
from src.ai.core.security import TenantContext, get_tenant_context


@pytest.mark.parametrize(
    "status",
    [
        "none",
        "expired",
        "cancelled",
        "past_due",
        "payment_failed",
        "pending",
        "paused",
        "unpaid",
    ],
)
def test_inactive_module_request_is_402_before_work(monkeypatch, status):
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        "tenant-a", "user-a"
    )
    monkeypatch.setattr(
        entitlements,
        "_plan",
        lambda *args: {"status": status, "entitlements": {usage.DEMAND_PREDICTION}},
    )

    @app.post(
        "/protected", dependencies=[entitlements.requires(usage.DEMAND_PREDICTION)]
    )
    def protected():
        pytest.fail("Inactive subscription reached the work")

    result = TestClient(app).post("/protected")
    assert result.status_code == 402
    assert result.json()["detail"]["reason"] == "SUBSCRIPTION_INACTIVE"
    assert result.json()["detail"]["feature_code"] == usage.DEMAND_PREDICTION


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_included_module_respects_existing_dependency(monkeypatch, status):
    dependency = entitlements.requires(usage.DEMAND_PREDICTION).dependency
    monkeypatch.setattr(
        entitlements,
        "_plan",
        lambda *args: {"status": status, "entitlements": {usage.DEMAND_PREDICTION}},
    )
    assert dependency(TenantContext("tenant-a", "user-a")) is None


def test_absent_module_denied(monkeypatch):
    monkeypatch.setattr(
        entitlements, "_plan", lambda *args: {"status": "active", "entitlements": set()}
    )
    with pytest.raises(usage.PlanLimitReached) as error:
        entitlements.requires(usage.DEMAND_PREDICTION).dependency(
            TenantContext("a", "u")
        )
    assert error.value.reason == "NOT_INCLUDED"


def test_paid_work_fails_closed_if_accounting_connection_is_down():
    def unavailable():
        raise ConnectionError("unavailable")

    with pytest.raises(credits.BudgetError) as error:
        credits.ensure_available("tenant-a", credits.DATA, conn_factory=unavailable)
    assert error.value.reason == "ACCOUNTING_UNAVAILABLE"


def test_api_quota_error_preserves_main_contract():
    from datetime import date

    detail = usage.PlanLimitReached(
        "QUOTA_EXHAUSTED",
        usage.MONTHLY_REPORTS,
        5,
        5,
        "billing_period",
        date(2026, 10, 31),
    ).as_http()
    assert detail.status_code == 402
    assert detail.detail["remaining"] == 0
    assert detail.detail["period_end"] == "2026-10-31"
    assert "2026-11-01" in detail.detail["message"]
