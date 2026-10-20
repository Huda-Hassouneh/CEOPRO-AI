"""Execute the exact route AST, with an inference double, without AI imports.

This is isolated HTTP authorization coverage, not full model-server execution.
"""

import ast
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from scripts.billing_verification import BACKEND
from src.ai import db
from src.ai.core import usage
from src.ai.core.entitlements import requires
from src.ai.core.exceptions import register_exception_handlers
from src.ai.core.security import TenantContext, get_tenant_context
from tests.integration_review.test_http_database import headers


@pytest.mark.parametrize("state", ["inactive", "missing-module", "included"])
def test_exact_forecast_route_gate(
    owner_db, assigned, test_price, billing_connections, state
):
    tid, _ = assigned
    with owner_db.cursor() as cur:
        if state == "inactive":
            cur.execute(
                "UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",
                (tid,),
            )
        else:
            cur.execute(
                "UPDATE tenant_plan_assignments SET plan_key=%s WHERE tenant_id=%s",
                (test_price[0] if state == "missing-module" else "growth", tid),
            )
    source = BACKEND / "src/ai/routers/dashboard.py"
    tree = ast.parse(source.read_text())
    handler = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name == "dashboard_generate_product_forecast_endpoint"
    )
    router = APIRouter(prefix="/dashboard")
    calls = []
    body = {"status": "UNKNOWN", "reason": "NO_HISTORY"}

    def work(*args):
        calls.append(args)
        return body

    namespace = {
        "router": router,
        "Depends": Depends,
        "HTTPException": HTTPException,
        "TenantContext": TenantContext,
        "get_tenant_context": get_tenant_context,
        "db": db,
        "usage": usage,
        "requires": requires,
        "get_product": lambda *args: {"product_id": "fixture"},
        "forecasting_pipeline": SimpleNamespace(run_forecast=work),
    }
    exec(  # noqa: S102 -- exact trusted repository AST, no user input
        compile(ast.Module(body=[handler], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    with TestClient(app) as client:
        result = client.post(
            "/dashboard/products/fixture/forecast", headers=headers(assigned)
        )
    if state == "included":
        assert result.status_code == 200 and result.json() == body and len(calls) == 1
    else:
        assert result.status_code == 402 and calls == []
        assert result.json()["detail"]["reason"] == (
            "SUBSCRIPTION_INACTIVE" if state == "inactive" else "NOT_INCLUDED"
        )
