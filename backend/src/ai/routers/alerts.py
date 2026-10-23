"""Alerts for the bell in the top bar (src/ai/alerts.py)."""
from datetime import datetime

from fastapi import APIRouter, Depends

from src.ai import alerts as alerts_module
from src.ai import db
from src.ai import notification_prefs
from src.ai import notification_inbox
from src.ai.core.security import TenantContext, get_tenant_context

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        items = alerts_module.build_alerts(conn, ctx.tenant_id)
        persistent_keys = notification_inbox.existing_event_keys(
            conn, ctx.tenant_id, [a["event_key"] for a in items if a.get("event_key")],
        )
        items = [a for a in items if a.get("event_key") not in persistent_keys]
        read_at = alerts_module.last_read(conn, ctx.tenant_id, ctx.user_id)
        with conn.cursor() as cursor:
            cursor.execute("SELECT notification_preferences FROM users WHERE user_id = %s;", (ctx.user_id,))
            row = cursor.fetchone()
        # Groups this person switched off in Settings -> Notifications.
        items = notification_prefs.wanted(items, notification_prefs.normalize(row[0] if row else None), "in_app")
        conn.commit()
    finally:
        conn.close()
    for item in items:
        at = datetime.fromisoformat(item["at"]) if isinstance(item["at"], str) else item["at"]
        item["unread"] = read_at is None or (at is not None and at > read_at)
    return {"alerts": items, "unread": sum(1 for a in items if a["unread"]),
            "last_read_at": read_at.isoformat() if read_at else None}


@router.post("/read")
def mark_alerts_read(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        alerts_module.mark_read(conn, ctx.tenant_id, ctx.user_id)
        conn.commit()
        return {"ok": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
