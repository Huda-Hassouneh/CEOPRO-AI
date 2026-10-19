"""
Keeps every company's demand forecasts current, without a separate worker.

Before this, forecasts were only written by a Redis-stream consumer
(consumer.py) that nothing published to and no deployment ran, so a real
company with months of sales saw "0 products forecasted" on Demand
Prediction. Now:

- products_needing_forecast() lists products that have sales but no
  forecast newer than both STALE_AFTER and their latest sale;
- start_refresh() forecasts those products in a background thread of the
  API process, one product per transaction, guarded by a per-company lock
  (Redis when available, so several API workers never duplicate the work);
- refresh_status() reports progress so the page can show "Updating
  forecasts: 12 of 28" and then reload.

It is triggered by the Demand Prediction page when forecasts are stale, after
sales imports and recorded sales, and by the "Refresh forecasts" button.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from src.ai import db
from src.ai.core import tenant_cache
from src.ai.forecasting.pipeline import DEFAULT_HORIZON_DAYS, run_forecast

logger = logging.getLogger("CEOPRO_AI_FORECAST_REFRESH")

STALE_AFTER_HOURS = float(os.getenv("FORECAST_STALE_AFTER_HOURS", "12"))
LOCK_TTL_SECONDS = int(os.getenv("FORECAST_REFRESH_LOCK_SECONDS", "1800"))
MAX_PRODUCTS_PER_RUN = int(os.getenv("FORECAST_REFRESH_MAX_PRODUCTS", "2000"))


def auto_refresh_enabled() -> bool:
    """Automatic refreshes after new sales and on page visits. On unless
    FORECAST_AUTO_REFRESH=0 (the test suite turns it off so no background
    threads outlive a test); the explicit refresh endpoint always works."""
    return os.getenv("FORECAST_AUTO_REFRESH", "1").strip().lower() not in ("0", "false", "no", "off")

_local_lock = threading.Lock()
_local_running: dict = {}
_local_status: dict = {}


def products_needing_forecast(conn, tenant_id: str, stale_after_hours: float = STALE_AFTER_HOURS) -> List[str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH sold AS (
                SELECT ii.product_id, MAX(i.created_at) AS last_recorded
                FROM invoice_items ii
                JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
                WHERE ii.tenant_id = %(tenant)s
                GROUP BY ii.product_id
            ), latest AS (
                SELECT product_id, MAX(created_at) AS forecast_at
                FROM demand_forecasts WHERE tenant_id = %(tenant)s
                GROUP BY product_id
            )
            SELECT p.product_id
            FROM products p
            JOIN sold s ON s.product_id = p.product_id
            LEFT JOIN latest l ON l.product_id = p.product_id
            WHERE p.tenant_id = %(tenant)s AND p.deleted_at IS NULL
              AND (l.forecast_at IS NULL
                   OR l.forecast_at < now() - make_interval(secs => %(stale)s)
                   OR l.forecast_at < s.last_recorded)
            ORDER BY l.forecast_at NULLS FIRST, p.product_id
            LIMIT %(limit)s;
            """,
            {"tenant": tenant_id, "stale": stale_after_hours * 3600, "limit": MAX_PRODUCTS_PER_RUN},
        )
        return [str(row[0]) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Lock + progress (Redis when reachable, in-process otherwise)
# ---------------------------------------------------------------------------

def _redis():
    try:
        from src.ai.core.redis_client import get_redis_client

        client = get_redis_client()
        client.ping()
        return client
    except Exception:
        return None


def _lock_key(tenant_id: str) -> str:
    return f"apex:forecast-refresh:lock:{tenant_id}"


def _status_key(tenant_id: str) -> str:
    return f"apex:forecast-refresh:status:{tenant_id}"


def _acquire(tenant_id: str) -> bool:
    client = _redis()
    if client is not None:
        try:
            return bool(client.set(_lock_key(tenant_id), "1", nx=True, ex=LOCK_TTL_SECONDS))
        except Exception:
            pass
    with _local_lock:
        if _local_running.get(tenant_id):
            return False
        _local_running[tenant_id] = True
        return True


def _lock_held(tenant_id: str) -> bool:
    client = _redis()
    if client is not None:
        try:
            return bool(client.exists(_lock_key(tenant_id)))
        except Exception:
            pass
    with _local_lock:
        return bool(_local_running.get(tenant_id))


def _release(tenant_id: str) -> None:
    client = _redis()
    if client is not None:
        try:
            client.delete(_lock_key(tenant_id))
        except Exception:
            pass
    with _local_lock:
        _local_running.pop(tenant_id, None)


def _write_status(tenant_id: str, **fields) -> None:
    fields = {k: ("" if v is None else str(v)) for k, v in fields.items()}
    client = _redis()
    if client is not None:
        try:
            client.hset(_status_key(tenant_id), mapping=fields)
            client.expire(_status_key(tenant_id), 7 * 24 * 3600)
        except Exception:
            pass
    with _local_lock:
        _local_status.setdefault(tenant_id, {}).update(fields)


def refresh_status(tenant_id: str) -> dict:
    raw = None
    client = _redis()
    if client is not None:
        try:
            raw = client.hgetall(_status_key(tenant_id)) or None
            if raw:
                raw = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}
        except Exception:
            raw = None
    if raw is None:
        with _local_lock:
            raw = dict(_local_status.get(tenant_id, {}))

    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    state = raw.get("state") or "idle"
    if state == "running" and not _lock_held(tenant_id):
        state = "interrupted"  # the process running it stopped; the next page load restarts it
    return {
        "state": state,
        "done": _int(raw.get("done")),
        "total": _int(raw.get("total")),
        "failed": _int(raw.get("failed")),
        "started_at": raw.get("started_at") or None,
        "finished_at": raw.get("finished_at") or None,
    }


# ---------------------------------------------------------------------------
# Running a refresh
# ---------------------------------------------------------------------------

def refresh_tenant_forecasts(tenant_id: str, user_id: str, product_ids: Optional[List[str]] = None) -> dict:
    """Forecasts the given products (default: every product that needs it).
    Each product is its own transaction, so one failure never loses the
    others. The caller must already hold the lock."""
    conn = db.dedicated_tenant_connection(tenant_id, user_id)
    done = failed = 0
    try:
        if product_ids is None:
            product_ids = products_needing_forecast(conn, tenant_id)
        total = len(product_ids)
        _write_status(tenant_id, state="running", done=0, failed=0, total=total,
                      started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)
        for product_id in product_ids:
            try:
                run_forecast(conn, tenant_id, product_id, DEFAULT_HORIZON_DAYS)
                done += 1
            except Exception:
                conn.rollback()
                failed += 1
                logger.exception("Forecast failed tenant=%s product=%s", tenant_id, product_id)
            _write_status(tenant_id, done=done, failed=failed)
        _write_status(tenant_id, state="finished", done=done, failed=failed, total=total,
                      finished_at=datetime.now(timezone.utc).isoformat())
        if done:
            try:
                from src.ai.rag.structured_summaries import regenerate_all_structured_summaries

                regenerate_all_structured_summaries(conn, db.minio_client(), tenant_id)
            except Exception as err:  # the assistant's summaries are a bonus, never a blocker
                logger.warning("Structured summaries not regenerated after forecasts (tenant=%s): %s", tenant_id, err)
        return {"done": done, "failed": failed, "total": total}
    finally:
        conn.close()


def start_refresh(tenant_id: str, user_id: str, product_ids: Optional[List[str]] = None) -> bool:
    """Starts a background refresh unless one is already running for this
    company. Returns True when a new refresh was started."""
    if not _acquire(tenant_id):
        return False
    _write_status(tenant_id, state="running", done=0, failed=0, total=len(product_ids) if product_ids else None,
                  started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)

    def _run():
        started = time.monotonic()
        try:
            result = refresh_tenant_forecasts(tenant_id, user_id, product_ids)
            logger.info("Forecast refresh tenant=%s: %s in %.1fs", tenant_id, result, time.monotonic() - started)
        except Exception:
            logger.exception("Forecast refresh failed tenant=%s", tenant_id)
            _write_status(tenant_id, state="failed", finished_at=datetime.now(timezone.utc).isoformat())
        finally:
            _release(tenant_id)
            tenant_cache.bump(tenant_id)  # screens show the new forecasts

    threading.Thread(target=_run, name=f"forecast-refresh-{tenant_id}", daemon=True).start()
    return True


def is_running(tenant_id: str) -> bool:
    return refresh_status(tenant_id)["state"] == "running"
