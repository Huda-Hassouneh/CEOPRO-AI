"""Durable tenant notification inbox API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ai import db, notification_inbox
from src.ai.core.security import TenantContext, get_tenant_context

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _connection(ctx: TenantContext):
    return db.app_role_connection(ctx.tenant_id, ctx.user_id)


@router.get("")
def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    before_created_at: Optional[datetime] = None,
    before_notification_id: Optional[UUID] = None,
    include_dismissed: bool = False,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    if (before_created_at is None) != (before_notification_id is None):
        raise HTTPException(status_code=422, detail="Both cursor fields are required.")
    conn = _connection(ctx)
    try:
        return notification_inbox.list_for_user(
            conn, ctx.tenant_id, limit, before_created_at,
            before_notification_id, include_dismissed,
        )
    finally:
        conn.close()


@router.post("/read-all")
def read_all(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = _connection(ctx)
    try:
        return {"updated": notification_inbox.mark_all_read(conn, ctx.tenant_id)}
    finally:
        conn.close()


@router.post("/{notification_id}/read")
def read_one(notification_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = _connection(ctx)
    try:
        notification_inbox.mark_read(conn, ctx.tenant_id, notification_id)
        return {"ok": True}
    finally:
        conn.close()


@router.post("/{notification_id}/dismiss")
def dismiss_one(notification_id: UUID, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = _connection(ctx)
    try:
        notification_inbox.dismiss(conn, ctx.tenant_id, notification_id)
        return {"ok": True}
    finally:
        conn.close()
