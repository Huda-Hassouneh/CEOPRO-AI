"""
KEEL - subscription usage: per-company plan allowances.

Kept deliberately apart from technical safety limits (upload size caps,
unpacked-size checks, the 20 MB-per-document assistant limit): those protect
the service and are the same for everyone; these are a commercial decision
per company (migration 20261007000000_add_usage_plans).

Model and vocabulary follow the reference project's billing backend (same tenant_id,
feature codes, aggregation types, reset cycles, statuses and 402 body), so
the local store below can be swapped for that system without touching
callers:
- 'sum' features (rag_assistant, web_searches, marketing_image_generation)
  are metered per billing period in tenant_usage_counters;
- 'max' features (tracked_products, tracked_competitors,
  document_storage_mb) are counted live from the data itself;
- NULL limit = unlimited; only 'active' and 'trialing' grant access.

Metered work is reserved ATOMICALLY before it starts (one conditional
upsert - two concurrent requests can't both take the last unit) and released
if the work fails, so a question the language model never answered (provider
error or rate limit) never uses the company's allowance.

Separately, ensure_ai_rate() caps each company's assistant requests per
minute: a fairness guard so one company can't consume the shared AI
provider's per-minute capacity for everyone - not a plan allowance.
"""
import calendar
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from src.ai.core.redis_client import get_redis_client

logger = logging.getLogger("CEOPRO_AI_USAGE")

DEFAULT_PLAN_KEY = os.getenv("DEFAULT_PLAN_KEY", "growth")
# A company with no plan assignment (its trial was refused, or never
# started) has no access: "none". "default" grants DEFAULT_PLAN_KEY instead,
# for local development and single-company installs only.
UNASSIGNED_ACCESS_DEFAULT = "none"
AI_REQUESTS_PER_MINUTE = int(os.getenv("AI_REQUESTS_PER_MINUTE_PER_COMPANY", "8"))
ACCESS_GRANTING_STATUSES = ("active", "trialing")

RAG_ASSISTANT = "rag_assistant"
WEB_SEARCHES = "web_searches"
IMAGE_GENERATION = "marketing_image_generation"
TRACKED_PRODUCTS = "tracked_products"
TRACKED_COMPETITORS = "tracked_competitors"
DOCUMENT_STORAGE_MB = "document_storage_mb"
DOCUMENT_EXTRACTION = "document_extraction"   # KB processed per billing period
SENTIMENT_ANALYSIS = "sentiment_analysis"     # records analysed per billing period
CONNECTED_DATA_SOURCES = "connected_data_sources"
MONTHLY_REPORTS = "monthly_reports"           # report exports per billing period
TEAM_SEATS = "team_seats"                     # active members of the company
DATA_CREDITS = "data_credits"                 # billing/credits.py meters these two
AI_CREDITS = "ai_credits"
CREDIT_FEATURES = (DATA_CREDITS, AI_CREDITS)

# Included modules (usage_plan_entitlements), as in the plan catalog.
MARKET_INTELLIGENCE = "market_intelligence"
DEMAND_PREDICTION = "demand_prediction"
COMPETITOR_MANAGEMENT = "competitor_management"

# The assistant allowance is counted in tokens (as in the plan catalog). This
# much is reserved before a question is answered, then settled to the real
# token count; ~1,600-1,900 tokens were measured per answer against Groq.
RAG_TOKEN_RESERVATION = int(os.getenv("RAG_TOKEN_RESERVATION", "2500"))

_LIVE_COUNTS = {
    TRACKED_PRODUCTS: "SELECT COUNT(*) FROM products WHERE tenant_id = %s AND deleted_at IS NULL;",
    TRACKED_COMPETITORS: "SELECT COUNT(*) FROM tenant_competitors WHERE tenant_id = %s AND is_tracked = TRUE;",
    # Assistant documents plus every other stored file (core/storage_ledger.py).
    DOCUMENT_STORAGE_MB: ("SELECT ((SELECT COALESCE(SUM(file_size_bytes), 0) FROM rag_documents_metadata WHERE tenant_id = %(t)s) "
                          "+ (SELECT COALESCE(SUM(size_bytes), 0) FROM tenant_storage_objects WHERE tenant_id = %(t)s)) / 1048576.0;"),
    CONNECTED_DATA_SOURCES: ("SELECT COUNT(*) FROM data_sources WHERE tenant_id = %s AND is_active = TRUE "
                             "AND source_type = 'OWN_SYSTEM_CONNECTOR';"),
    # Seats: members who haven't been removed (invitations still open are
    # added when inviting - see settings.invite_team_member).
    TEAM_SEATS: "SELECT COUNT(*) FROM tenant_users WHERE tenant_id = %s AND removed_at IS NULL;",
}

_MESSAGES = {
    RAG_ASSISTANT: "Your plan's assistant allowance for this billing period has been used.",
    DOCUMENT_EXTRACTION: "Your plan's document processing allowance for this billing period has been used.",
    SENTIMENT_ANALYSIS: "Your plan's review analysis allowance for this billing period has been used.",
    CONNECTED_DATA_SOURCES: "Your plan's limit of connected data sources has been reached.",
    MARKET_INTELLIGENCE: "Market intelligence isn't included in your plan.",
    DEMAND_PREDICTION: "Demand forecasting isn't included in your plan.",
    COMPETITOR_MANAGEMENT: "Competitor tracking isn't included in your plan.",
    WEB_SEARCHES: "Your plan's web searches for this billing period have been used.",
    IMAGE_GENERATION: "Your plan's image generations for this billing period have been used.",
    TRACKED_PRODUCTS: "Your plan's product limit has been reached.",
    MONTHLY_REPORTS: "Your plan's reports for this billing period have been used.",
    TEAM_SEATS: "Your plan's team seats are all in use. Remove a member or upgrade your plan to add more.",
    TRACKED_COMPETITORS: "Your plan's limit of tracked competitors has been reached.",
    DOCUMENT_STORAGE_MB: "Your plan's document storage is full.",
}


class PlanLimitReached(Exception):
    """402: the company's plan doesn't allow this right now."""

    def __init__(self, reason: str, feature_code: str, current_usage=None, limit=None,
                 reset_cycle: Optional[str] = None, period_end: Optional[date] = None):
        super().__init__(f"{reason}: {feature_code}")
        self.reason, self.feature_code = reason, feature_code
        self.current_usage, self.limit, self.reset_cycle, self.period_end = current_usage, limit, reset_cycle, period_end

    def as_http(self) -> HTTPException:
        if self.reason == "SUBSCRIPTION_INACTIVE":
            message = "Your subscription isn't active. Update your plan in Billing to continue."
        else:
            message = _MESSAGES.get(self.feature_code, "Your plan's limit for this has been reached.")
            if self.reset_cycle == "billing_period" and self.period_end:
                message += f" It renews on {(self.period_end + timedelta(days=1)).isoformat()}."
            message += " You can upgrade your plan in Billing."
        remaining = None if self.limit is None or self.current_usage is None else max(0, self.limit - self.current_usage)
        return HTTPException(status_code=402, detail={
            "reason": self.reason, "feature_code": self.feature_code,
            "current_usage": self.current_usage, "limit": self.limit, "remaining": remaining,
            "reset_cycle": self.reset_cycle,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "message": message,
        })


def _month_bounds(today: date):
    return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])


def _unassigned_access() -> str:
    return os.getenv("UNASSIGNED_PLAN_ACCESS", UNASSIGNED_ACCESS_DEFAULT)


def get_plan(conn, tenant_id: str, today: Optional[date] = None, now: Optional[datetime] = None) -> dict:
    """The company's plan, status, current period and per-feature limits.
    Limits are the plan's, replaced by an approved contract override
    (tenant_entitlement_overrides), or the plan's trial allowance while the
    company is on a free trial. A free trial ends at its exact UTC time."""
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.plan_key, a.status, a.current_period_start, a.current_period_end, a.source, a.period_code,
                   t.ends_at
            FROM tenant_plan_assignments a LEFT JOIN billing_trials t ON t.tenant_id = a.tenant_id
            WHERE a.tenant_id = %s;
            """,
            (tenant_id,),
        )
        row = cursor.fetchone()
        if row:
            plan_key, status, period_start, period_end, source, period_code, trial_ends_at = row
        elif _unassigned_access() == "default":
            plan_key, status, period_start, period_end, source, period_code, trial_ends_at = (
                DEFAULT_PLAN_KEY, "active", None, None, None, "monthly", None)
        else:
            plan_key, status, period_start, period_end, source, period_code, trial_ends_at = (
                DEFAULT_PLAN_KEY, "none", None, None, None, "monthly", None)
        # A free trial ends at its exact end time unless a paid subscription took over.
        trial_over = (trial_ends_at <= now) if trial_ends_at is not None else bool(period_end and period_end < today)
        if status == "trialing" and ((source == "trial" and trial_over)
                                     or (source == "contract" and period_end and period_end < today)):
            status = "expired"
        cursor.execute(
            """
            SELECT p.display_name, f.feature_code, f.unit, f.aggregation_type, f.reset_cycle, l.limit_value,
                   l.trial_limit_value, o.limit_value
            FROM usage_plans p
            JOIN usage_plan_limits l ON l.plan_key = p.plan_key
            JOIN usage_features f ON f.feature_code = l.feature_code
            LEFT JOIN tenant_entitlement_overrides o ON o.tenant_id = %s AND o.feature_code = l.feature_code
            WHERE p.plan_key = %s;
            """,
            (tenant_id, plan_key),
        )
        rows = cursor.fetchall()
        cursor.execute("SELECT feature_code FROM usage_plan_entitlements WHERE plan_key = %s;", (plan_key,))
        entitlements = sorted(r[0] for r in cursor.fetchall())
    if not (period_start and period_end and period_start <= today <= period_end):
        period_start, period_end = _month_bounds(today)
    trialing = status == "trialing"
    features = {}
    for _name, code, unit, agg, cycle, limit, trial_limit, override in rows:
        if override is not None:
            limit = override
        elif trialing and trial_limit is not None:
            limit = trial_limit
        features[code] = {"unit": unit, "aggregation_type": agg, "reset_cycle": cycle,
                          "limit": None if limit is None else int(limit)}
    return {
        "plan_key": plan_key, "display_name": rows[0][0] if rows else plan_key, "status": status,
        "assigned": row is not None, "period_start": period_start, "period_end": period_end, "features": features,
        "source": source, "period_code": period_code or "monthly", "entitlements": entitlements,
        "trial_ends_at": trial_ends_at,
    }


def _metered_used(conn, tenant_id: str, feature_code: str, period_start: date) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT used FROM tenant_usage_counters WHERE tenant_id = %s AND feature_code = %s AND period_start = %s;",
            (tenant_id, feature_code, period_start),
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def _credits_used(conn, tenant_id: str, feature_code: str, period_start: date) -> float:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT consumed_credits + reserved_credits FROM tenant_credit_balances "
            "WHERE tenant_id = %s AND budget_kind = %s AND period_start = %s;",
            (tenant_id, "data" if feature_code == DATA_CREDITS else "ai", period_start),
        )
        row = cursor.fetchone()
    return round(float(row[0]), 2) if row else 0.0


def lock_feature(conn, tenant_id: str, feature_code: str) -> None:
    """Serialises check-then-create for one company and feature until the
    caller's transaction ends, so concurrent requests can't both take the
    last unit of a counted ('max') limit."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));", (f"keel_capacity:{tenant_id}:{feature_code}",))


def _live_used(conn, tenant_id: str, feature_code: str) -> float:
    with conn.cursor() as cursor:
        query = _LIVE_COUNTS[feature_code]
        cursor.execute(query, {"t": tenant_id} if "%(t)s" in query else (tenant_id,))
        value = cursor.fetchone()[0]
    return round(float(value), 2) if feature_code == DOCUMENT_STORAGE_MB else int(value)


def current_usage(conn, tenant_id: str, plan: Optional[dict] = None) -> list:
    """Per feature: limit, current usage, remaining - the shape of the reference
    project's GET /subscriptions/current/usage."""
    plan = plan or get_plan(conn, tenant_id)
    out = []
    for code, feature in sorted(plan["features"].items()):
        if code in CREDIT_FEATURES:
            used = _credits_used(conn, tenant_id, code, plan["period_start"])
        elif feature["aggregation_type"] == "sum":
            used = _metered_used(conn, tenant_id, code, plan["period_start"])
        else:
            used = _live_used(conn, tenant_id, code)
        limit = feature["limit"]
        out.append({
            "feature_code": code, "unit": feature["unit"], "limit": limit, "current_usage": used,
            "remaining": None if limit is None else max(0, limit - used),
            "is_unlimited": limit is None, "is_exceeded": limit is not None and used >= limit,
            "aggregation_type": feature["aggregation_type"], "reset_cycle": feature["reset_cycle"],
        })
    return out


def require_entitlement(conn, tenant_id: str, feature_code: str) -> None:
    """Raises PlanLimitReached (NOT_INCLUDED) when the company's plan doesn't
    include this module, or SUBSCRIPTION_INACTIVE when it has no access."""
    plan = get_plan(conn, tenant_id)
    _require_active(plan, feature_code)
    if feature_code not in plan["entitlements"]:
        raise PlanLimitReached("NOT_INCLUDED", feature_code)


def remaining(conn, tenant_id: str, feature_code: str) -> Optional[int]:
    """What is left of a metered ('sum') allowance this period; None = unlimited.
    0 when the plan has no access."""
    plan = get_plan(conn, tenant_id)
    if plan["status"] not in ACCESS_GRANTING_STATUSES:
        return 0
    feature = plan["features"].get(feature_code)
    if not feature or feature["limit"] is None:
        return None
    return max(0, feature["limit"] - _metered_used(conn, tenant_id, feature_code, plan["period_start"]))


def record(conn, tenant_id: str, feature_code: str, amount: int) -> None:
    """Adds work already done to this period's metered usage (no limit check -
    the caller bounded the work with remaining() first). The caller commits."""
    if amount <= 0:
        return
    plan = get_plan(conn, tenant_id)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenant_usage_counters (tenant_id, feature_code, period_start, used, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, feature_code, period_start) DO UPDATE
                SET used = tenant_usage_counters.used + EXCLUDED.used, updated_at = NOW();
            """,
            (tenant_id, feature_code, plan["period_start"], int(amount)),
        )


def settle(conn, reservation: dict, actual: int) -> None:
    """Replaces a reservation's estimate with what was really used (may be more
    or less). The caller commits."""
    difference = int(actual) - reservation["amount"]
    if difference == 0:
        return
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE tenant_usage_counters SET used = GREATEST(0, used + %s), updated_at = NOW()
            WHERE tenant_id = %s AND feature_code = %s AND period_start = %s;
            """,
            (difference, reservation["tenant_id"], reservation["feature_code"], reservation["period_start"]),
        )
    reservation["amount"] = int(actual)


# Features introduced with KEEL's credit plans are never unlimited by
# omission: a plan without a row for them doesn't include them.
_FAIL_CLOSED_FEATURES = (MONTHLY_REPORTS, TEAM_SEATS, DATA_CREDITS, AI_CREDITS)


def _missing_limit(feature_code: str) -> Optional[int]:
    return 0 if feature_code in _FAIL_CLOSED_FEATURES else None


def _require_active(plan: dict, feature_code: str) -> None:
    if plan["status"] not in ACCESS_GRANTING_STATUSES:
        raise PlanLimitReached("SUBSCRIPTION_INACTIVE", feature_code)


def reserve(conn, tenant_id: str, feature_code: str, amount: int = 1) -> dict:
    """Atomically takes `amount` of a metered ('sum') allowance for the
    current period, or raises PlanLimitReached (QUOTA_EXHAUSTED). The caller
    commits the reservation before doing the work, and calls release() if
    the work then fails. Returns the reservation for release()."""
    plan = get_plan(conn, tenant_id)
    _require_active(plan, feature_code)
    feature = plan["features"].get(feature_code)
    limit = feature["limit"] if feature else _missing_limit(feature_code)
    period_start = plan["period_start"]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenant_usage_counters (tenant_id, feature_code, period_start, used, updated_at)
            SELECT %(tenant)s, %(code)s, %(period)s, %(amount)s, NOW()
            WHERE %(limit)s::BIGINT IS NULL OR %(amount)s <= %(limit)s::BIGINT
            ON CONFLICT (tenant_id, feature_code, period_start) DO UPDATE
                SET used = tenant_usage_counters.used + EXCLUDED.used, updated_at = NOW()
                WHERE %(limit)s::BIGINT IS NULL OR tenant_usage_counters.used + EXCLUDED.used <= %(limit)s::BIGINT
            RETURNING used;
            """,
            {"tenant": tenant_id, "code": feature_code, "period": period_start, "amount": int(amount), "limit": limit},
        )
        taken = cursor.fetchone()
    if taken is None:
        raise PlanLimitReached("QUOTA_EXHAUSTED", feature_code, _metered_used(conn, tenant_id, feature_code, period_start),
                               limit, "billing_period", plan["period_end"])
    return {"tenant_id": tenant_id, "feature_code": feature_code, "period_start": period_start, "amount": int(amount)}


def reserve_request(tenant_id: str, feature_code: str, idempotency_key: str,
                    actor_user_id: Optional[str] = None, conn_factory=None) -> Optional[dict]:
    """Counts one request (e.g. a report export) against a metered allowance,
    once per idempotency key per period: a retried or replayed request with
    the same key is not counted again (returns None). Raises PlanLimitReached
    when the allowance is used up. Runs on the billing service's own
    connection - companies can read these counters but never write them.
    Fails closed: no accounting connection, no request."""
    from src.ai import db

    conn = (conn_factory or db.system_connection)()
    try:
        plan = get_plan(conn, tenant_id)
        with conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));",
                           (f"keel_metered:{tenant_id}:{feature_code}",))
            cursor.execute(
                "SELECT 1 FROM metered_request_keys WHERE tenant_id = %s AND feature_code = %s AND idempotency_key = %s;",
                (tenant_id, feature_code, idempotency_key),
            )
            if cursor.fetchone():
                conn.rollback()
                return None
        reservation = reserve(conn, tenant_id, feature_code, 1)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO metered_request_keys (tenant_id, feature_code, idempotency_key, period_start, actor_user_id)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (tenant_id, feature_code, idempotency_key, plan["period_start"], actor_user_id),
            )
        conn.commit()
        reservation["idempotency_key"] = idempotency_key
        return reservation
    except PlanLimitReached:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_request(reservation: Optional[dict], conn_factory=None) -> None:
    """Gives back a counted request whose work failed (its key is freed, so a
    retry is counted once)."""
    if not reservation:
        return
    from src.ai import db

    conn = (conn_factory or db.system_connection)()
    try:
        release(conn, reservation)
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM metered_request_keys WHERE tenant_id = %s AND feature_code = %s AND idempotency_key = %s;",
                (reservation["tenant_id"], reservation["feature_code"], reservation["idempotency_key"]),
            )
        conn.commit()
    except Exception:  # noqa: BLE001 - the unit stays counted; never fail the response over it
        conn.rollback()
        logger.exception("could not release counted request (%s)", reservation.get("feature_code"))
    finally:
        conn.close()


def release(conn, reservation: dict) -> None:
    """Gives back a reservation whose work didn't happen. The caller commits."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE tenant_usage_counters SET used = GREATEST(0, used - %s), updated_at = NOW()
            WHERE tenant_id = %s AND feature_code = %s AND period_start = %s;
            """,
            (reservation["amount"], reservation["tenant_id"], reservation["feature_code"], reservation["period_start"]),
        )


def capacity_left(conn, tenant_id: str, feature_code: str) -> Optional[float]:
    """For 'max' features counted live: how many more fit; None = unlimited,
    0 when the plan grants no access."""
    plan = get_plan(conn, tenant_id)
    if plan["status"] not in ACCESS_GRANTING_STATUSES:
        return 0
    feature = plan["features"].get(feature_code)
    if not feature or feature["limit"] is None:
        return None
    lock_feature(conn, tenant_id, feature_code)
    return max(0, feature["limit"] - _live_used(conn, tenant_id, feature_code))


def ensure_capacity(conn, tenant_id: str, feature_code: str, adding: float = 1) -> None:
    """For 'max' features counted live: raises PlanLimitReached
    (CAPACITY_REACHED) when adding `adding` would exceed the plan."""
    plan = get_plan(conn, tenant_id)
    _require_active(plan, feature_code)
    feature = plan["features"].get(feature_code)
    limit = feature["limit"] if feature else _missing_limit(feature_code)
    if limit is None:
        return
    lock_feature(conn, tenant_id, feature_code)
    used = _live_used(conn, tenant_id, feature_code)
    if used + adding > limit:
        raise PlanLimitReached("CAPACITY_REACHED", feature_code, used, limit, "lifetime", None)


# --- Fairness: per-company AI request rate --------------------------------

_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = get_redis_client(socket_connect_timeout=1, socket_timeout=1)
    return _redis_client


def ensure_ai_rate(tenant_id: str) -> None:
    """At most AI_REQUESTS_PER_MINUTE assistant requests per company per
    minute, so a burst from one company can't take the shared provider's
    per-minute capacity from everyone else. Fails open without Redis."""
    try:
        client = _redis()
        now = int(datetime.now(timezone.utc).timestamp())
        key = f"ai_rate:{tenant_id}:{now // 60}"
        count = client.incr(key)
        if count == 1:
            client.expire(key, 70)
        if count > AI_REQUESTS_PER_MINUTE:
            retry_after = 60 - now % 60
            raise HTTPException(
                status_code=429,
                detail=f"Too many assistant questions from your company in the last minute. Please try again in about {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("AI rate guard unavailable (%s); allowing the request", exc)
