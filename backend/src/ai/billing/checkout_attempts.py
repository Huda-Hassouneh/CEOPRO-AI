"""Durable fixed-plan Checkout reservations; activation remains webhook-owned."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import uuid

from src.ai.billing.payment_contracts import FrozenCheckoutRequest


@contextmanager
def tenant_lock(conn, tenant_id):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", ("keel-checkout:" + tenant_id,))
    try:
        yield
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", ("keel-checkout:" + tenant_id,))
        conn.commit()


def active(conn, tenant_id):
    with conn.cursor() as cur:
        cur.execute("SELECT attempt_id,request_key,stripe_session_id,provider_params,created_at FROM billing_checkout_attempts "
                    "WHERE tenant_id=%s AND state IN ('preparing','open')", (tenant_id,))
        row = cur.fetchone()
    return dict(zip(("attempt_id","request_key","session_id","params","created_at"),row)) if row else None


def reserve(conn, tenant_id, key, plan, period):
    attempt = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("INSERT INTO billing_checkout_attempts(attempt_id,tenant_id,request_key,plan_key,period_code) VALUES(%s,%s,%s,%s,%s)",
                    (attempt,tenant_id,key,plan,period))
    conn.commit()
    return {"attempt_id":attempt,"request_key":key,"session_id":None,"params":None,"created_at":datetime.now(timezone.utc)}


def freeze(conn, attempt, params):
    with conn.cursor() as cur:
        cur.execute("UPDATE billing_checkout_attempts SET provider_params=COALESCE(provider_params,%s::jsonb) "
                    "WHERE attempt_id=%s RETURNING provider_params", (json.dumps(params),str(attempt["attempt_id"])))
        frozen = cur.fetchone()[0]
    conn.commit()
    return frozen


class FrozenCheckoutConflict(ValueError):
    """An existing immutable request belongs to another approved revision."""


def freeze_payment_request(conn, attempt, request: FrozenCheckoutRequest, *, quote_revision=None):
    """Compatibility bridge for the existing raw provider_params JSONB column.

    Keep its Stripe representation untouched; the application never rebuilds
    frozen transport evidence. No SQL, transaction or retry semantics change.
    """
    payload = freeze(conn, attempt, request.payload)
    if quote_revision is not None:
        if request.provider != "stripe" or (payload.get("metadata") or {}).get("custom_quote_revision_id") != quote_revision:
            raise FrozenCheckoutConflict("The previous revision Checkout must be reconciled first.")
    return FrozenCheckoutRequest(request.provider, request.idempotency_key, payload)


def opened(conn, attempt, session):
    with conn.cursor() as cur:
        cur.execute("UPDATE billing_checkout_attempts SET stripe_session_id=%s,state='open',updated_at=clock_timestamp() WHERE attempt_id=%s",
                    (session["id"],str(attempt["attempt_id"])))
    conn.commit()


def expire(conn, attempt):
    with conn.cursor() as cur:
        cur.execute("UPDATE billing_checkout_attempts SET state='expired',updated_at=clock_timestamp() WHERE attempt_id=%s", (str(attempt["attempt_id"]),))
    from src.ai.billing import trial_checkouts
    trial_checkouts.release(conn, attempt)
    conn.commit()
