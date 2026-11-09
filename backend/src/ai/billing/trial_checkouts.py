"""Dormant atomic reservations, never trial issuance or entitlement evidence.

Caller owns commit/rollback. No provider calls or independently committing
legacy helpers are composed here. Readiness and activation remain unimplemented.
"""
from psycopg2.extras import Json
from src.ai.billing.payment_bindings import _setup


def approved_terms(conn, plan_key, period_code):
    _setup(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT public.billing_trial_checkout_terms(%s,%s)", (plan_key, period_code))
        return cur.fetchone()[0]


def reserve(conn, attempt_id, terms):
    _setup(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT public.billing_reserve_trial_checkout(%s,%s)", (str(attempt_id), Json(terms)))
        return cur.fetchone()[0]


def operation(conn, attempt_id, action, *, payload=None, replay_window_seconds=None, session=None):
    _setup(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT public.billing_trial_operation(%s,%s,%s,%s,%s)",
                    (str(attempt_id), action, Json(payload) if payload is not None else None,
                     replay_window_seconds, session))
        return cur.fetchone()[0]
