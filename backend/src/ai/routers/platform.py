"""Python-native platform management. Tenant ownership never implies platform authority."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.ai import db
from src.ai.billing import promotions
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

    @field_validator("expires_at")
    @classmethod
    def future(cls, value):
        if value.tzinfo is None or value <= datetime.now(timezone.utc):
            raise ValueError("A future expiry with timezone is required")
        return value


@router.get("/me")
def me(ctx: Ctx):
    result = service.command(ctx, "me")
    require_platform_permission(result["role"], "me")
    return {**result, "token_expires_at": getattr(ctx, "token_expires_at", None)}


@router.get("/overview")
def overview(ctx: Ctx):
    return service.command(ctx, "overview")


@router.get("/companies")
def companies(ctx: Ctx, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
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
def users(ctx: Ctx, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
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
