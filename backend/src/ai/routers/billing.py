"""
Billing API: the plan catalog, a company's subscription and usage, Stripe
Checkout, the Stripe customer portal, plan changes, cancellation, invoices,
and the signed Stripe webhook.

Payments use Stripe-hosted pages (Checkout and the customer portal), so card
details never reach this server. When STRIPE_SECRET_KEY isn't configured the
catalog and usage still work and every payment action answers 503
`payments_not_configured` - the UI then says so instead of pretending.
"""
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from src.ai import db
from src.ai.billing import config, service, store, stripe_api, webhooks
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context

logger = logging.getLogger("APEX_BILLING")
router = APIRouter(prefix="/billing", tags=["billing"])

_BILLING_ROLES = {"owner", "admin", "accountant"}

# feature_code -> the Billing page's usage key, and a unit conversion. Only the
# owner's agreed plan terms are shown; web_searches is an internal budget.
_PAGE_KEYS = {
    usage.TRACKED_PRODUCTS: ("products", 1),
    usage.TRACKED_COMPETITORS: ("competitors", 1),
    usage.RAG_ASSISTANT: ("aiTokens", 1),
    usage.IMAGE_GENERATION: ("imageGenerations", 1),
    usage.DOCUMENT_STORAGE_MB: ("storageGb", 1 / 1024),
    usage.DOCUMENT_EXTRACTION: ("documentProcessingMb", 1 / 1024),
    usage.SENTIMENT_ANALYSIS: ("sentimentRecords", 1),
    usage.CONNECTED_DATA_SOURCES: ("dataSources", 1),
}

PeriodCode = Literal["monthly", "three-months", "six-months", "yearly"]


class PlanChoice(BaseModel):
    plan_key: str
    period_code: PeriodCode = "monthly"


def _scaled(value, factor):
    if value is None:
        return None
    return round(value * factor, 3) if factor != 1 else value


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else (value.isoformat() if value else None)


def _role(conn, tenant_id: str, user_id: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
            (tenant_id, user_id),
        )
        row = cursor.fetchone()
    return row[0] if row else ""


def _require_billing_role(conn, ctx: TenantContext) -> None:
    if _role(conn, ctx.tenant_id, ctx.user_id) not in _BILLING_ROLES:
        raise HTTPException(status_code=403, detail="Only the company owner, an admin or the accountant can manage billing.")


def _to_http(err: service.BillingError) -> HTTPException:
    return HTTPException(status_code=err.status, detail={"reason": err.code, "message": err.message})


def _provider_failure(err: Exception) -> HTTPException:
    logger.exception("Stripe request failed: %s", err)
    return HTTPException(status_code=502, detail={
        "reason": "provider_error", "message": "The payment provider didn't respond. Please try again in a moment.",
    })


@router.get("/plans")
def list_plans() -> dict:
    """The public plan catalog (also shown on the landing page)."""
    conn = db.system_connection()
    try:
        plans = store.catalog(conn)
    finally:
        conn.close()
    return {"plans": plans, "payments_enabled": config.payments_enabled()}


@router.get("/subscription")
def get_subscription(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        plan = usage.get_plan(conn, ctx.tenant_id)
        features = usage.current_usage(conn, ctx.tenant_id, plan)
        subscription = store.current_subscription(conn, ctx.tenant_id)
        trial = store.trial(conn, ctx.tenant_id)
        has_customer = store.customer_id(conn, ctx.tenant_id) is not None
        can_manage = _role(conn, ctx.tenant_id, ctx.user_id) in _BILLING_ROLES
        conn.commit()
    finally:
        conn.close()
    limits, used = {}, {}
    for item in features:
        if item["feature_code"] not in _PAGE_KEYS:
            continue  # internal budgets (e.g. web_searches) aren't plan terms customers see
        key, factor = _PAGE_KEYS[item["feature_code"]]
        limits[key] = _scaled(item["limit"], factor)
        used[key] = _scaled(item["current_usage"], factor)
    return {
        "available": True,
        "planId": plan["plan_key"],
        "planName": plan["display_name"],
        "status": plan["status"],
        "hasAccess": plan["status"] in usage.ACCESS_GRANTING_STATUSES,
        "assigned": plan["assigned"],
        "source": plan.get("source"),
        "billingPeriod": plan.get("period_code") or "monthly",
        "periodStart": plan["period_start"].isoformat(),
        "periodEnd": plan["period_end"].isoformat(),
        "trialEndsAt": _iso(trial["ends_at"]) if trial and plan["status"] == "trialing" and not subscription else (
            _iso(subscription["trial_end"]) if subscription and subscription["status"] == "trialing" else None
        ),
        "trialUsed": trial is not None,
        "renewsAt": _iso(subscription["current_period_end"]) if subscription and not subscription["cancel_at_period_end"] else None,
        "endsAt": _iso(subscription["current_period_end"]) if subscription and subscription["cancel_at_period_end"] else None,
        "cancelAtPeriodEnd": bool(subscription and subscription["cancel_at_period_end"]),
        "scheduledChange": {
            "planId": subscription["scheduled_plan_key"], "billingPeriod": subscription["scheduled_period_code"],
            "effectiveAt": _iso(subscription["current_period_end"]),
        } if subscription and subscription["scheduled_plan_key"] else None,
        "hasSubscription": subscription is not None,
        "hasBillingAccount": has_customer,
        "canManageBilling": can_manage,
        "paymentsEnabled": config.payments_enabled(),
        "limits": limits,
        "usage": used,
        "features": features,
        "entitlements": plan.get("entitlements", []),
    }


@router.get("/invoices")
def list_invoices(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        rows = store.payments(conn, ctx.tenant_id)
        conn.commit()
    finally:
        conn.close()
    return {"invoices": rows}


def _company(conn, tenant_id: str, user_id: str) -> tuple:
    with conn.cursor() as cursor:
        cursor.execute("SELECT business_name FROM companies WHERE tenant_id = %s;", (tenant_id,))
        company = cursor.fetchone()
        cursor.execute("SELECT email FROM users WHERE user_id = %s;", (user_id,))
        user = cursor.fetchone()
    return (company[0] if company else ""), (user[0] if user else "")


@router.post("/checkout")
def start_checkout(body: PlanChoice, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    sys_conn = db.system_connection()
    try:
        _require_billing_role(conn, ctx)
        company_name, email = _company(conn, ctx.tenant_id, ctx.user_id)
        return service.create_checkout(conn, sys_conn, ctx.tenant_id, email, company_name, body.plan_key, body.period_code)
    except service.BillingError as err:
        raise _to_http(err)
    except HTTPException:
        raise
    except Exception as err:  # noqa: BLE001 - provider/network failure
        raise _provider_failure(err)
    finally:
        conn.close()
        sys_conn.close()


@router.post("/portal")
def open_portal(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        return service.create_portal(conn, ctx.tenant_id)
    except service.BillingError as err:
        raise _to_http(err)
    except HTTPException:
        raise
    except Exception as err:  # noqa: BLE001
        raise _provider_failure(err)
    finally:
        conn.close()


@router.post("/change-plan")
def change_plan(body: PlanChoice, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    sys_conn = db.system_connection()
    try:
        _require_billing_role(conn, ctx)
        return service.change_plan(conn, sys_conn, ctx.tenant_id, body.plan_key, body.period_code)
    except service.BillingError as err:
        raise _to_http(err)
    except HTTPException:
        raise
    except Exception as err:  # noqa: BLE001
        raise _provider_failure(err)
    finally:
        conn.close()
        sys_conn.close()


@router.delete("/scheduled-change")
def cancel_scheduled_change(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    sys_conn = db.system_connection()
    try:
        _require_billing_role(conn, ctx)
        return service.cancel_scheduled_change(conn, sys_conn, ctx.tenant_id)
    except service.BillingError as err:
        raise _to_http(err)
    except HTTPException:
        raise
    except Exception as err:  # noqa: BLE001
        raise _provider_failure(err)
    finally:
        conn.close()
        sys_conn.close()


def _set_cancellation(ctx: TenantContext, cancel: bool) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        return service.set_cancellation(conn, ctx.tenant_id, cancel)
    except service.BillingError as err:
        raise _to_http(err)
    except HTTPException:
        raise
    except Exception as err:  # noqa: BLE001
        raise _provider_failure(err)
    finally:
        conn.close()


@router.post("/cancel")
def cancel_subscription(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    return _set_cancellation(ctx, True)


@router.post("/resume")
def resume_subscription(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    return _set_cancellation(ctx, False)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, stripe_signature: str = Header(default=None, alias="Stripe-Signature")) -> dict:
    """Stripe -> KEEL. Verified against the raw body; 400 for a bad signature
    (Stripe stops), 500 when processing failed (Stripe retries)."""
    secret = config.webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe webhooks are not configured on this server.")
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")
    payload = await request.body()
    try:
        event = stripe_api.construct_event(payload, stripe_signature, secret)
    except Exception:  # noqa: BLE001 - invalid signature or payload
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    event = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    sys_conn = db.system_connection()
    try:
        result = webhooks.handle_event(sys_conn, event)
    except webhooks.WebhookRetry:
        raise HTTPException(status_code=500, detail="Event not processed; it will be retried.")
    finally:
        sys_conn.close()
    return {"received": True, **result}
