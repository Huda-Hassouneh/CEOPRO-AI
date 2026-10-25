"""Python-native platform management. Tenant ownership never implies platform authority."""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from src.ai import db
from src.ai.billing import admin as billing_admin, custom_offers, custom_plan_pricing_service, promotions
from src.ai.core import auth_throttle, security
from src.ai.core.authorization import require_platform_permission
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.platform import service

router = APIRouter(prefix="/platform", tags=["platform"])
Ctx = Annotated[TenantContext, Depends(get_tenant_context)]


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=2000)


class Status(Reason):
    active: bool


class Metadata(Reason):
    notes: str = Field(max_length=10000)


class Invite(Reason):
    email: str = Field(max_length=255)

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        import re
        if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", value):
            raise ValueError("Enter a valid email address")
        return value.lower()


class Member(Reason):
    status: Literal["active", "suspended", "removed"]


class Settings(Reason):
    support_email: str = Field(min_length=3, max_length=255)

    @field_validator("support_email")
    @classmethod
    def valid_email(cls, value):
        return Invite.email_shape(value)


class Approval(Reason):
    request_id: UUID
    kind: Literal["below_floor_price", "manual_access", "provider_spending"]
    subject: str = Field(min_length=1, max_length=255)
    terms: dict
    expires_at: datetime

    @field_validator("terms")
    @classmethod
    def bounded_terms(cls, value):
        import json
        if not value:
            raise ValueError("Explicit approval terms are required")
        if len(json.dumps(value).encode()) > 16384:
            raise ValueError("Approval terms are too large")
        return value

    @field_validator("expires_at")
    @classmethod
    def future(cls, value):
        if value.tzinfo is None or value <= datetime.now(timezone.utc):
            raise ValueError("A future expiry with timezone is required")
        return value


class PromotionDraft(Reason):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    terms: dict = Field(default_factory=dict)
    plan_keys: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("terms")
    @classmethod
    def bounded_terms(cls, value):
        import json
        if len(json.dumps(value, default=str).encode()) > 8192:
            raise ValueError("Promotion terms are too large")
        return value


class PromotionActivation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    approval_reference: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)


class PlanFeatureMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    feature_code: str = Field(min_length=1, max_length=60)
    included: StrictBool
    limit_value: StrictInt | None = None
    reason: str = Field(default="Owner plan feature update through Platform Billing Portal.", min_length=1, max_length=2000)


class PlanStatusMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    active: StrictBool
    reason: str = Field(default="Owner plan availability update through Platform Billing Portal.", min_length=1, max_length=2000)


class FeatureMetadataMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    name_ar: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    description_ar: str | None = Field(default=None, max_length=4000)
    reason: str = Field(min_length=1, max_length=2000)


class OwnerVendorRateSave(BaseModel):
    """Original owner vendor-rate form mapped to immutable Python rate + draft binding."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    budget_kind: Literal["data", "ai"]
    provider: str = Field(min_length=1, max_length=60)
    operation: str = Field(min_length=1, max_length=120)
    unit: Literal["request", "record", "page", "input_token", "output_token", "cache_read_token", "cache_write_token", "image"]
    unit_cost_usd: Decimal = Field(ge=0, max_digits=20, decimal_places=12)
    source: str = Field(min_length=1, max_length=2000)
    verification_evidence: str = Field(min_length=1, max_length=4000)
    verified_at: date
    effective_from: datetime
    effective_to: datetime | None = None
    supersedes_rate_id: UUID | None = None
    policy_version_id: UUID | None = None
    feature_code: str | None = Field(default=None, min_length=1, max_length=100)
    usage_basis: Literal["enabled_feature", "limit_value"] = "limit_value"
    units_per_feature_unit: Decimal = Field(default=Decimal("1"), gt=0, max_digits=24, decimal_places=8)
    operational_multiplier: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    variability_reserve: Decimal = Field(ge=1, max_digits=18, decimal_places=8)
    required_for_price: bool = True
    usage_assumption: dict = Field(default_factory=dict)

    @field_validator("effective_from", "effective_to")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Effective dates must include a timezone")
        return value

    @field_validator("source", "verification_evidence")
    @classmethod
    def nonblank_evidence(cls, value):
        if not value.strip():
            raise ValueError("Source and verification evidence are required")
        return value

    @field_validator("usage_assumption")
    @classmethod
    def bounded_assumption(cls, value):
        import json
        if len(json.dumps(value, default=str).encode()) > 4096:
            raise ValueError("Usage assumption is too large")
        return value


class OwnerInfrastructureRateSave(BaseModel):
    """Original infrastructure card mapped to an immutable rate and policy binding."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    policy_version_id: UUID
    feature_code: str = Field(min_length=1, max_length=60)
    provider: str = Field(min_length=1, max_length=60)
    operation: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=60)
    unit_cost_usd: Decimal = Field(ge=0, max_digits=20, decimal_places=12)
    source: str = Field(min_length=1, max_length=2000)
    verified_at: date
    effective_from: datetime
    effective_to: datetime | None = None
    supersedes_rate_id: UUID | None = None
    usage_basis: Literal["enabled_feature", "limit_value", "estimated_usage"] = "estimated_usage"
    units_per_feature_unit: Decimal = Field(default=Decimal("1"), gt=0, max_digits=24, decimal_places=8)
    operational_multiplier: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    variability_reserve: Decimal = Field(ge=1, max_digits=18, decimal_places=8)
    required_for_price: bool = True
    usage_assumption: dict = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def safe_unit(cls, value):
        import re
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_./-]{0,59}", value):
            raise ValueError("Unit must be a short identifier beginning with a letter")
        return value

    @field_validator("effective_from", "effective_to")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Effective dates must include a timezone")
        return value

    @field_validator("source")
    @classmethod
    def nonblank_source(cls, value):
        if not value.strip():
            raise ValueError("Rate source and verification evidence are required")
        return value

    @field_validator("usage_assumption")
    @classmethod
    def bounded_infrastructure_assumption(cls, value):
        import json
        if len(json.dumps(value, default=str).encode()) > 4096:
            raise ValueError("Usage assumption is too large")
        return value


def _promotion_operator(ctx: TenantContext) -> None:
    result = service.command(ctx, "me")
    require_platform_permission(result["role"], "promotion_management")


def _promotion_error(error: promotions.PromotionError) -> HTTPException:
    return HTTPException(error.status, detail={"reason": error.code, "message": error.message})


@router.get("/billing/promotions")
def promotion_definitions(ctx: Ctx):
    _promotion_operator(ctx)
    conn = db.system_connection()
    try:
        result = promotions.list_definitions(conn, ctx.user_id)
        conn.commit()
        return {"items": result}
    except promotions.PromotionError as exc:
        conn.rollback()
        raise _promotion_error(exc)
    finally:
        conn.close()


@router.post("/billing/promotions", status_code=201)
def create_promotion_draft(body: PromotionDraft, ctx: Ctx):
    _promotion_operator(ctx)
    conn = db.system_connection()
    try:
        result = promotions.save_draft(conn, actor_user_id=ctx.user_id, code=body.code, name=body.name,
                                       description=body.description, terms=body.terms,
                                       plan_keys=body.plan_keys, reason=body.reason)
        conn.commit()
        return result
    except promotions.PromotionError as exc:
        conn.rollback()
        raise _promotion_error(exc)
    except Exception as exc:
        conn.rollback()
        from psycopg2 import IntegrityError
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, detail={"reason": "promotion_conflict", "message": "Promotion definition conflicts with an existing record."}) from None
        raise
    finally:
        conn.close()


@router.patch("/billing/promotions/{promotion_id}")
def update_promotion_draft(promotion_id: UUID, body: PromotionDraft, ctx: Ctx):
    _promotion_operator(ctx)
    conn = db.system_connection()
    try:
        result = promotions.save_draft(conn, actor_user_id=ctx.user_id, promotion_id=str(promotion_id),
                                       code=body.code, name=body.name, description=body.description,
                                       terms=body.terms, plan_keys=body.plan_keys, reason=body.reason)
        conn.commit()
        return result
    except promotions.PromotionError as exc:
        conn.rollback()
        raise _promotion_error(exc)
    except Exception as exc:
        conn.rollback()
        from psycopg2 import IntegrityError
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, detail={"reason": "promotion_conflict", "message": "Promotion definition conflicts with an existing record."}) from None
        raise
    finally:
        conn.close()


@router.post("/billing/promotions/{promotion_id}/disable")
def disable_promotion(promotion_id: UUID, body: Reason, ctx: Ctx):
    _promotion_operator(ctx)
    conn = db.system_connection()
    try:
        result = promotions.disable(conn, actor_user_id=ctx.user_id, promotion_id=str(promotion_id), reason=body.reason)
        conn.commit()
        return result
    except promotions.PromotionError as exc:
        conn.rollback()
        raise _promotion_error(exc)
    finally:
        conn.close()


@router.post("/billing/promotions/{promotion_id}/activate")
def activate_promotion(promotion_id: UUID, body: PromotionActivation, ctx: Ctx):
    _promotion_operator(ctx)
    conn = db.system_connection()
    try:
        result = promotions.activate(conn, actor_user_id=ctx.user_id, promotion_id=str(promotion_id),
                                     approval_reference=body.approval_reference, reason=body.reason)
        conn.commit()
        return result
    except promotions.PromotionError as exc:
        conn.rollback()
        raise _promotion_error(exc)
    finally:
        conn.close()

@router.get("/me")
def me(ctx: Ctx):
    result = service.command(ctx, "me")
    require_platform_permission(result["role"], "me")
    return {**result, "token_expires_at": getattr(ctx, "token_expires_at", None)}


@router.get("/overview")
def overview(ctx: Ctx):
    return service.command(ctx, "overview")


@router.get("/companies")
def companies(ctx: Ctx, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000),
              search: str | None = Query(None, max_length=200)):
    if search is not None:
        return service.search(ctx, "companies", search, limit, offset)
    return {"items": service.command(ctx, "companies", {"limit": limit, "offset": offset})}


@router.get("/companies/{company_id}")
def company(company_id: UUID, ctx: Ctx):
    return service.command(ctx, "company", {"id": str(company_id)})


@router.patch("/companies/{company_id}/metadata")
def company_metadata(company_id: UUID, body: Metadata, ctx: Ctx):
    return service.command(ctx, "company_metadata", {"id": str(company_id), **body.model_dump()})


@router.patch("/companies/{company_id}/status")
def company_status(company_id: UUID, body: Status, ctx: Ctx):
    return service.command(ctx, "company_status", {"id": str(company_id), **body.model_dump()})


@router.get("/users")
def users(ctx: Ctx, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000),
          search: str | None = Query(None, max_length=200)):
    if search is not None:
        return service.search(ctx, "users", search, limit, offset)
    return {"items": service.command(ctx, "users", {"limit": limit, "offset": offset})}


@router.get("/users/{user_id}")
def user(user_id: UUID, ctx: Ctx):
    return service.command(ctx, "user", {"id": str(user_id)})


@router.patch("/users/{user_id}/status")
def user_status(user_id: UUID, body: Status, ctx: Ctx):
    return service.command(ctx, "user_status", {"id": str(user_id), **body.model_dump()})


@router.patch("/memberships/{membership_id}/status")
def membership_status(membership_id: UUID, body: Status, ctx: Ctx):
    return service.command(ctx, "membership_status", {"id": str(membership_id), **body.model_dump()})


@router.get("/team")
def team(ctx: Ctx, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return service.command(ctx, "team", {"limit": limit, "offset": offset})


@router.post("/team/invitations", status_code=201)
def invite(body: Invite, ctx: Ctx):
    auth_throttle.ensure_allowed("send", body.email)
    auth_throttle.record_failure("send", body.email)
    return service.invite(ctx, body.model_dump())


@router.post("/team/invitations/{invitation_id}/resend")
def resend(invitation_id: UUID, body: Reason, ctx: Ctx):
    auth_throttle.ensure_allowed("send", f"platform:{invitation_id}")
    auth_throttle.record_failure("send", f"platform:{invitation_id}")
    return service.invite(ctx, body.model_dump(), str(invitation_id))


@router.post("/team/invitations/{invitation_id}/cancel")
def cancel(invitation_id: UUID, body: Reason, ctx: Ctx):
    return service.command(ctx, "invitation_cancel", {"id": str(invitation_id), **body.model_dump()})


@router.patch("/team/{user_id}")
def member(user_id: UUID, body: Member, ctx: Ctx):
    return service.command(ctx, "member_update", {"id": str(user_id), **body.model_dump()})


@router.post("/owner-transfer/{user_id}")
def transfer(user_id: UUID, body: Reason, ctx: Ctx):
    return service.command(ctx, "owner_transfer", {"id": str(user_id), **body.model_dump()})


@router.get("/audit")
def audit(ctx: Ctx, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return {"items": service.command(ctx, "audit", {"limit": limit, "offset": offset})}


@router.get("/settings")
def settings(ctx: Ctx):
    return service.command(ctx, "settings")


@router.patch("/settings")
def update_settings(body: Settings, ctx: Ctx):
    return service.command(ctx, "settings_update", body.model_dump())


@router.post("/financial-approvals", status_code=201)
def approve(body: Approval, ctx: Ctx):
    # An authorization receipt; it does not activate access, change money, or alter provider controls.
    return service.command(ctx, "financial_approval", body.model_dump(mode="json"))


class Accept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    password: str | None = None

    @field_validator("full_name")
    @classmethod
    def nonblank_name(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Full name is required")
        return value


@router.get("/invitations/{token}")
def view_invitation(token: str):
    if len(token) > 200:
        raise HTTPException(404, "Invitation not found.")
    return service.invitation(token)


@router.post("/invitations/{token}/accept")
def accept(token: str, body: Accept):
    if len(token) > 200:
        raise HTTPException(404, "Invitation not found.")
    data = {"full_name": body.full_name}
    if body.password:
        security.ensure_password_policy(body.password)
        data["password_hash"] = security.hash_password(body.password)
    result = service.invitation(token, data)
    from src.ai.routers.auth import _session
    return _session(result["tenant_id"], result["user_id"], "staff", result["business_name"],
                    result["full_name"], "en", result["email"])

class CustomQuoteDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    customer_user_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)
    configuration: dict = Field(default_factory=dict)
    feature_quantities: dict = Field(default_factory=dict)
    commercial_terms: dict = Field(default_factory=dict)
    economic_inputs: dict = Field(default_factory=dict)
    fx_evidence: dict = Field(default_factory=dict)
    valid_until: datetime | None = None


class CustomQuoteRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    configuration: dict = Field(default_factory=dict)
    feature_quantities: dict = Field(default_factory=dict)
    commercial_terms: dict = Field(default_factory=dict)
    economic_inputs: dict = Field(default_factory=dict)
    fx_evidence: dict = Field(default_factory=dict)
    valid_until: datetime | None = None


class CustomQuoteTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class CustomQuoteApproval(CustomQuoteTransition):
    approval_reference: str = Field(min_length=1, max_length=200)


class CustomContractAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tenant_id: UUID
    contract_ref: str = Field(min_length=1, max_length=120)
    approval_reference: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    limits: dict[str, int]
    monthly_price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    trial_days: int = Field(default=0, ge=0, le=90)
    data_sources: list[str] = Field(default_factory=list, max_length=50)
    included_features: list[str] | None = None
    refresh_frequency: Literal["hourly", "daily", "weekly"] | None = None
    support_level: str | None = Field(default=None, max_length=40)
    period_months: int = Field(default=1, ge=1, le=36)

    @field_validator("limits")
    @classmethod
    def strict_limits(cls, value):
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value.values()):
            raise ValueError("Contract allowances must be nonnegative integers.")
        return value

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value):
        value = value.upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter code.")
        return value


def _custom_quote_operator(ctx: TenantContext) -> None:
    result = service.command(ctx, "me")
    if result.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the Platform Owner can manage custom quotes.")

def _custom_quote_http_error(error: custom_offers.CustomOfferError) -> HTTPException:
    return HTTPException(error.status, detail={"reason": error.code, "message": error.message})


def _quote_payload(body):
    return body.model_dump(mode="json")


@router.post("/billing/custom-quotes", status_code=201)
def create_custom_quote(body: CustomQuoteDraft, ctx: Ctx):
    """Create an internal quote draft; this does not publish an offer or activate access."""
    _custom_quote_operator(ctx)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        payload = _quote_payload(body)
        created = custom_offers.create_draft(
            conn, tenant_id=str(body.tenant_id), customer_user_id=str(body.customer_user_id) if body.customer_user_id else None,
            idempotency_key=body.idempotency_key,
            configuration=payload["configuration"], feature_quantities=payload["feature_quantities"],
            commercial_terms=payload["commercial_terms"], economic_inputs=payload["economic_inputs"],
            fx_evidence=payload["fx_evidence"], valid_until=body.valid_until,
        )
        conn.commit()
        return created
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/billing/custom-quotes/{quote_id}")
def get_custom_quote(quote_id: UUID, ctx: Ctx):
    _custom_quote_operator(ctx)
    conn = db.system_connection()
    try:
        result = custom_offers.quote_detail(conn, str(quote_id), include_private=True)
        if result is None:
            raise HTTPException(status_code=404, detail="Quote not found.")
        return result
    finally:
        conn.close()


@router.post("/billing/custom-quotes/{quote_id}/revisions")
def create_custom_quote_revision(quote_id: UUID, body: CustomQuoteRevision, ctx: Ctx):
    _custom_quote_operator(ctx)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        payload = _quote_payload(body)
        result = custom_offers.create_revision(
            conn, quote_id=str(quote_id), expected_revision=body.expected_revision,
            idempotency_key=body.idempotency_key, configuration=payload["configuration"],
            feature_quantities=payload["feature_quantities"], commercial_terms=payload["commercial_terms"],
            economic_inputs=payload["economic_inputs"], fx_evidence=payload["fx_evidence"],
            valid_until=body.valid_until,
        )
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/billing/custom-quotes/{quote_id}/submit")
def submit_custom_quote(quote_id: UUID, body: CustomQuoteTransition, ctx: Ctx):
    _custom_quote_operator(ctx)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.transition(conn, "submit", tenant_id=None, quote_id=str(quote_id),
                                          expected_revision=body.expected_revision, idempotency_key=body.idempotency_key)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/billing/custom-quotes/{quote_id}/approve")
def approve_custom_quote(quote_id: UUID, body: CustomQuoteApproval, ctx: Ctx):
    _custom_quote_operator(ctx)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.transition(conn, "approve", tenant_id=None, quote_id=str(quote_id),
                                          expected_revision=body.expected_revision,
                                          idempotency_key=body.idempotency_key,
                                          approval_reference=body.approval_reference)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/billing/custom-plan-pricing/policies", status_code=201)
def create_custom_pricing_policy(body: dict, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "policy_create", body)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.get("/billing/custom-plan-pricing/policies")
def list_custom_pricing_policies(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "policy_list", {})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.get("/billing/custom-plan-pricing/cost-rates")
def list_custom_pricing_cost_rates(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "rate_list", {})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.get("/billing/custom-plan-pricing/policies/{policy_id}/bindings")
def list_custom_pricing_bindings(policy_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "binding_list", {"policy_version_id": str(policy_id)})
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.post("/billing/custom-plan-pricing/cost-rates", status_code=201)
def create_custom_pricing_cost_rate(body: dict, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "rate_create", body)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.post("/billing/custom-plan-pricing/vendor-rates", status_code=201)
def save_owner_vendor_rate(body: OwnerVendorRateSave, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Atomically map the original owner form to a Python rate and optional draft-policy binding."""
    _custom_quote_operator(ctx)
    if body.verified_at > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail={"reason": "verification_date_invalid", "message": "Verification date cannot be in the future."})
    if body.effective_to is not None and body.effective_to <= body.effective_from:
        raise HTTPException(status_code=422, detail={"reason": "effective_interval_invalid", "message": "Effective end must be after effective start."})
    if body.feature_code and body.policy_version_id is None:
        raise HTTPException(status_code=422, detail={"reason": "draft_policy_required", "message": "Choose a draft pricing policy to bind this feature cost."})
    if body.feature_code and body.effective_from > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail={"reason": "future_binding_unsupported", "message": "The current Python pricing-binding contract only accepts rates effective now. Choose a current or past effective start date."})
    if not body.feature_code and body.policy_version_id is not None:
        raise HTTPException(status_code=422, detail={"reason": "feature_binding_required", "message": "A policy can only be selected when the rate is linked to a feature."})
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if body.supersedes_rate_id is not None:
            custom_offers.pricing_admin_command(conn, "rate_close", {
                "cost_rate_id": str(body.supersedes_rate_id),
                "effective_to": body.effective_from.astimezone(timezone.utc).isoformat(),
                "reason": "Superseded by a new immutable vendor cost-rate version",
            })
        rate = custom_offers.pricing_admin_command(conn, "rate_create", {
            "budget_kind": body.budget_kind, "provider": body.provider, "operation": body.operation,
            "unit": body.unit, "unit_cost_usd": str(body.unit_cost_usd), "source": body.source,
            "verified_at": body.verified_at.isoformat(), "effective_from": body.effective_from.astimezone(timezone.utc).isoformat(),
            "effective_to": body.effective_to.astimezone(timezone.utc).isoformat() if body.effective_to else None,
            "verification_evidence": body.verification_evidence,
        })
        binding = None
        if body.feature_code:
            binding = custom_offers.pricing_admin_command(conn, "binding_create", {
                "policy_version_id": str(body.policy_version_id), "cost_rate_id": rate["cost_rate_id"],
                "feature_code": body.feature_code, "cost_category": "vendor",
                "usage_basis": body.usage_basis, "units_per_feature_unit": str(body.units_per_feature_unit),
                "operational_multiplier": str(body.operational_multiplier),
                "variability_reserve": str(body.variability_reserve),
                "required_for_price": body.required_for_price, "usage_assumption": body.usage_assumption,
                "effective_from": body.effective_from.astimezone(timezone.utc).isoformat(),
                "effective_to": body.effective_to.astimezone(timezone.utc).isoformat() if body.effective_to else None,
                "source": body.source,
            })
        conn.commit()
        return {"cost_rate": rate, "binding": binding}
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/billing/custom-plan-pricing/infrastructure-rates")
def list_owner_infrastructure_rates(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """List internal infrastructure rate cards through the owner-checked pricing authority."""
    _custom_quote_operator(ctx)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        rates = custom_offers.pricing_admin_command(conn, "rate_list", {}).get("cost_rates", [])
        policies = custom_offers.pricing_admin_command(conn, "policy_list", {}).get("policies", [])
        bindings = []
        for policy in policies:
            bindings.extend(custom_offers.pricing_admin_command(
                conn, "binding_list", {"policy_version_id": policy["policy_version_id"]}
            ).get("bindings", []))
        rows = []
        for binding in bindings:
            if binding.get("cost_category") != "infrastructure":
                continue
            rate = next((item for item in rates if item.get("cost_rate_id") == binding.get("cost_rate_id")), None)
            if rate is None:
                continue
            rows.append({**rate, **binding, "id": rate["cost_rate_id"],
                         "policy_status": next((p["status"] for p in policies
                                                 if p["policy_version_id"] == binding["policy_version_id"]), None),
                         "featureId": binding["feature_code"], "costDriver": rate["operation"],
                         "billingUnit": rate["unit"], "unitCost": rate["unit_cost_usd"],
                         "currency": "USD", "verificationStatus": "confirmed",
                         "effectiveFrom": rate["effective_from"], "effectiveTo": rate["effective_to"],
                         "billingUnitsPerFeatureUnit": binding["units_per_feature_unit"],
                         "operationalMultiplier": binding["operational_multiplier"],
                         "variabilityReserve": binding["variability_reserve"],
                         "usageBasis": binding["usage_basis"],
                         "policyVersionId": binding["policy_version_id"],
                         "bindingId": binding["binding_id"]})
        conn.commit()
        return {"items": rows}
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()


@router.post("/billing/custom-plan-pricing/infrastructure-rates", status_code=201)
def save_owner_infrastructure_rate(body: OwnerInfrastructureRateSave,
                                   ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Atomically create an immutable infra rate and bind it to an owner draft policy."""
    _custom_quote_operator(ctx)
    now = datetime.now(timezone.utc)
    if body.verified_at > now.date():
        raise HTTPException(422, detail={"reason": "verification_date_invalid", "message": "Verification date cannot be in the future."})
    if body.effective_from > now:
        raise HTTPException(422, detail={"reason": "future_binding_unsupported", "message": "The current pricing contract accepts infrastructure rates effective now or earlier."})
    if body.effective_to is not None and body.effective_to <= body.effective_from:
        raise HTTPException(422, detail={"reason": "effective_interval_invalid", "message": "Effective end must be after effective start."})
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        supported_features = {item["featureCode"] for item in custom_offers.feature_catalog(conn)}
        supported_features.update(item["featureCode"] for item in custom_offers.module_catalog())
        if body.feature_code not in supported_features:
            raise HTTPException(422, detail={"reason": "unsupported_feature", "message": "Infrastructure rates must bind to an existing Python-supported feature."})
        if body.supersedes_rate_id is not None:
            known = custom_offers.pricing_admin_command(conn, "rate_list", {}).get("cost_rates", [])
            old = next((rate for rate in known if rate.get("cost_rate_id") == str(body.supersedes_rate_id)), None)
            if old is None:
                raise HTTPException(404, detail="Infrastructure rate not found.")
            if old.get("effective_to") is None:
                old_start = old["effective_from"]
                if isinstance(old_start, str):
                    old_start = datetime.fromisoformat(old_start.replace("Z", "+00:00"))
                if body.effective_from <= old_start:
                    raise HTTPException(422, detail={"reason": "effective_interval_invalid", "message": "A replacement rate must start after its predecessor."})
                custom_offers.pricing_admin_command(conn, "rate_close", {
                    "cost_rate_id": str(body.supersedes_rate_id),
                    "effective_to": body.effective_from.astimezone(timezone.utc).isoformat(),
                    "reason": "Superseded by an immutable infrastructure rate version",
                })
        rate = custom_offers.pricing_admin_command(conn, "rate_create", {
            "budget_kind": "infrastructure", "provider": body.provider, "operation": body.operation,
            "unit": body.unit, "unit_cost_usd": str(body.unit_cost_usd), "source": body.source,
            "verified_at": body.verified_at.isoformat(),
            "effective_from": body.effective_from.astimezone(timezone.utc).isoformat(),
            "effective_to": body.effective_to.astimezone(timezone.utc).isoformat() if body.effective_to else None,
            "verification_evidence": body.source,
        })
        binding = custom_offers.pricing_admin_command(conn, "binding_create", {
            "policy_version_id": str(body.policy_version_id), "cost_rate_id": rate["cost_rate_id"],
            "feature_code": body.feature_code, "cost_category": "infrastructure",
            "usage_basis": body.usage_basis, "units_per_feature_unit": str(body.units_per_feature_unit),
            "operational_multiplier": str(body.operational_multiplier),
            "variability_reserve": str(body.variability_reserve),
            "required_for_price": body.required_for_price, "usage_assumption": body.usage_assumption,
            "effective_from": body.effective_from.astimezone(timezone.utc).isoformat(),
            "effective_to": body.effective_to.astimezone(timezone.utc).isoformat() if body.effective_to else None,
            "source": body.source,
        })
        conn.commit()
        return {"cost_rate": rate, "binding": binding, "policy_version_id": str(body.policy_version_id)}
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@router.post("/billing/custom-plan-pricing/cost-rates/{rate_id}/close")
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
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.post("/billing/custom-plan-pricing/bindings", status_code=201)
def create_custom_pricing_binding(body: dict, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.pricing_admin_command(conn, "binding_create", body)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.post("/billing/custom-plan-pricing/policies/{policy_id}/activate")
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
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.get("/billing/admin-views/{view}")
def platform_billing_admin_view(view: Literal["quotes", "plans", "subscriptions", "contracts", "audit"],
                                ctx: TenantContext = Depends(get_tenant_context),
                                limit: int = Query(100, ge=1, le=200),
                                offset: int = Query(0, ge=0, le=1000000)) -> dict:
    """Owner-only, read-only billing portfolio views. Database function repeats the owner check."""
    _custom_quote_operator(ctx)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_platform_owner_read(%s,%s,%s);", (view, limit, offset))
            result = cursor.fetchone()[0]
        conn.commit()
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if getattr(exc, "pgcode", None) == "42501":
            raise HTTPException(status_code=403, detail="Only the Platform Owner can view global billing administration.") from None
        raise
    finally:
        conn.close()




@router.patch("/billing/plans/{plan_key}/features")
def update_platform_plan_feature(plan_key: str, body: PlanFeatureMutation, ctx: Ctx):
    """Update the latest catalog feature contract; existing tenant assignments remain snapshotted."""
    _custom_quote_operator(ctx)
    conn = db.system_connection()
    try:
        result = billing_admin.set_plan_feature(
            conn, plan_key=plan_key, feature_code=body.feature_code, included=body.included,
            limit_value=body.limit_value, approved_by=ctx.user_id, reason=body.reason,
        )
        conn.commit()
        return result
    except billing_admin.AdminError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail={"reason": "invalid_plan_feature_change", "message": str(exc)}) from None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch("/billing/plans/{plan_key}/status")
def update_platform_plan_status(plan_key: str, body: PlanStatusMutation, ctx: Ctx):
    """Change plan availability for new purchases; current paid assignments are not changed."""
    _custom_quote_operator(ctx)
    conn = db.system_connection()
    try:
        result = billing_admin.set_plan_active(
            conn, plan_key=plan_key, active=body.active, approved_by=ctx.user_id, reason=body.reason,
        )
        conn.commit()
        return result
    except billing_admin.AdminError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail={"reason": "invalid_plan_status_change", "message": str(exc)}) from None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/billing/feature-catalog")
def platform_feature_catalog(ctx: Ctx):
    _custom_quote_operator(ctx)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_platform_feature_catalog_command('list','{}'::jsonb);")
            result = cursor.fetchone()[0]
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch("/billing/feature-catalog/{feature_code}")
def update_platform_feature_metadata(feature_code: str, body: FeatureMetadataMutation, ctx: Ctx):
    _custom_quote_operator(ctx)
    if not feature_code or len(feature_code) > 60:
        raise HTTPException(422, detail="Invalid canonical feature code.")
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        from psycopg2.extras import Json
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_platform_feature_catalog_command(%s,%s::jsonb);", (
                "update_metadata", Json({
                    "feature_code": feature_code, "display_name": body.name, "display_name_ar": body.name_ar,
                    "description": body.description, "description_ar": body.description_ar, "reason": body.reason,
                })
            ))
            result = cursor.fetchone()[0]
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise HTTPException(403, detail="Platform Owner permission is required.") from None
        if code == "P0002":
            raise HTTPException(404, detail="Canonical feature not found.") from None
        if code == "22023":
            raise HTTPException(422, detail="Localized feature names are required.") from None
        raise
    finally:
        conn.close()


@router.get("/billing/custom-quotes")
def list_custom_offer_review_queue(state: str | None = None, limit: int = 50,
                                   ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.admin_quote_list(conn, state=state, limit=limit)
        conn.commit()
        return {"quotes": result}
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()

@router.post("/billing/custom-quotes/{quote_id}/calculate")
def calculate_custom_quote(quote_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Calculate only the current submitted revision; client cannot choose economics."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        quote = custom_offers.admin_quote_detail(conn, str(quote_id))
        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found.")
        revision = quote.get("currentRevision") or {}
        quantities = revision.get("featureQuantities") or {}
        configuration = revision.get("configuration") or {}
        preview = custom_plan_pricing_service.calculate_preview(
            conn, limits=quantities,
            enabled_features=configuration.get("enabledFeatures") or [],
            refresh_frequency=configuration.get("refreshFrequency") or configuration.get("refresh_frequency"))
        if not preview.get("pricingAvailable") or not preview.get("pricingSnapshot"):
            conn.commit()
            return preview
        attached = custom_offers.attach_pricing_snapshot(
            conn, quote_id=str(quote_id), snapshot=preview["pricingSnapshot"])
        conn.commit()
        return {**preview, "pricingSnapshot": None, "quote": attached}
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()

@router.post("/billing/custom-quotes/{quote_id}/reject")
def reject_custom_offer_by_admin(quote_id: UUID, body: CustomQuoteTransition,
                                  ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = custom_offers.transition(conn, "admin_reject", tenant_id=None,
            quote_id=str(quote_id), expected_revision=body.expected_revision,
            idempotency_key=body.idempotency_key)
        conn.commit()
        return result
    except custom_offers.CustomOfferError as exc:
        conn.rollback()
        raise _custom_quote_http_error(exc)
    finally:
        conn.close()


@router.post("/billing/custom-contracts", status_code=201)
def assign_custom_contract(body: CustomContractAssignment, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Apply an audited manual contract only when no current Stripe subscription can conflict with it."""
    _custom_quote_operator(ctx)
    conn = db.system_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true);",
                           (str(ctx.tenant_id), str(ctx.user_id)))
            cursor.execute(
                """SELECT public.keel_active_principal(%s,%s) AND EXISTS(
                     SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=%s
                     WHERE m.user_id=%s AND m.status='active' AND m.role_key='owner') AND NOT EXISTS(
                     SELECT 1 FROM public.users u WHERE u.user_id=%s AND u.platform_disabled_at IS NOT NULL);""",
                (str(ctx.user_id), str(ctx.tenant_id), str(ctx.tenant_id), str(ctx.user_id), str(ctx.user_id)),
            )
            if not cursor.fetchone()[0]:
                raise HTTPException(status_code=403, detail="Only an active Platform Owner may assign custom contracts.")
            cursor.execute("SELECT tenant_id FROM public.companies WHERE tenant_id=%s FOR UPDATE;", (str(body.tenant_id),))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Tenant not found.")
            cursor.execute(
                """SELECT status FROM public.billing_subscriptions WHERE tenant_id=%s
                   AND status IN ('trialing','active','past_due','pending','payment_failed','paused') FOR UPDATE;""",
                (str(body.tenant_id),),
            )
            if cursor.fetchone():
                raise HTTPException(status_code=409, detail={
                    "reason": "provider_subscription_transition_required",
                    "message": "A current Stripe subscription exists. Use the verified billing transition workflow before assigning a manual contract.",
                })
        billing_admin.set_custom_contract(
            conn, tenant_id=str(body.tenant_id), contract_ref=body.contract_ref,
            approved_by=str(ctx.user_id), reason=f"{body.approval_reference}: {body.reason}",
            limits=body.limits, monthly_price=body.monthly_price, currency=body.currency,
            trial_days=body.trial_days, data_sources=body.data_sources,
            included_features=body.included_features, refresh_frequency=body.refresh_frequency,
            support_level=body.support_level, period_months=body.period_months,
        )
        conn.commit()
        return {"tenant_id": str(body.tenant_id), "contract_ref": body.contract_ref, "state": "assigned",
                "approved_by": str(ctx.user_id), "approval_reference": body.approval_reference}
    except billing_admin.AdminError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
