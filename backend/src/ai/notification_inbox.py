"""Tenant-scoped durable notification inbox operations."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException


def _sql_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "pgcode", None)
    if code == "22023":
        return HTTPException(status_code=422, detail="Invalid notification request.")
    if code == "42501":
        return HTTPException(status_code=403, detail="Notification access is not authorized.")
    return HTTPException(status_code=500, detail="Notification request failed.")


def list_for_user(conn, tenant_id: str, limit: int = 20,
                  before_created_at: Optional[datetime] = None,
                  before_notification_id: Optional[UUID] = None,
                  include_dismissed: bool = False) -> dict:
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT public.list_tenant_notifications(%s, %s, %s, %s, %s);",
                (tenant_id, limit, before_created_at, str(before_notification_id) if before_notification_id else None,
                 include_dismissed),
            )
            result = cursor.fetchone()[0]
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        raise _sql_error(exc) from exc


def mark_read(conn, tenant_id: str, notification_id: UUID) -> bool:
    return _mutate(conn, "public.mark_tenant_notification_read(%s, %s)", (tenant_id, str(notification_id)))


def mark_all_read(conn, tenant_id: str) -> int:
    return _mutate(conn, "public.mark_all_tenant_notifications_read(%s)", (tenant_id,))


def dismiss(conn, tenant_id: str, notification_id: UUID) -> bool:
    return _mutate(conn, "public.dismiss_tenant_notification(%s, %s)", (tenant_id, str(notification_id)))


def existing_event_keys(conn, tenant_id: str, keys: list[str]) -> set[str]:
    if not keys:
        return set()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.notification_existing_event_keys(%s, %s);", (tenant_id, keys))
            result = cursor.fetchone()[0]
        conn.commit()
        return set(result or [])
    except Exception as exc:
        conn.rollback()
        raise _sql_error(exc) from exc


def _mutate(conn, function_sql: str, params: tuple):
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT {function_sql};", params)
            result = cursor.fetchone()[0]
        conn.commit()
        if result is False:
            raise HTTPException(status_code=404, detail="Notification not found.")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise _sql_error(exc) from exc
