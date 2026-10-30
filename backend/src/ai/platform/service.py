"""Platform management through restricted SQL functions; never uses the billing/system connection."""
from src.infrastructure.public_urls import frontend_origin
import os
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from psycopg2 import IntegrityError, Error as DatabaseError
from psycopg2.extras import Json
from src.ai import db
from src.ai.core import notifications, security

ERRORS = {"forbidden": (403, "Platform permission required."), "not_found": (404, "Record not found or invitation expired."),
    "protected": (409, "This platform record is protected."), "last_owner": (409, "The last active owner must be preserved."),
    "already_member": (409, "This user is already an active platform operator."),
    "idempotency_conflict": (409, "This request ID was already used for different approval terms."),
    "new_credentials_required": (422, "Full name and password are required for a new operator account."),
    "operator_inactive": (409, "Only the Platform Owner can reactivate an existing operator."),
    "seat_capacity": (402, "The customer workspace has no available team seat."),
    "not_configured": (503, "Platform administration has not been bootstrapped.")}


def _error(result):
    if isinstance(result, dict) and result.get("error"):
        status, detail = ERRORS.get(result["error"], (422, "Invalid platform request."))
        raise HTTPException(status, detail)
    return result


def record_attempt(ctx, action, subject, reason, outcome="denied"):
    conn = None
    try:
        conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
        with conn.cursor() as cur:
            cur.execute("SELECT keel_platform_record_attempt(%s,%s,%s,%s);", (action, subject, reason, outcome))
        conn.commit()
    except DatabaseError:
        if conn is not None:
            conn.rollback()
        raise HTTPException(503, "Platform administration is temporarily unavailable.") from None
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def command(ctx, action, payload=None):
    conn = None
    payload = dict(payload or {})
    try:
        conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
        with conn.cursor() as cur:
            if action == "membership_status" and payload.get("active") is True:
                # SQL authorizes and holds authority/commercial/capacity locks before
                # the existing Python billing authority supplies the current seat limit.
                cur.execute("SELECT keel_platform_command(%s,%s);", ("membership_restore_scope", Json(payload)))
                scope = cur.fetchone()[0]
                if scope.get("error"):
                    conn.commit()  # Persist permission denial before HTTP mapping.
                    _error(scope)
                from src.ai.routers.auth import _seat_limit
                try:
                    payload["_seat_limit"] = _seat_limit(scope["tenant_id"])
                except HTTPException as exc:
                    cur.execute("SELECT keel_platform_record_attempt(%s,%s,%s,'denied');",
                                (action, str(payload.get("id")), "Existing entitlement authority refused: " + str(exc.status_code)))
                    conn.commit()
                    raise
            cur.execute("SELECT keel_platform_command(%s,%s);", (action, Json(payload)))
            result = cur.fetchone()[0]
            if isinstance(result, dict) and result.get("error") and result["error"] != "forbidden":
                cur.execute("SELECT keel_platform_record_attempt(%s,%s,%s,'denied');",
                    (action, str(payload.get("id", "platform")), result["error"]))
        # Commit denied attempts before mapping to HTTP. No domain mutation succeeds on an error result.
        conn.commit()
    except IntegrityError:
        conn.rollback()
        record_attempt(ctx, action, str(payload.get("id", "platform")), "Constraint rejected mutation")
        raise HTTPException(409, "This change conflicts with an existing record.") from None
    except DatabaseError:
        if conn is not None:
            conn.rollback()
        raise HTTPException(503, "Platform administration is temporarily unavailable.") from None
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
    return _error(result)


def search(ctx, resource, query, limit, offset):
    """Search a platform directory through its narrow authorized SQL function."""
    conn = None
    try:
        conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT public.keel_platform_search(%s,%s,%s,%s);",
                (resource, query, limit, offset),
            )
            result = cur.fetchone()[0]
        # As with keel_platform_command, persist the database-authored denial
        # audit before converting it to the established 403 response.
        conn.commit()
    except DatabaseError:
        if conn is not None:
            conn.rollback()
        raise HTTPException(503, "Platform administration is temporarily unavailable.") from None
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
    return _error(result)


def invite(ctx, payload, invitation_id=None):
    raw = security.generate_url_safe_token()
    data = {**payload, "token_hash": security.hash_token(raw), "expires_at": (
        datetime.now(timezone.utc) + timedelta(minutes=security.TEAM_INVITATION_EXPIRE_MINUTES)).isoformat()}
    if invitation_id:
        data["id"] = invitation_id
    result = command(ctx, "invitation_resend" if invitation_id else "invite", data)
    try:
        sent = notifications.send_email(result["email"], "KEEL platform invitation",
            "You have been invited to administer KEEL. Open the platform invitation page: "
            + frontend_origin() + '/platform/invitations/' + raw)
    except Exception:
        sent = False
    if not sent:
        record_attempt(ctx, "invitation_delivery", result["invitation_id"], "Invitation email not delivered", "delivery_failed")
    return {**result, "delivery": "sent" if sent else "unavailable"}


def invitation(token, payload=None):
    conn = None
    try:
        conn = db.auth_lookup_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT keel_platform_accept(%s,%s,%s);",
                        (security.hash_token(token), Json(payload or {}), payload is not None))
            result = cur.fetchone()[0]
        conn.commit()
    except IntegrityError:
        conn.rollback()
        raise HTTPException(409, "This account changed while the invitation was accepted. Try signing in.") from None
    except DatabaseError:
        if conn is not None:
            conn.rollback()
        raise HTTPException(503, "Platform administration is temporarily unavailable.") from None
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
    return _error(result)
