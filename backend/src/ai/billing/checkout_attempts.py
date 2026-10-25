"""Durable fixed-plan Checkout reservations; activation remains webhook-owned."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import uuid


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


def opened(conn, attempt, session):
    with conn.cursor() as cur:
        cur.execute("UPDATE billing_checkout_attempts SET stripe_session_id=%s,state='open',updated_at=clock_timestamp() WHERE attempt_id=%s",
                    (session["id"],str(attempt["attempt_id"])))
    conn.commit()


def expire(conn, attempt):
    with conn.cursor() as cur:
        cur.execute("UPDATE billing_checkout_attempts SET state='expired',updated_at=clock_timestamp() WHERE attempt_id=%s", (str(attempt["attempt_id"]),))
    conn.commit()
