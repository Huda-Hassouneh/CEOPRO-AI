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
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.ai import db
from src.ai.billing import config, credits, custom_offers, custom_plan_pricing_service, promotions, service, store, stripe_api, webhooks
from src.ai.core import feature_rights, usage
from src.ai.core.security import TenantContext, get_tenant_context

logger = logging.getLogger("APEX_BILLING")
router = APIRouter(prefix="/billing", tags=["billing"])

_BILLING_ROLES = {"owner", "admin", "accountant"}

# feature_code -> the Billing page's usage key, and a unit conversion. Only
# plan terms customers see: web_searches and the assistant's token cap are
# internal safety limits, and competitors have no fixed count (they depend
# on market discovery and the Data Credit budget).
_PAGE_KEYS = {
    usage.TRACKED_PRODUCTS: ("products", 1),
    usage.MONTHLY_REPORTS: ("reports", 1),
    usage.TEAM_SEATS: ("teamSeats", 1),
    usage.DATA_CREDITS: ("dataCredits", 1),
    usage.AI_CREDITS: ("aiCredits", 1),
    usage.IMAGE_GENERATION: ("imageGenerations", 1),
    usage.DOCUMENT_STORAGE_MB: ("storageGb", 1 / 1024),
    usage.DOCUMENT_EXTRACTION: ("documentProcessingMb", 1 / 1024),
    usage.SENTIMENT_ANALYSIS: ("sentimentRecords", 1),
    usage.CONNECTED_DATA_SOURCES: ("dataSources", 1),
}

PeriodCode = Literal["monthly", "three-months", "six-months", "yearly"]


class PlanChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_key: str
    period_code: PeriodCode = "monthly"


class CheckoutChoice(PlanChoice):
    promotion_code: str | None = Field(default=None, min_length=1, max_length=100)


class PromotionValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=100)
    plan_key: str = Field(min_length=1, max_length=50)
    period_code: PeriodCode = "monthly"


class CustomOfferConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limits: dict[str, object] = Field(default_factory=dict)
    refresh_frequency: Literal["hourly", "daily", "weekly"] | None = None
    enabled_features: list[str] = Field(default_factory=list, max_length=20)


class CustomQuoteTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class CustomPricingPreview(CustomOfferConfiguration):
    pass

class CustomQuoteRequest(CustomOfferConfiguration):
    idempotency_key: str = Field(min_length=1, max_length=200)

class CustomQuoteApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    approval_reference: str = Field(min_length=3, max_length=200)

class CustomQuoteCheckout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200)

def _scaled(value, factor):
    if value is None:
        return None
    return round(value * factor, 3) if factor != 1 else value


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else (value.isoformat() if value else None)


def _effective_rights_response(plan: dict) -> dict:
    """Serialize version 1 of the read-only configured-rights API contract.

    ``state`` is the Python plan configuration state, not an authorization
    result; callers must also honor the existing top-level ``hasAccess``.
    Exact established Python codes only are exposed. Limits remain in their
    native Python units; ``None`` means unlimited only when state is
    ``unlimited``, while absent rows carry state ``absent``.
    """
    projection = feature_rights.project_effective_rights(plan)
    items = [
        {
            "featureCode": right["feature_code"],
            "state": right["configured_state"],
            "unit": right["unit"],
            "aggregationType": right["aggregation_type"],
            "resetCycle": right["reset_cycle"],
            "limit": right["limit"],
        }
        for right in projection["rights"]
        if right["mapping_status"] == "established_python_code"
    ]
    return {
        "version": 1,
        "basis": "configured_plan",
        "items": items,
    }


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


def _custom_offer_error(err: custom_offers.CustomOfferError) -> HTTPException:
    return HTTPException(err.status, detail={"reason": err.code, "message": err.message})


@router.get("/custom-offers/configurator")
def custom_offer_configurator(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Read-only catalog of feature quantities the existing Python contract supports."""
    del ctx  # Authentication is required; catalog metadata is not tenant-specific.
    conn = db.system_connection()
    try:
        return {
            "version": 1,
            "mode": "configuration_metadata_only",
            "features": custom_offers.feature_catalog(conn),
            "modules": custom_offers.module_catalog(),
            "refreshFrequencies": ["hourly", "daily", "weekly"],
            "initialCheckoutCurrency": "USD",
            "pricingAvailable": False,
            "unlimitedQuantityOverridesSupported": False,
        }
    finally:
        conn.close()


@router.post("/custom-offers/configuration/validate")
def validate_custom_offer_configuration(
    body: CustomOfferConfiguration, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """Check known feature units without saving or changing customer rights."""
    del ctx
    conn = db.system_connection()
    try:
        return custom_offers.validate_configuration(
            conn, limits=body.limits, enabled_features=body.enabled_features,
            refresh_frequency=body.refresh_frequency,
        )
    except custom_offers.CustomOfferError as exc:
        raise _custom_offer_error(exc)
    finally:
        conn.close()


@router.post("/custom-offers/pricing-preview")
def preview_custom_offer_pricing(body: CustomPricingPreview, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Customer-side configuration preflight; private economics stay owner-only."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        validation = custom_offers.validate_configuration(
            conn, limits=body.limits, enabled_features=body.enabled_features,
            refresh_frequency=body.refresh_frequency)
        conn.commit()
        return {"pricingAvailable": False, "pricingStatus": "manual_review_required",
                "reviewRequired": True, "reasons": ["platform_owner_review_required"],
                "currency": "USD", "price": None, "configuration": validation["configuration"]}
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@router.post("/custom-offers/quotes", status_code=201)
def request_custom_offer_quote(
    body: CustomQuoteRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """Submit tenant configuration for manual review; no price or access is assigned."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        result = custom_offers.request_quote(
            conn, tenant_id=ctx.tenant_id, customer_user_id=ctx.user_id,
            idempotency_key=body.idempotency_key,
            configuration={"refreshFrequency": body.refresh_frequency,
                           "enabledFeatures": body.enabled_features},
            feature_quantities=body.limits,
        )
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@router.post("/custom-offers/admin/pricing/policies", status_code=201)
def create_custom_pricing_policy(body: dict, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "policy_create", body)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()

@router.get("/custom-offers/admin/pricing/policies")
def list_custom_pricing_policies(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "policy_list", {})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()

@router.get("/custom-offers/admin/pricing/cost-rates")
def list_custom_pricing_cost_rates(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "rate_list", {})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()

@router.get("/custom-offers/admin/pricing/policies/{policy_id}/bindings")
def list_custom_pricing_bindings(policy_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "binding_list", {"policy_version_id": str(policy_id)})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()

@router.post("/custom-offers/admin/pricing/cost-rates", status_code=201)
def create_custom_pricing_cost_rate(body: dict, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "rate_create", body)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()

@router.post("/custom-offers/admin/pricing/cost-rates/{rate_id}/close")
def close_custom_pricing_cost_rate(rate_id: UUID, body: dict,
                                   ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "rate_close",
            {**body, "cost_rate_id": str(rate_id)})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()

@router.post("/custom-offers/admin/pricing/bindings", status_code=201)
def create_custom_pricing_binding(body: dict, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "binding_create", body)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()

@router.post("/custom-offers/admin/pricing/policies/{policy_id}/activate")
def activate_custom_pricing_policy(policy_id: UUID, body: dict,
                                   ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "policy_activate",
            {**body, "policy_version_id": str(policy_id)})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()






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
        price_snapshot = store.subscription_price_snapshot(conn, ctx.tenant_id) if subscription else None
        trial = store.trial(conn, ctx.tenant_id)
        has_customer = store.customer_id(conn, ctx.tenant_id) is not None
        can_manage = _role(conn, ctx.tenant_id, ctx.user_id) in _BILLING_ROLES
        budgets = credits.summary(conn, ctx.tenant_id)
        conn.commit()
    finally:
        conn.close()
    trial_available = False
    if not trial and not subscription:
        # The per-person check needs this person's other companies, which
        # this company's own connection can't see.
        sys_conn = db.system_connection()
        try:
            trial_available = store.trial_eligibility(sys_conn, ctx.tenant_id, config.trial_plan_key(), ctx.user_id) is None
        finally:
            sys_conn.close()
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
        "currentPrice": price_snapshot,
        "hasBillingAccount": has_customer,
        "canManageBilling": can_manage,
        "paymentsEnabled": config.payments_enabled(),
        "limits": limits,
        "usage": used,
        "features": features,
        "entitlements": plan.get("entitlements", []),
        "effectiveRights": _effective_rights_response(plan),
        # Data and AI Credits, separately: limit, used, remaining, warning
        # threshold reached and reset date. Never provider prices or costs.
        "credits": budgets,
        "trialAvailable": trial_available,
        "trialEndsAtExact": _iso(plan.get("trial_ends_at")),
    }


@router.get("/usage-history")
def usage_history(limit: int = 50, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Recent metered operations (what used Data or AI Credits, and their
    status). Credits only - never provider prices, costs or raw responses."""
    limit = max(1, min(200, limit))
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        items = credits.history(conn, ctx.tenant_id, limit)
        conn.commit()
    finally:
        conn.close()
    return {"items": items}


class TrialChoice(BaseModel):
    plan_key: str


@router.post("/trial")
def start_trial(body: TrialChoice, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """A company that never had a trial (and has no plan) starts one on the
    plan it picks, for that plan's trial length. Checked on the server: one
    trial per company, one per person, self-serve plans only. No payment is
    taken and nothing converts to a paid plan without a checkout."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        conn.commit()
    finally:
        conn.close()
    sys_conn = db.system_connection()
    try:
        reason = store.trial_eligibility(sys_conn, ctx.tenant_id, body.plan_key, ctx.user_id)
        if reason:
            raise HTTPException(status_code=409, detail={"reason": reason, "message": _TRIAL_REFUSALS.get(reason, _TRIAL_REFUSALS["trial_already_used"])})
        granted = store.start_trial(sys_conn, ctx.tenant_id, started_by_user_id=ctx.user_id, plan_key=body.plan_key)
        if not granted:
            sys_conn.rollback()
            raise HTTPException(status_code=409, detail={"reason": "trial_already_used", "message": _TRIAL_REFUSALS["trial_already_used"]})
        sys_conn.commit()
    except HTTPException:
        raise
    except Exception:
        sys_conn.rollback()
        raise
    finally:
        sys_conn.close()
    from src.ai.core import entitlements

    entitlements.forget(ctx.tenant_id)
    return {"plan_key": granted["plan_key"], "started_at": granted["started_at"].isoformat(),
            "ends_at": granted["ends_at"].isoformat()}


_TRIAL_REFUSALS = {
    "plan_has_no_trial": "This plan doesn't offer a free trial.",
    "trial_already_used": "Your company has already used its free trial.",
    "trial_already_used_by_person": "You've already used a free trial with another company.",
    "plan_already_assigned": "Your company already has a plan.",
    "subscription_exists": "Your company already has a subscription.",
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


@router.post("/promotions/validate")
def validate_promotion(body: PromotionValidation, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        result = promotions.validate(conn, ctx.tenant_id, body.code, body.plan_key, body.period_code)
        conn.commit()
        return result
    finally:
        conn.close()


@router.post("/checkout")
def start_checkout(body: CheckoutChoice, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    sys_conn = db.system_connection()
    try:
        _require_billing_role(conn, ctx)
        company_name, email = _company(conn, ctx.tenant_id, ctx.user_id)
        return service.create_checkout(conn, sys_conn, ctx.tenant_id, email, company_name,
                                       body.plan_key, body.period_code, body.promotion_code, ctx.user_id)
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



@router.get("/checkout-status")
def checkout_status(session_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        return service.checkout_status(conn, ctx.tenant_id, session_id)
    except service.BillingError as err:
        raise _to_http(err)
    except HTTPException:
        raise
    except Exception as err:
        raise _provider_failure(err)
    finally:
        conn.close()


@router.post("/checkout/cancel-pending")
def cancel_pending_checkout(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn=db.app_role_connection(ctx.tenant_id,ctx.user_id)
    sys_conn=db.system_connection()
    try:
        _require_billing_role(conn,ctx)
        return service.cancel_pending_checkout(conn,sys_conn,ctx.tenant_id)
    except service.BillingError as err:
        raise _to_http(err)
    except HTTPException:
        raise
    except Exception as err:
        raise _provider_failure(err)
    finally:
        conn.close()
        sys_conn.close()


@router.post("/change-plan/preview")
def preview_plan_change(body: PlanChoice, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        return service.preview_plan_change(conn, ctx.tenant_id, body.plan_key, body.period_code)
    except service.BillingError as err:
        raise _to_http(err)
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

@router.get("/custom-offers/quotes/{quote_id}")
def get_custom_offer_quote(quote_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Read a quote only inside the authenticated tenant; private economics stay hidden."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        result = custom_offers.quote_detail(conn, str(quote_id), include_private=False)
        if result is None or result["tenant_id"] != ctx.tenant_id:
            raise HTTPException(status_code=404, detail="Quote not found.")
        conn.commit()
        return result
    finally:
        conn.close()


@router.post("/custom-offers/quotes/{quote_id}/accept")
def accept_custom_offer_quote(quote_id: UUID, body: CustomQuoteTransition,
                              ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.transition(conn, "accept", tenant_id=ctx.tenant_id,
                                          quote_id=str(quote_id), expected_revision=body.expected_revision,
                                          idempotency_key=body.idempotency_key)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()


@router.post("/custom-offers/quotes/{quote_id}/reject")
def reject_custom_offer_quote(quote_id: UUID, body: CustomQuoteTransition,
                              ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.transition(conn, "reject", tenant_id=ctx.tenant_id,
                                          quote_id=str(quote_id), expected_revision=body.expected_revision,
                                          idempotency_key=body.idempotency_key)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()


@router.post("/custom-offers/quotes/{quote_id}/checkout-attempts")
def prepare_custom_offer_checkout_attempt(quote_id: UUID, body: CustomQuoteCheckout,
                                          ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Create or resume the Stripe Checkout session for an accepted Custom offer."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    sys_conn = db.system_connection()
    try:
        _require_billing_role(conn, ctx)
        company_name, email = _company(conn, ctx.tenant_id, ctx.user_id)
        result = service.create_custom_quote_checkout(conn, sys_conn, ctx.tenant_id, email,
            company_name, str(quote_id), body.idempotency_key)
        conn.commit()
        return result
    except service.BillingError as err:
        conn.rollback()
        raise _to_http(err)
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    except Exception as err:  # provider failure; attempt identity remains retryable
        conn.rollback()
        raise _provider_failure(err)
    finally:
        conn.close()
        sys_conn.close()


@router.get("/custom-offers/quotes")
def list_custom_offer_quotes(limit: int = 50, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_billing_role(conn, ctx)
        quotes = custom_offers.quote_list(conn, ctx.tenant_id, limit=limit)
        conn.commit()
        return {"quotes": quotes}
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_offer_error(exc)
    finally:
        conn.close()
