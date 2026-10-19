"""
KEEL - service setup for the operator (read-only status and a connection test).

Provider keys are set in the service's environment, never in the app. These two
endpoints are for the operator only (OPERATOR_EMAILS) and return no key value.
Everyone else gets 404, as if the screen did not exist.
"""
from fastapi import APIRouter, Depends, HTTPException

from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.market_scraper import provider_setup

router = APIRouter(prefix="/operator", tags=["operator"])


def _caller_is_operator(ctx: TenantContext) -> bool:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT email, email_verified_at FROM users WHERE user_id = %s;", (ctx.user_id,))
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return bool(row) and provider_setup.is_operator(row[0], row[1] is not None)


def require_operator(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    if not _caller_is_operator(ctx):
        raise HTTPException(status_code=404, detail="Not found.")
    return ctx


@router.get("/me")
def operator_me(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Lets the app show the Service setup tab; true only for an operator."""
    return {"is_operator": _caller_is_operator(ctx)}


@router.get("/providers")
def list_providers(_: TenantContext = Depends(require_operator)) -> dict:
    return {"providers": provider_setup.status()}


@router.post("/providers/{provider}/test")
def test_provider(provider: str, _: TenantContext = Depends(require_operator)) -> dict:
    if provider not in provider_setup.PROVIDERS:
        raise HTTPException(status_code=404, detail="Not found.")
    return {"provider": provider, "result": provider_setup.test_connection(provider)}
