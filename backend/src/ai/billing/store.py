"""
Billing persistence. Reads take a tenant-scoped connection (row-level
security applies). Local writes use separate restricted setup, verified-webhook
and accounting capabilities. Existing manual deployments retain their trusted
connection configuration; an administrator DSN is never a local API default.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ai.billing import config

# Stripe subscription status -> the status KEEL stores (same table as the
# reference project's billing service).
STATUS_FROM_STRIPE = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "canceled": "cancelled",
    "incomplete": "pending",
    "incomplete_expired": "expired",
    "unpaid": "payment_failed",
    "paused": "paused",
}


def _ts(value) -> Optional[datetime]:
    return datetime.fromtimestamp(int(value), tz=timezone.utc) if value else None


# --- catalog ----------------------------------------------------------------

def catalog(conn) -> list:
    """Active plans with their per-period prices and feature limits."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT plan_key, display_name, display_name_ar, monthly_price, currency, trial_days, tier_level, self_serve
            FROM usage_plans WHERE is_active ORDER BY tier_level, plan_key;
            """
        )
        plans = cursor.fetchall()
        cursor.execute("SELECT plan_key, feature_code, limit_value, trial_limit_value FROM usage_plan_limits;")
        limits = cursor.fetchall()
        cursor.execute("SELECT plan_key, feature_code FROM usage_plan_entitlements;")
        entitlements = cursor.fetchall()
        cursor.execute(
            """
            SELECT plan_key, period_code, interval_months, discount_percent, amount, currency, stripe_price_id IS NOT NULL
            FROM billing_plan_prices WHERE retired_at IS NULL ORDER BY interval_months;
            """
        )
        prices = cursor.fetchall()
    with conn.cursor() as cursor:
        cursor.execute("SELECT feature_code,unit,aggregation_type,reset_cycle,display_name,display_name_ar,description,description_ar FROM usage_features")
        feature_catalog = {row[0]: dict(zip(('unit','aggregation_type','reset_cycle','name','name_ar','description','description_ar'),row[1:])) for row in cursor.fetchall()}
    out = []
    for key, name, name_ar, monthly, currency, trial_days, tier, self_serve in plans:
        out.append({
            "plan_key": key,
            "feature_catalog": feature_catalog,
            "name": {"en": name, "ar": name_ar or name},
            "monthly_price": float(monthly) if monthly is not None else None,
            "currency": currency,
            "trial_days": trial_days,
            "tier_level": tier,
            "self_serve": self_serve,
            "limits": {code: (None if value is None else int(value)) for plan, code, value, _trial in limits if plan == key},
            # What a free trial of this plan includes where it differs (Data and AI Credits).
            "trial_limits": {code: int(trial) for plan, code, _value, trial in limits if plan == key and trial is not None},
            "entitlements": sorted(code for plan, code in entitlements if plan == key),
            "prices": [
                {
                    "period_code": period, "interval_months": months, "discount_percent": float(discount),
                    "amount": float(amount), "currency": price_currency, "purchasable": purchasable,
                }
                for plan, period, months, discount, amount, price_currency, purchasable in prices if plan == key
            ],
        })
    return out


def current_price(conn, plan_key: str, period_code: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.stripe_price_id, p.amount, p.currency, u.self_serve, u.is_active, u.tier_level, u.trial_days
            FROM billing_plan_prices p JOIN usage_plans u ON u.plan_key = p.plan_key
            WHERE p.plan_key = %s AND p.period_code = %s AND p.retired_at IS NULL;
            """,
            (plan_key, period_code),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return {
        "stripe_price_id": row[0], "amount": float(row[1]), "currency": row[2], "self_serve": row[3],
        "is_active": row[4], "tier_level": row[5], "trial_days": row[6],
    }


def plan_tier(conn, plan_key: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT tier_level FROM usage_plans WHERE plan_key = %s;", (plan_key,))
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def configured_plan_rights(conn, tenant_id: str, plan_key: str, *, trialing: bool = False) -> dict:
    """Read a plan's configured rights using the same catalog and tenant
    overrides consumed by the entitlement evaluator.

    Missing limit rows are kept absent so callers cannot mistake an
    unconfigured feature for either zero or unlimited. ``None`` in an
    existing limit row retains the catalog's established unlimited meaning.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT f.feature_code, f.unit, f.aggregation_type, f.reset_cycle,
                   l.limit_value, l.trial_limit_value, o.limit_value
            FROM usage_plan_limits l
            JOIN usage_features f ON f.feature_code = l.feature_code
            LEFT JOIN tenant_entitlement_overrides o
              ON o.tenant_id = %s AND o.feature_code = l.feature_code
            WHERE l.plan_key = %s;
            """,
            (tenant_id, plan_key),
        )
        rows = cursor.fetchall()
        cursor.execute("SELECT feature_code FROM usage_plan_entitlements WHERE plan_key = %s;", (plan_key,))
        entitlements = {row[0] for row in cursor.fetchall()}
    features = {}
    for code, unit, aggregation, reset_cycle, limit, trial_limit, override in rows:
        if override is not None:
            limit = override
        elif trialing and trial_limit is not None:
            limit = trial_limit
        features[code] = {
            "unit": unit,
            "aggregation_type": aggregation,
            "reset_cycle": reset_cycle,
            "limit": None if limit is None else int(limit),
        }
    return {"features": features, "entitlements": entitlements}


def has_custom_contract(conn, tenant_id: str) -> bool:
    """Private contracts carry terms outside the public plan-rights vector."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM tenant_custom_contracts WHERE tenant_id = %s;", (tenant_id,))
        return cursor.fetchone() is not None


def resolve_price(conn, stripe_price_id: str) -> Optional[tuple]:
    """Stripe price id -> (plan_key, period_code), retired prices included."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT plan_key, period_code FROM billing_plan_prices WHERE stripe_price_id = %s;",
            (stripe_price_id,),
        )
        return cursor.fetchone()


# --- trials -----------------------------------------------------------------

def trial_eligibility(conn, tenant_id: str, plan_key: str, started_by_user_id: Optional[str] = None) -> Optional[str]:
    """None when this company may start a free trial of this plan, else the
    reason it may not: one trial per company ever, one per person across
    their companies, never on top of a plan or subscription, and only on a
    self-serve plan that offers a trial."""
    if getattr(conn, "billing_setup_only", False):
        return _setup_trial_command(conn, tenant_id, started_by_user_id, plan_key, start=False).get("reason")
    with conn.cursor() as cursor:
        cursor.execute("SELECT trial_days, self_serve, is_active FROM usage_plans WHERE plan_key = %s;", (plan_key,))
        row = cursor.fetchone()
        if not row or not row[2] or not row[1] or int(row[0]) <= 0:
            return "plan_has_no_trial"
        cursor.execute("SELECT 1 FROM billing_trials WHERE tenant_id = %s;", (tenant_id,))
        if cursor.fetchone():
            return "trial_already_used"
        if started_by_user_id:
            cursor.execute("SELECT 1 FROM billing_trials WHERE started_by_user_id = %s;", (started_by_user_id,))
            if cursor.fetchone():
                return "trial_already_used_by_person"
        cursor.execute("SELECT 1 FROM tenant_plan_assignments WHERE tenant_id = %s;", (tenant_id,))
        if cursor.fetchone():
            return "plan_already_assigned"
        cursor.execute("SELECT 1 FROM billing_subscriptions WHERE tenant_id = %s;", (tenant_id,))
        if cursor.fetchone():
            return "subscription_exists"
    return None


def _setup_trial_command(conn, tenant_id, user_id, plan_key, *, start):
    if str(tenant_id) != conn._tenant_id or str(user_id) != conn._user_id:
        raise ValueError("Trial identity must match the authenticated billing context.")
    with conn.cursor() as cur:
        cur.execute("SELECT public.billing_setup_trial(%s,%s)", (plan_key, start))
        return cur.fetchone()[0]


def start_trial(sys_conn, tenant_id: str, now: Optional[datetime] = None, *,
                started_by_user_id: Optional[str] = None, plan_key: Optional[str] = None) -> Optional[dict]:
    """Gives a company its one free trial if it is eligible
    (trial_eligibility). The trial lasts the plan's trial_days from `now`, to
    the second (UTC). Returns the trial, or None when not granted. Caller
    commits."""
    plan_key = plan_key or config.trial_plan_key()
    if getattr(sys_conn, "billing_setup_only", False):
        if now is not None:
            raise ValueError("The restricted trial command uses database time, not a caller-selected date.")
        result = _setup_trial_command(sys_conn, tenant_id, started_by_user_id, plan_key, start=True)
        if result.get("reason"):
            return None
        return {"plan_key": result["plan_key"],
                "started_at": datetime.fromisoformat(result["started_at"]),
                "ends_at": datetime.fromisoformat(result["ends_at"])}
    now = now or datetime.now(timezone.utc)
    with sys_conn.cursor() as cursor:
        # Two sign-ups by the same person can't both pass the per-person check.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                       (f"keel_trial:{started_by_user_id or tenant_id}",))
    if trial_eligibility(sys_conn, tenant_id, plan_key, started_by_user_id):
        return None
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT trial_days FROM usage_plans WHERE plan_key = %s;", (plan_key,))
        days = int(cursor.fetchone()[0])
        ends_at = now + timedelta(days=days)
        cursor.execute(
            """
            INSERT INTO billing_trials (tenant_id, plan_key, started_at, ends_at, started_by_user_id) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO NOTHING RETURNING tenant_id;
            """,
            (tenant_id, plan_key, now, ends_at, started_by_user_id),
        )
        if cursor.fetchone() is None:
            return None
        cursor.execute(
            """
            INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, current_period_start, current_period_end, source)
            VALUES (%s, %s, 'trialing', %s, %s, 'trial')
            ON CONFLICT (tenant_id) DO NOTHING;
            """,
            (tenant_id, plan_key, now.date(), ends_at.date()),
        )
    return {"plan_key": plan_key, "started_at": now, "ends_at": ends_at}


def trial(conn, tenant_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT plan_key, started_at, ends_at FROM billing_trials WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()
    return {"plan_key": row[0], "started_at": row[1], "ends_at": row[2]} if row else None


# --- customers and subscriptions -------------------------------------------

def customer_id(conn, tenant_id: str) -> Optional[str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT stripe_customer_id FROM billing_customers WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()
    return row[0] if row else None


def save_customer(sys_conn, tenant_id: str, stripe_customer_id: str) -> None:
    if getattr(sys_conn, "verified_webhook_only", False):
        sys_conn.bind_tenant(tenant_id)
    with sys_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO billing_customers (tenant_id, stripe_customer_id) VALUES (%s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET stripe_customer_id = EXCLUDED.stripe_customer_id;
            """,
            (tenant_id, stripe_customer_id),
        )


def tenant_for_customer(sys_conn, stripe_customer_id: str) -> Optional[str]:
    if getattr(sys_conn, "verified_webhook_only", False):
        with sys_conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_provider_tenant(%s,%s)", ("customer", stripe_customer_id))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT tenant_id FROM billing_customers WHERE stripe_customer_id = %s;", (stripe_customer_id,))
        row = cursor.fetchone()
    return str(row[0]) if row else None


def tenant_for_subscription(sys_conn, stripe_subscription_id: str) -> Optional[str]:
    if getattr(sys_conn, "verified_webhook_only", False):
        with sys_conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_provider_tenant(%s,%s)", ("subscription", stripe_subscription_id))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None
    with sys_conn.cursor() as cursor:
        cursor.execute(
            "SELECT tenant_id FROM billing_subscriptions WHERE stripe_subscription_id = %s;", (stripe_subscription_id,)
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


_SUB_COLUMNS = (
    "subscription_id, stripe_subscription_id, stripe_customer_id, plan_key, period_code, status, "
    "current_period_start, current_period_end, trial_end, cancel_at_period_end, cancelled_at, "
    "scheduled_plan_key, scheduled_period_code"
)


def _sub_row(row) -> Optional[dict]:
    if not row:
        return None
    keys = [c.strip() for c in _SUB_COLUMNS.split(",")]
    return dict(zip(keys, row))


def current_subscription(conn, tenant_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {_SUB_COLUMNS} FROM billing_subscriptions
            WHERE tenant_id = %s AND status = ANY(%s)
            ORDER BY created_at DESC LIMIT 1;
            """,
            (tenant_id, list(config.CURRENT_STATUSES)),
        )
        return _sub_row(cursor.fetchone())


def period_bounds(stripe_sub: dict) -> tuple:
    """Current period from the subscription item (newer Stripe API versions)
    or the subscription itself (older ones)."""
    items = (stripe_sub.get("items") or {}).get("data") or []
    item = items[0] if items else {}
    start = item.get("current_period_start") or stripe_sub.get("current_period_start")
    end = item.get("current_period_end") or stripe_sub.get("current_period_end")
    return _ts(start), _ts(end)


def subscription_price_id(stripe_sub: dict) -> Optional[str]:
    items = (stripe_sub.get("items") or {}).get("data") or []
    return ((items[0].get("price") or {}).get("id")) if items else None


def apply_subscription(
    sys_conn, tenant_id: str, stripe_sub: dict, plan_key: str, period_code: str, event_created: datetime,
) -> dict:
    """Stores Stripe's current view of a subscription and makes the company's
    plan follow it. Only ever called with a subscription freshly retrieved
    from Stripe, so a late or repeated event can't roll it back."""
    status = STATUS_FROM_STRIPE.get(stripe_sub.get("status"), "pending")
    period_start, period_end = period_bounds(stripe_sub)
    customer = stripe_sub.get("customer")
    customer = customer.get("id") if isinstance(customer, dict) else customer
    with sys_conn.cursor() as cursor:
        # Different subscription objects share one commercial assignment.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                       ("keel_billing_tenant:" + str(tenant_id),))
        cursor.execute(
            f"""
            INSERT INTO billing_subscriptions
                (tenant_id, stripe_subscription_id, stripe_customer_id, stripe_price_id, plan_key, period_code, status,
                 current_period_start, current_period_end, trial_end, cancel_at_period_end, cancelled_at, last_event_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (stripe_subscription_id) DO UPDATE SET
                stripe_customer_id = EXCLUDED.stripe_customer_id, stripe_price_id = EXCLUDED.stripe_price_id,
                plan_key = EXCLUDED.plan_key, period_code = EXCLUDED.period_code, status = EXCLUDED.status,
                current_period_start = EXCLUDED.current_period_start, current_period_end = EXCLUDED.current_period_end,
                trial_end = EXCLUDED.trial_end, cancel_at_period_end = EXCLUDED.cancel_at_period_end,
                cancelled_at = EXCLUDED.cancelled_at,
                scheduled_plan_key = CASE WHEN EXCLUDED.status IN ('cancelled', 'expired') THEN NULL
                                          WHEN billing_subscriptions.scheduled_plan_key = EXCLUDED.plan_key
                                           AND billing_subscriptions.scheduled_period_code = EXCLUDED.period_code THEN NULL
                                          ELSE billing_subscriptions.scheduled_plan_key END,
                scheduled_period_code = CASE WHEN EXCLUDED.status IN ('cancelled', 'expired') THEN NULL
                                             WHEN billing_subscriptions.scheduled_plan_key = EXCLUDED.plan_key
                                              AND billing_subscriptions.scheduled_period_code = EXCLUDED.period_code THEN NULL
                                             ELSE billing_subscriptions.scheduled_period_code END,
                last_event_at = GREATEST(billing_subscriptions.last_event_at, EXCLUDED.last_event_at),
                updated_at = CURRENT_TIMESTAMP
            WHERE billing_subscriptions.tenant_id = EXCLUDED.tenant_id
            RETURNING {_SUB_COLUMNS};
            """,
            (
                tenant_id, stripe_sub["id"], customer, subscription_price_id(stripe_sub), plan_key, period_code, status,
                period_start, period_end, _ts(stripe_sub.get("trial_end")), bool(stripe_sub.get("cancel_at_period_end")),
                _ts(stripe_sub.get("canceled_at")), event_created,
            ),
        )
        saved = cursor.fetchone()
        if saved is None:
            raise ValueError("subscription is already assigned to another company")
        row = _sub_row(saved)
        cursor.execute(
            "SELECT 1 FROM billing_subscriptions WHERE tenant_id=%s "
            "AND stripe_subscription_id<>%s AND status=ANY(%s);",
            (tenant_id, stripe_sub["id"], list(config.CURRENT_STATUSES)),
        )
        if cursor.fetchone():
            # Preserve history without revoking a replacement subscription.
            return row
        # The company's plan follows its live subscription. A subscription that
        # ended only replaces the plan if it was the one in force.
        cursor.execute(
            """
            INSERT INTO tenant_plan_assignments
                (tenant_id, plan_key, status, current_period_start, current_period_end, period_code, source, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'stripe', CURRENT_TIMESTAMP)
            ON CONFLICT (tenant_id) DO UPDATE SET
                plan_key = EXCLUDED.plan_key, status = EXCLUDED.status,
                current_period_start = EXCLUDED.current_period_start, current_period_end = EXCLUDED.current_period_end,
                period_code = EXCLUDED.period_code, source = 'stripe', updated_at = CURRENT_TIMESTAMP
            WHERE EXCLUDED.status = ANY(%s) OR tenant_plan_assignments.source = 'stripe';
            """,
            (
                tenant_id, plan_key, status, period_start.date() if period_start else None,
                period_end.date() if period_end else None, period_code, list(config.CURRENT_STATUSES),
            ),
        )
    return row


def set_schedule(sys_conn, tenant_id: str, stripe_subscription_id: str, plan_key, period_code) -> None:
    if getattr(sys_conn, "billing_setup_only", False):
        with sys_conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_setup_schedule(%s,%s,%s)", (stripe_subscription_id,plan_key,period_code))
        return
    with sys_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE billing_subscriptions SET scheduled_plan_key = %s, scheduled_period_code = %s, updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s AND stripe_subscription_id = %s;
            """,
            (plan_key, period_code, tenant_id, stripe_subscription_id),
        )


# --- payments ---------------------------------------------------------------

def _minor_to_major(amount: int, currency: str) -> float:
    # ISK and UGX are compatibility exceptions in Stripe: their API amounts
    # still use two-decimal representation (with a trailing 00), despite the
    # currencies having no fractional charge unit.
    zero_decimal = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "vnd", "vuv", "xaf", "xof", "xpf"}
    return float(amount) if currency.lower() in zero_decimal else round(amount / 100.0, 2)


def record_payment(sys_conn, tenant_id: str, invoice: dict, subscription_id: Optional[str],
                   status: str, failure_reason: Optional[str] = None) -> None:
    """One row per invoice; a later success replaces an earlier failure."""
    currency = (invoice.get("currency") or "usd").upper()
    amount_minor = invoice.get("amount_paid") if status == "succeeded" else invoice.get("amount_due")
    lines = ((invoice.get("lines") or {}).get("data") or [])
    period = (lines[0].get("period") or {}) if lines else {}
    paid_at = (invoice.get("status_transitions") or {}).get("paid_at")
    with sys_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO billing_payments
                (tenant_id, stripe_invoice_id, stripe_subscription_id, amount, currency, status, paid_at, failure_reason,
                 hosted_invoice_url, invoice_pdf_url, period_start, period_end)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (stripe_invoice_id) DO UPDATE SET
                amount = EXCLUDED.amount, status = EXCLUDED.status, paid_at = EXCLUDED.paid_at,
                failure_reason = EXCLUDED.failure_reason, hosted_invoice_url = EXCLUDED.hosted_invoice_url,
                invoice_pdf_url = EXCLUDED.invoice_pdf_url
            WHERE billing_payments.tenant_id = EXCLUDED.tenant_id
              AND (billing_payments.status <> 'succeeded' OR EXCLUDED.status = 'succeeded');
            """,
            (
                tenant_id, invoice["id"], subscription_id, _minor_to_major(amount_minor or 0, currency), currency, status,
                (_ts(paid_at) or datetime.now(timezone.utc)) if status == "succeeded" else None, failure_reason,
                invoice.get("hosted_invoice_url"), invoice.get("invoice_pdf"),
                _ts(period.get("start")), _ts(period.get("end")),
            ),
        )


def payments(conn, tenant_id: str, limit: int = 24) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT stripe_invoice_id, amount, currency, status, paid_at, failure_reason, hosted_invoice_url,
                   invoice_pdf_url, period_start, period_end, created_at
            FROM billing_payments WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s;
            """,
            (tenant_id, limit),
        )
        rows = cursor.fetchall()
    keys = ("invoice_id", "amount", "currency", "status", "paid_at", "failure_reason", "hosted_invoice_url",
            "invoice_pdf_url", "period_start", "period_end", "created_at")
    out = []
    for row in rows:
        item = dict(zip(keys, row))
        item["amount"] = float(item["amount"])
        for key in ("paid_at", "period_start", "period_end", "created_at"):
            item[key] = item[key].isoformat() if item[key] else None
        out.append(item)
    return out


# --- webhook audit ----------------------------------------------------------

def claim_event(sys_conn, event_id: str, event_type: str, created: datetime, payload: dict) -> bool:
    """True when this event still needs processing: inserted now, or stored
    earlier but never finished (Stripe is retrying after a failure)."""
    import json

    with sys_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO billing_webhook_events (stripe_event_id, event_type, event_created, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (stripe_event_id) DO NOTHING RETURNING stripe_event_id;
            """,
            (event_id, event_type, created, json.dumps(payload, default=str)),
        )
        if cursor.fetchone():
            return True
        # Row lock for the rest of this transaction only; webhooks.handle_event also holds an
        # event-wide advisory lock, which is what actually keeps two deliveries from both running.
        cursor.execute(
            "SELECT processed_at FROM billing_webhook_events WHERE stripe_event_id = %s FOR UPDATE;", (event_id,)
        )
        row = cursor.fetchone()
    pending = row is not None and row[0] is None
    if pending and getattr(sys_conn, "verified_webhook_only", False):
        with sys_conn.cursor() as cursor:
            cursor.execute("UPDATE billing_webhook_events SET error=NULL WHERE stripe_event_id=%s", (event_id,))
    return pending


def finish_event(sys_conn, event_id: str, tenant_id: Optional[str], error: Optional[str] = None) -> None:
    with sys_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE billing_webhook_events
            SET processed_at = CASE WHEN %s IS NULL THEN CURRENT_TIMESTAMP ELSE NULL END, error = %s, tenant_id = COALESCE(%s,tenant_id)
            WHERE stripe_event_id = %s;
            """,
            (error, error, tenant_id, event_id),
        )


def subscription_price_snapshot(conn, tenant_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT p.amount,p.currency,p.interval_months FROM billing_subscriptions s
          LEFT JOIN billing_plan_prices p ON p.stripe_price_id=s.stripe_price_id
          WHERE s.tenant_id=%s AND s.status=ANY(%s) ORDER BY s.updated_at DESC LIMIT 1""",
          (tenant_id,list(config.CURRENT_STATUSES)))
        row=cur.fetchone()
    return {'amount':float(row[0]) if row and row[0] is not None else None,
            'currency':row[1] if row and row[1] else 'USD','intervalUnit':'month',
            'intervalCount':row[2] if row and row[2] else 1}


def checkout_subscription_ended(conn, tenant_id, subscription_id):
    if not subscription_id:
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM billing_subscriptions WHERE tenant_id=%s AND stripe_subscription_id=%s",(tenant_id,subscription_id))
        row=cur.fetchone()
    return bool(row and row[0] in ('cancelled','expired'))
