"""
KEEL - Data Credits and AI Credits: per-company spending budgets enforced
around every paid provider call (docs/SUBSCRIPTIONS_AND_CREDITS.md).

Every billable call follows the same path:

    with credits.metering(tenant_id, "assistant_question", usage_class="simple_question"):
        ...
        with credits.provider_call("ai", "groq", "openai/gpt-oss-20b", {"input_token": 900, "output_token": 1000}) as call:
            response = provider(...)
            call.measured({"input_token": ..., "output_token": ...}, provider_request_id=...)

1. reserve (before the call, its own committed transaction): the company's
   plan must grant access; the provider must not be switched off or over
   its platform cap; the operation's estimated cost (units x the provider's
   configured price, plus a safety margin) must fit in what's left of this
   period's budget. The balance row is updated under a per-company lock, so
   concurrent requests can never spend the same credits twice.
2. call the provider.
3. settle (its own committed transaction): the reservation becomes the real
   cost. A call that reached the provider and failed is still charged when
   that provider bills failures; a call that never reached it is released.

Fail closed: no company context, no configured price, or the accounting
database unavailable -> the paid call is refused, never made. Providers
that charge nothing (configured at 0) skip all of this. Money (USD) and
credits are stored separately; credits = cost / credit_usd_value.

A reservation left 'reserved' (the process died mid-call) keeps counting
against the budget; expire_stale_reservations() later charges its estimate
and marks it for reconciliation, so a crash never makes spending free.
"""
import contextvars
import hashlib
import itertools
import logging
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from typing import Callable, Dict, Iterator, Optional

from fastapi import HTTPException

logger = logging.getLogger("KEEL_CREDITS")

DATA, AI = "data", "ai"
FEATURE_FOR_BUDGET = {DATA: "data_credits", AI: "ai_credits"}

# System-initiated work allowed to finish past an exhausted budget. Never
# reachable from a customer request (see metering(allow_over_budget=...)).
RECOVERY_OPERATIONS = frozenset({"reconciliation", "admin_recovery"})

_HTTP_STATUS = {
    "SUBSCRIPTION_INACTIVE": 402, "BUDGET_EXHAUSTED": 402, "DUPLICATE_REQUEST": 409, "CONCURRENCY_LIMIT": 429,
    "REQUEST_TOO_LARGE": 413, "COST_NOT_CONFIGURED": 503, "PROVIDER_DISABLED": 503, "PROVIDER_CAP_REACHED": 503,
    "NO_BILLING_CONTEXT": 503, "ACCOUNTING_UNAVAILABLE": 503,
}
_MESSAGES = {
    "SUBSCRIPTION_INACTIVE": "Your subscription isn't active. Update your plan in Billing to continue.",
    "BUDGET_EXHAUSTED": {
        DATA: "Your plan's Data Credits for this billing period have been used. They renew on {renews}. "
              "You can upgrade your plan in Billing.",
        AI: "Your plan's AI Credits for this billing period have been used. They renew on {renews}. "
            "You can upgrade your plan in Billing.",
    },
    "DUPLICATE_REQUEST": "This request was already processed.",
    "CONCURRENCY_LIMIT": "Your company already has several AI requests running. Please wait for them to finish.",
    "REQUEST_TOO_LARGE": "This request is too large to process. Please shorten it.",
    "COST_NOT_CONFIGURED": "This service isn't available yet: its pricing hasn't been set up on this server.",
    "PROVIDER_DISABLED": "This service is temporarily switched off. Please try again later.",
    "PROVIDER_CAP_REACHED": "This service has reached its spending limit for the month. Please try again later.",
    "NO_BILLING_CONTEXT": "This request couldn't be attributed to a company and was not run.",
    "ACCOUNTING_UNAVAILABLE": "Usage accounting is temporarily unavailable, so this request was not run. Please try again shortly.",
}


class BudgetError(Exception):
    """A paid call refused before it was made."""

    def __init__(self, reason: str, budget_kind: Optional[str] = None, *, limit=None, used=None,
                 period_end: Optional[date] = None, detail: Optional[str] = None):
        super().__init__(f"{reason} ({budget_kind or '-'}): {detail or ''}".strip())
        self.reason, self.budget_kind = reason, budget_kind
        self.limit, self.used, self.period_end, self.detail = limit, used, period_end, detail

    @property
    def status_code(self) -> int:
        return _HTTP_STATUS.get(self.reason, 503)

    def message(self) -> str:
        text = _MESSAGES.get(self.reason, _MESSAGES["ACCOUNTING_UNAVAILABLE"])
        if isinstance(text, dict):
            text = text.get(self.budget_kind or DATA)
        renews = (self.period_end + timedelta(days=1)).isoformat() if self.period_end else "the next billing period"
        return text.format(renews=renews)

    def as_http(self) -> HTTPException:
        """Safe for customers: the reason code and plain message, never provider
        names, prices or internal detail."""
        remaining = None
        if self.limit is not None and self.used is not None:
            remaining = float(max(Decimal("0"), Decimal(str(self.limit)) - Decimal(str(self.used))))
        return HTTPException(status_code=self.status_code, detail={
            "reason": self.reason, "budget": self.budget_kind, "message": self.message(),
            "limit": float(self.limit) if self.limit is not None else None,
            "used": float(self.used) if self.used is not None else None, "remaining": remaining,
            "period_end": self.period_end.isoformat() if self.period_end else None,
        })


# --- Context: which company a paid call is for -----------------------------

@dataclass
class MeteringContext:
    tenant_id: str
    operation_type: str
    usage_class: Optional[str] = None
    actor_user_id: Optional[str] = None
    operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: Optional[str] = None
    allow_over_budget: bool = False
    steps: Iterator = field(default_factory=itertools.count)
    spent_credits: Dict[str, Decimal] = field(default_factory=dict)


_CURRENT: contextvars.ContextVar = contextvars.ContextVar("keel_metering", default=None)


def current() -> Optional[MeteringContext]:
    return _CURRENT.get()


@contextmanager
def metering(tenant_id: str, operation_type: str, *, usage_class: Optional[str] = None,
             actor_user_id: Optional[str] = None, idempotency_key: Optional[str] = None,
             allow_over_budget: bool = False):
    """Attributes every paid call inside the block to this company and
    operation. idempotency_key (from the client's Idempotency-Key header, or
    a deterministic job key) makes a replayed operation refuse to charge -
    and to run - a second time. allow_over_budget is only for system recovery
    and reconciliation work (RECOVERY_OPERATIONS), never customer requests."""
    if allow_over_budget and operation_type not in RECOVERY_OPERATIONS:
        raise ValueError("only recovery operations may run past an exhausted budget")
    ctx = MeteringContext(str(tenant_id), operation_type, usage_class, str(actor_user_id) if actor_user_id else None,
                          idempotency_key=idempotency_key, allow_over_budget=allow_over_budget)
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def metered(operation_type: str, usage_class: Optional[str] = None) -> Callable:
    """Decorator for a unit of work that may call paid providers: runs it
    inside metering() for its `tenant_id` argument. Inside an existing
    scope for the same company (web research during an assistant question),
    the outer scope is kept."""
    import functools
    import inspect

    def decorate(fn: Callable) -> Callable:
        signature = inspect.signature(fn)
        if "tenant_id" not in signature.parameters:
            raise TypeError(f"{fn.__name__} has no tenant_id parameter to meter")

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tenant_id = signature.bind_partial(*args, **kwargs).arguments.get("tenant_id")
            outer = current()
            if tenant_id is None or (outer is not None and outer.tenant_id == str(tenant_id)):
                return fn(*args, **kwargs)
            with metering(tenant_id, operation_type, usage_class=usage_class):
                return fn(*args, **kwargs)

        return wrapper

    return decorate


def bind(fn: Callable) -> Callable:
    """fn, running in a copy of the caller's context - for worker threads
    (ThreadPoolExecutor doesn't carry context variables over on its own)."""
    snapshot = contextvars.copy_context()

    def run(*args, **kwargs):
        # A context can be entered by one thread at a time: each call gets its own copy.
        return snapshot.copy().run(fn, *args, **kwargs)

    return run


# --- Configuration -----------------------------------------------------------

def _system_connection():
    from src.ai import db

    return db.system_connection()


def policy(conn) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT credit_usd_value, target_contribution_margin, default_safety_margin, warning_thresholds,
                   max_ai_concurrency, max_ai_input_tokens, max_ai_output_tokens, reservation_timeout_seconds,
                   top_ups_enabled, ai_fallback_policy
            FROM billing_cost_policy WHERE policy_id;
            """
        )
        row = cursor.fetchone()
    if not row:
        raise BudgetError("ACCOUNTING_UNAVAILABLE", detail="billing_cost_policy has no row")
    keys = ("credit_usd_value", "target_contribution_margin", "default_safety_margin", "warning_thresholds",
            "max_ai_concurrency", "max_ai_input_tokens", "max_ai_output_tokens", "reservation_timeout_seconds",
            "top_ups_enabled", "ai_fallback_policy")
    return dict(zip(keys, row))


def schedule(conn, budget_kind: str, provider: str, operation: str) -> Dict[str, dict]:
    """unit -> {cost, margin, charged_on_failure, final} for this provider
    operation; an operation-specific price wins over the provider's '*' row."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT unit, unit_cost_usd, safety_margin, charged_on_failure, cost_is_final, operation
            FROM provider_cost_schedules
            WHERE budget_kind = %s AND provider = %s AND operation IN (%s, '*')
            ORDER BY (operation = '*');
            """,
            (budget_kind, provider, operation),
        )
        rows = cursor.fetchall()
    out: Dict[str, dict] = {}
    for unit, cost, margin, charged, final, _op in rows:
        out.setdefault(unit, {"cost": cost, "margin": margin, "charged_on_failure": charged, "final": final})
    return out


def _cost(prices: Dict[str, dict], units: Dict[str, float], budget_kind: str, provider: str, operation: str) -> Decimal:
    total = Decimal("0")
    for unit, amount in units.items():
        if not amount:
            continue
        price = prices.get(unit)
        if (price is None or price["cost"] is None) and unit == "cache_read_token":
            price = prices.get("input_token")  # never cheaper than a cache read
        if price is None or price["cost"] is None:
            raise BudgetError("COST_NOT_CONFIGURED", budget_kind,
                              detail=f"no confirmed {unit} price for {provider}/{operation}")
        total += Decimal(str(price["cost"])) * Decimal(str(amount))
    return total


def is_free(conn, budget_kind: str, provider: str, operation: str, units: Dict[str, float]) -> bool:
    prices = schedule(conn, budget_kind, provider, operation)
    try:
        return _cost(prices, units, budget_kind, provider, operation) == 0 and all(
            prices.get(u) and prices[u]["cost"] is not None for u, a in units.items() if a)
    except BudgetError:
        return False


def _bypassed_for_tests() -> bool:
    """Unit tests that mock providers without a database switch metering off
    (tests/conftest.py). Honoured only while pytest is running a test, so
    no setting can turn metering off in a deployment."""
    return os.getenv("KEEL_TEST_DISABLE_METERING") == "1" and "PYTEST_CURRENT_TEST" in os.environ


def _to_credits(cost: Decimal, credit_value: Decimal) -> Decimal:
    return (cost / credit_value).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)


def _lock(cursor, *parts: str) -> None:
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));", (":".join(parts),))


# --- Plan budget -------------------------------------------------------------

def _budget(conn, tenant_id: str, budget_kind: str) -> dict:
    from src.ai.core import usage

    plan = usage.get_plan(conn, tenant_id)
    feature = plan["features"].get(FEATURE_FOR_BUDGET[budget_kind])
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT subscription_id FROM billing_subscriptions
            WHERE tenant_id = %s AND status IN ('trialing', 'active', 'past_due', 'pending', 'payment_failed', 'paused')
            ORDER BY created_at DESC LIMIT 1;
            """,
            (tenant_id,),
        )
        sub = cursor.fetchone()
    return {
        "plan_key": plan["plan_key"], "status": plan["status"], "period_start": plan["period_start"],
        "period_end": plan["period_end"], "has_access": plan["status"] in usage.ACCESS_GRANTING_STATUSES,
        # A plan with no budget row for this kind grants nothing (fail closed).
        "limit": Decimal(feature["limit"]) if feature and feature["limit"] is not None else (
            None if feature else Decimal("0")),
        "subscription_id": str(sub[0]) if sub else None,
    }


def ensure_available(tenant_id: str, budget_kind: str, conn_factory: Callable = None) -> None:
    """Before starting discretionary work (a discovery run): refuses up front
    when the company has no access or no credits left this period, instead
    of starting work whose every paid call would be refused. Fails closed."""
    if _bypassed_for_tests():
        return
    try:
        conn = (conn_factory or _system_connection)()
    except Exception as exc:  # noqa: BLE001
        raise BudgetError("ACCOUNTING_UNAVAILABLE", budget_kind, detail=type(exc).__name__) from exc
    try:
        budget = _budget(conn, str(tenant_id), budget_kind)
        if not budget["has_access"]:
            raise BudgetError("SUBSCRIPTION_INACTIVE", budget_kind)
        used = balance(conn, str(tenant_id), budget_kind, budget["period_start"])
        spent = used["consumed"] + used["reserved"]
        if budget["limit"] is not None and spent >= budget["limit"]:
            raise BudgetError("BUDGET_EXHAUSTED", budget_kind, limit=budget["limit"], used=spent,
                              period_end=budget["period_end"])
    except BudgetError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed
        raise BudgetError("ACCOUNTING_UNAVAILABLE", budget_kind, detail=type(exc).__name__) from exc
    finally:
        conn.close()


def requires_budget(budget_kind: str):
    """FastAPI dependency: ensure_available() for the signed-in company, for
    endpoints that start discretionary paid collection."""
    from fastapi import Depends

    from src.ai.core.security import TenantContext, get_tenant_context

    def dependency(ctx: TenantContext = Depends(get_tenant_context)) -> None:
        ensure_available(ctx.tenant_id, budget_kind)

    return Depends(dependency)


def balance(conn, tenant_id: str, budget_kind: str, period_start: date) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT reserved_credits, consumed_credits, consumed_cost_usd FROM tenant_credit_balances
            WHERE tenant_id = %s AND budget_kind = %s AND period_start = %s;
            """,
            (tenant_id, budget_kind, period_start),
        )
        row = cursor.fetchone()
    reserved, consumed, cost = row if row else (Decimal("0"), Decimal("0"), Decimal("0"))
    return {"reserved": Decimal(reserved), "consumed": Decimal(consumed), "consumed_cost_usd": Decimal(cost)}


def _provider_controls(cursor, provider: str, model: Optional[str]) -> list:
    keys = ["*", provider] + ([f"{provider}:{model}"] if model else [])
    cursor.execute(
        "SELECT provider, monthly_cap_usd, kill_switch FROM provider_spend_controls WHERE provider = ANY(%s);", (keys,)
    )
    return cursor.fetchall()


def _provider_month_spend(cursor, provider: Optional[str], model: Optional[str], month_start: datetime) -> Decimal:
    """This month's spend (settled, or estimated while in flight) for one
    provider, one of its models, or - provider None - every provider."""
    cursor.execute(
        """
        SELECT COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd)), 0) FROM usage_ledger
        WHERE (%s::text IS NULL OR provider = %s) AND (%s::text IS NULL OR provider_operation = %s)
          AND created_at >= %s AND status <> 'released';
        """,
        (provider, provider, model, model, month_start),
    )
    return Decimal(cursor.fetchone()[0])


# --- Reserve / settle --------------------------------------------------------

@dataclass
class Reservation:
    ledger_id: Optional[str]
    tenant_id: str
    budget_kind: str
    provider: str
    operation: str
    period_start: Optional[date]
    reserved_credits: Decimal
    estimated_cost_usd: Decimal
    free: bool = False
    settled: bool = False


def reserve(budget_kind: str, provider: str, operation: str, estimated_units: Dict[str, float], *,
            idempotency_key: Optional[str] = None, conn_factory: Callable = None) -> Reservation:
    """Takes the estimated cost of one provider call out of the company's
    budget, or raises BudgetError. Commits on its own connection."""
    ctx = current()
    if _bypassed_for_tests():
        return Reservation(None, ctx.tenant_id if ctx else "", budget_kind, provider, operation, None,
                           Decimal("0"), Decimal("0"), free=True)
    factory = conn_factory or _system_connection
    try:
        conn = factory()
    except Exception as exc:  # noqa: BLE001 - no accounting, no paid call
        raise BudgetError("ACCOUNTING_UNAVAILABLE", budget_kind, detail=type(exc).__name__) from exc
    try:
        prices = schedule(conn, budget_kind, provider, operation)
        estimated_cost = _cost(prices, estimated_units, budget_kind, provider, operation)
        if estimated_cost == 0 and all(prices.get(u) for u, a in estimated_units.items() if a):
            conn.rollback()
            return Reservation(None, ctx.tenant_id if ctx else "", budget_kind, provider, operation, None,
                               Decimal("0"), Decimal("0"), free=True)
        if ctx is None:
            raise BudgetError("NO_BILLING_CONTEXT", budget_kind, detail=f"{provider}/{operation} called outside metering()")
        pol = policy(conn)
        margins = [Decimal(str(p["margin"])) for u, p in prices.items() if estimated_units.get(u) and p["margin"] is not None]
        margin = max(margins) if margins else Decimal(str(pol["default_safety_margin"]))
        credits_needed = _to_credits(estimated_cost * (Decimal("1") + margin), Decimal(str(pol["credit_usd_value"])))

        if budget_kind == AI:
            input_tokens = estimated_units.get("input_token", 0) + estimated_units.get("cache_read_token", 0) \
                + estimated_units.get("cache_write_token", 0)
            if input_tokens > pol["max_ai_input_tokens"] or estimated_units.get("output_token", 0) > pol["max_ai_output_tokens"]:
                raise BudgetError("REQUEST_TOO_LARGE", budget_kind)

        step = next(ctx.steps) + 1  # atomic: steps may run in worker threads
        key = idempotency_key or (f"{ctx.idempotency_key}:{step}" if ctx.idempotency_key else str(uuid.uuid4()))
        key = key if len(key) <= 200 else hashlib.sha256(key.encode()).hexdigest()
        with conn.cursor() as cursor:
            _lock(cursor, "keel_credits", ctx.tenant_id, budget_kind)
            cursor.execute("SELECT status FROM usage_ledger WHERE tenant_id = %s AND idempotency_key = %s;",
                           (ctx.tenant_id, key))
            if cursor.fetchone():
                raise BudgetError("DUPLICATE_REQUEST", budget_kind)

            budget = _budget(conn, ctx.tenant_id, budget_kind)
            over_budget_allowed = ctx.allow_over_budget and ctx.operation_type in RECOVERY_OPERATIONS
            if not budget["has_access"] and not over_budget_allowed:
                raise BudgetError("SUBSCRIPTION_INACTIVE", budget_kind)

            for name, cap, kill in _provider_controls(cursor, provider, operation if budget_kind == AI else None):
                if kill:
                    raise BudgetError("PROVIDER_DISABLED", budget_kind, detail=name)
                if cap is not None:
                    _lock(cursor, "keel_provider_cap", name)
                    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    model = name.split(":", 1)[1] if ":" in name else None
                    scope = None if name == "*" else provider  # the global cap counts every provider
                    if _provider_month_spend(cursor, scope, model, month_start) + estimated_cost > Decimal(cap):
                        raise BudgetError("PROVIDER_CAP_REACHED", budget_kind, detail=name)

            if budget_kind == AI:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM usage_ledger
                    WHERE tenant_id = %s AND budget_kind = 'ai' AND status = 'reserved'
                      AND created_at > NOW() - make_interval(secs => %s);
                    """,
                    (ctx.tenant_id, pol["reservation_timeout_seconds"]),
                )
                if cursor.fetchone()[0] >= pol["max_ai_concurrency"]:
                    raise BudgetError("CONCURRENCY_LIMIT", budget_kind)

            cursor.execute(
                """
                INSERT INTO tenant_credit_balances (tenant_id, budget_kind, period_start, period_end)
                VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, budget_kind, period_start) DO NOTHING;
                """,
                (ctx.tenant_id, budget_kind, budget["period_start"], budget["period_end"]),
            )
            cursor.execute(
                """
                UPDATE tenant_credit_balances SET reserved_credits = reserved_credits + %(need)s, updated_at = NOW()
                WHERE tenant_id = %(t)s AND budget_kind = %(k)s AND period_start = %(p)s
                  AND (%(limit)s::numeric IS NULL OR %(over)s
                       OR consumed_credits + reserved_credits + %(need)s <= %(limit)s::numeric)
                RETURNING consumed_credits + reserved_credits;
                """,
                {"need": credits_needed, "t": ctx.tenant_id, "k": budget_kind, "p": budget["period_start"],
                 "limit": budget["limit"], "over": over_budget_allowed},
            )
            if cursor.fetchone() is None:
                used = balance(conn, ctx.tenant_id, budget_kind, budget["period_start"])
                raise BudgetError("BUDGET_EXHAUSTED", budget_kind, limit=budget["limit"],
                                  used=used["consumed"] + used["reserved"], period_end=budget["period_end"])
            cursor.execute(
                """
                INSERT INTO usage_ledger
                    (tenant_id, subscription_id, plan_key, plan_status, budget_kind, period_start, operation_id,
                     operation_type, usage_class, provider, provider_operation, idempotency_key, status,
                     estimated_units, estimated_cost_usd, reserved_credits, actor_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'reserved', %s::jsonb, %s, %s, %s)
                RETURNING ledger_id;
                """,
                (ctx.tenant_id, budget["subscription_id"], budget["plan_key"], budget["status"], budget_kind,
                 budget["period_start"], ctx.operation_id, ctx.operation_type, ctx.usage_class, provider, operation,
                 key, _json(estimated_units), estimated_cost, credits_needed, ctx.actor_user_id),
            )
            ledger_id = str(cursor.fetchone()[0])
        conn.commit()
        return Reservation(ledger_id, ctx.tenant_id, budget_kind, provider, operation, budget["period_start"],
                           credits_needed, estimated_cost)
    except BudgetError:
        conn.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed
        conn.rollback()
        logger.exception("credit reservation failed (%s/%s)", provider, operation)
        raise BudgetError("ACCOUNTING_UNAVAILABLE", budget_kind, detail=type(exc).__name__) from exc
    finally:
        conn.close()


def _json(value) -> str:
    import json

    return json.dumps(value or {}, sort_keys=True, default=str)


def settle(reservation: Reservation, measured_units: Optional[Dict[str, float]], *, failed: bool = False,
           reached_provider: bool = True, provider_request_id: Optional[str] = None,
           error_code: Optional[str] = None, conn_factory: Callable = None) -> Optional[Decimal]:
    """Turns a reservation into what the call really cost. measured_units None
    = the provider didn't report usage: the estimate is charged and the row
    waits for reconciliation. Returns the credits consumed. Never raises:
    a settlement that can't be written leaves the reservation counting
    (expire_stale_reservations() charges it later)."""
    if reservation.free or reservation.settled or not reservation.ledger_id:
        return Decimal("0")
    factory = conn_factory or _system_connection
    try:
        conn = factory()
    except Exception:  # noqa: BLE001
        logger.critical("could not open a connection to settle ledger %s; it stays reserved", reservation.ledger_id)
        return None
    try:
        prices = schedule(conn, reservation.budget_kind, reservation.provider, reservation.operation)
        pol = policy(conn)
        credit_value = Decimal(str(pol["credit_usd_value"]))
        charged_on_failure = any(p["charged_on_failure"] for p in prices.values()) if prices else True
        final = all(p["final"] for p in prices.values()) if prices else False

        if not reached_provider or (failed and not charged_on_failure):
            status, cost, consumed = "released", Decimal("0"), Decimal("0")
        elif measured_units is None:
            # Billed but not reported (or a failure the provider still bills):
            # charge the estimate and reconcile later.
            status, cost, consumed = "pending_reconciliation", reservation.estimated_cost_usd, reservation.reserved_credits
        else:
            cost = _cost(prices, measured_units, reservation.budget_kind, reservation.provider, reservation.operation)
            consumed = _to_credits(cost, credit_value)
            status = ("failed_charged" if failed else "consumed") if final else "pending_reconciliation"
            if not final:
                consumed = _to_credits(cost * (Decimal("1") + Decimal(str(pol["default_safety_margin"]))), credit_value)
        with conn.cursor() as cursor:
            _lock(cursor, "keel_credits", reservation.tenant_id, reservation.budget_kind)
            cursor.execute(
                """
                UPDATE usage_ledger SET status = %s, measured_units = %s::jsonb, actual_cost_usd = %s,
                       consumed_credits = %s, provider_request_id = %s, error_code = %s, settled_at = NOW()
                WHERE ledger_id = %s AND status = 'reserved' RETURNING ledger_id;
                """,
                (status, _json(measured_units) if measured_units is not None else None,
                 None if status == "pending_reconciliation" and measured_units is None else cost,
                 consumed, (provider_request_id or None) and str(provider_request_id)[:200],
                 (error_code or None) and str(error_code)[:80], reservation.ledger_id),
            )
            if cursor.fetchone() is None:  # already settled (a retry of settle): never double-count
                conn.rollback()
                reservation.settled = True
                return Decimal("0")
            cursor.execute(
                """
                UPDATE tenant_credit_balances
                SET reserved_credits = GREATEST(0, reserved_credits - %s), consumed_credits = consumed_credits + %s,
                    consumed_cost_usd = consumed_cost_usd + %s, updated_at = NOW()
                WHERE tenant_id = %s AND budget_kind = %s AND period_start = %s;
                """,
                (reservation.reserved_credits, consumed, cost, reservation.tenant_id, reservation.budget_kind,
                 reservation.period_start),
            )
        conn.commit()
        reservation.settled = True
        ctx = current()
        if ctx is not None:
            ctx.spent_credits[reservation.budget_kind] = ctx.spent_credits.get(reservation.budget_kind, Decimal("0")) + consumed
        return consumed
    except Exception:  # noqa: BLE001
        conn.rollback()
        logger.critical("settling ledger %s failed; it stays reserved", reservation.ledger_id, exc_info=True)
        return None
    finally:
        conn.close()


class ProviderCall:
    """Handle inside provider_call(): say what the provider billed.

    measured(units)     the provider reported its usage: charge exactly that.
    billed_unreported() the provider billed but didn't report usage: charge
                        the estimate and reconcile later.
    sent()              the request left this server; if the block then
                        fails, the call is charged when the provider bills
                        failed requests.
    (none of these)     nothing was billed (e.g. an error response the
                        provider doesn't charge for): the reservation is
                        released."""

    def __init__(self, reservation: Reservation):
        self.reservation = reservation
        self.units: Optional[Dict[str, float]] = None
        self.request_id: Optional[str] = None
        self.reached_provider = False
        self.billed_without_usage = False

    def sent(self) -> None:
        self.reached_provider = True

    def measured(self, units: Dict[str, float], provider_request_id: Optional[str] = None) -> None:
        self.reached_provider = True
        self.units = {k: v for k, v in units.items() if v}
        self.request_id = provider_request_id

    def billed_unreported(self, provider_request_id: Optional[str] = None) -> None:
        self.reached_provider = True
        self.billed_without_usage = True
        self.request_id = provider_request_id


@contextmanager
def provider_call(budget_kind: str, provider: str, operation: str, estimated_units: Dict[str, float], *,
                  idempotency_key: Optional[str] = None):
    """reserve -> the block (the provider call) -> settle, per ProviderCall."""
    reservation = reserve(budget_kind, provider, operation, estimated_units, idempotency_key=idempotency_key)
    call = ProviderCall(reservation)
    try:
        yield call
    except BaseException as exc:
        if not reservation.free:
            settle(reservation, call.units, failed=True, reached_provider=call.reached_provider,
                   provider_request_id=call.request_id, error_code=type(exc).__name__)
        raise
    else:
        if not reservation.free:
            if call.units is not None:
                settle(reservation, call.units, provider_request_id=call.request_id)
            elif call.billed_without_usage:
                settle(reservation, None, provider_request_id=call.request_id)
            else:
                settle(reservation, None, reached_provider=False, error_code="not_billed")


# --- Maintenance and reporting -----------------------------------------------

def expire_stale_reservations(conn, now: Optional[datetime] = None) -> int:
    """Reservations older than the policy's timeout (their process died):
    charged at their estimate and left for reconciliation. Caller commits."""
    pol = policy(conn)
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=pol["reservation_timeout_seconds"])
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT ledger_id, tenant_id, budget_kind, period_start, reserved_credits, estimated_cost_usd "
            "FROM usage_ledger WHERE status = 'reserved' AND created_at < %s FOR UPDATE SKIP LOCKED;",
            (cutoff,),
        )
        rows = cursor.fetchall()
        for ledger_id, tenant_id, kind, period_start, reserved, estimate in rows:
            cursor.execute(
                "UPDATE usage_ledger SET status = 'pending_reconciliation', consumed_credits = %s, error_code = 'expired', "
                "settled_at = %s WHERE ledger_id = %s;",
                (reserved, now, ledger_id),
            )
            cursor.execute(
                """
                UPDATE tenant_credit_balances
                SET reserved_credits = GREATEST(0, reserved_credits - %s), consumed_credits = consumed_credits + %s,
                    consumed_cost_usd = consumed_cost_usd + %s, updated_at = NOW()
                WHERE tenant_id = %s AND budget_kind = %s AND period_start = %s;
                """,
                (reserved, reserved, estimate, tenant_id, kind, period_start),
            )
    return len(rows)


def reconcile(conn, ledger_id: str, actual_cost_usd: Decimal, *, reference: str, actor: str,
              reason: str = "provider-reported usage") -> Decimal:
    """Records the provider's final cost for a pending row: the difference
    becomes an append-only adjustment (a refund of over-reservation, or the
    extra cost). Idempotent per reference. Returns the credit delta. Caller
    commits."""
    pol = policy(conn)
    credit_value = Decimal(str(pol["credit_usd_value"]))
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT tenant_id, budget_kind, period_start, consumed_credits, status FROM usage_ledger "
            "WHERE ledger_id = %s FOR UPDATE;",
            (ledger_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("unknown ledger row")
        tenant_id, kind, period_start, consumed, status = row
        if status != "pending_reconciliation":
            return Decimal("0")
        actual_credits = _to_credits(Decimal(str(actual_cost_usd)), credit_value)
        delta = actual_credits - Decimal(consumed or 0)
        cursor.execute(
            """
            INSERT INTO usage_ledger_adjustments
                (tenant_id, ledger_id, budget_kind, period_start, credits_delta, cost_delta_usd, kind, reference, reason, actor)
            VALUES (%s, %s, %s, %s, %s, %s, 'reconciliation', %s, %s, %s)
            ON CONFLICT (tenant_id, reference) DO NOTHING RETURNING adjustment_id;
            """,
            (tenant_id, ledger_id, kind, period_start, delta, Decimal(str(actual_cost_usd)), reference, reason, actor),
        )
        if cursor.fetchone() is None:
            return Decimal("0")
        cursor.execute(
            "UPDATE usage_ledger SET status = 'reconciled', reconciled_at = NOW(), actual_cost_usd = %s WHERE ledger_id = %s;",
            (Decimal(str(actual_cost_usd)), ledger_id),
        )
        cursor.execute(
            """
            UPDATE tenant_credit_balances SET consumed_credits = GREATEST(0, consumed_credits + %s), updated_at = NOW()
            WHERE tenant_id = %s AND budget_kind = %s AND period_start = %s;
            """,
            (delta, tenant_id, kind, period_start),
        )
    return delta


def summary(conn, tenant_id: str) -> dict:
    """The Billing page's view of both budgets for the current period."""
    pol = policy(conn)
    out = {}
    for kind in (DATA, AI):
        budget = _budget(conn, tenant_id, kind)
        bal = balance(conn, tenant_id, kind, budget["period_start"])
        used = bal["consumed"] + bal["reserved"]
        limit = budget["limit"]
        percent = None if not limit else float(min(Decimal("100"), used / limit * 100))
        reached = [t for t in pol["warning_thresholds"] if percent is not None and percent >= t]
        out[kind] = {
            "limit": None if limit is None else float(limit),
            "consumed": float(bal["consumed"]), "reserved": float(bal["reserved"]),
            "remaining": None if limit is None else float(max(Decimal("0"), limit - used)),
            "percent_used": percent, "warning": max(reached) if reached else None,
            "exhausted": limit is not None and used >= limit,
            "period_start": budget["period_start"].isoformat(), "period_end": budget["period_end"].isoformat(),
            "resets_on": (budget["period_end"] + timedelta(days=1)).isoformat(),
        }
    out["warning_thresholds"] = list(pol["warning_thresholds"])
    out["top_ups_enabled"] = bool(pol["top_ups_enabled"])
    return out


def history(conn, tenant_id: str, limit: int = 50) -> list:
    """Recent metered operations for the Billing page: credits and status
    only - never provider prices, keys or raw responses."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT budget_kind, operation_type, usage_class, status, COALESCE(consumed_credits, reserved_credits),
                   created_at, operation_id
            FROM usage_ledger WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s;
            """,
            (tenant_id, limit),
        )
        rows = cursor.fetchall()
    return [{"budget": kind, "operation": op, "usage_class": cls, "status": status, "credits": float(credits),
             "at": at.isoformat(), "operation_id": str(op_id)}
            for kind, op, cls, status, credits, at, op_id in rows]
