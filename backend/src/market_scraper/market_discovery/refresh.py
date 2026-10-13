"""
Keeps every company's competitor list current without anyone pressing Scan.

Each pass finds companies whose last finished discovery is older than
DISCOVERY_REFRESH_DAYS (default 7) and runs discovery again for a few of
them, oldest first. Only companies that have already run discovery once are
refreshed - a company that never asked for discovery is never scanned - and
a company with a run in progress is skipped (one active run per company is
enforced by pipeline.start_run, so several API replicas can't double up).

The loop runs as a daemon thread inside the API process (single-service
deployments have nowhere else to run it). DISCOVERY_REFRESH_ENABLED=false
turns it off, e.g. for test runs or a deployment that schedules
`python -m src.market_scraper.market_discovery.refresh` itself.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from src.ai.core import tenant_cache
from src.ai.core.usage import DEFAULT_PLAN_KEY

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
REFRESH_DAYS = float(os.getenv("DISCOVERY_REFRESH_DAYS", "7"))
CHECK_SECONDS = int(os.getenv("DISCOVERY_REFRESH_CHECK_SECONDS", "3600"))
BATCH = int(os.getenv("DISCOVERY_REFRESH_BATCH", "5"))
FIRST_DELAY_SECONDS = int(os.getenv("DISCOVERY_REFRESH_FIRST_DELAY_SECONDS", "120"))

_started = False
_lock = threading.Lock()


def due(system_conn, now: Optional[datetime] = None, days: float = REFRESH_DAYS, limit: int = BATCH) -> List[Tuple[str, Optional[str], Optional[float]]]:
    """(tenant_id, user_id, radius_km) for companies whose discovery is stale."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    with system_conn.cursor() as cursor:
        cursor.execute(
            """
            WITH last AS (
                SELECT DISTINCT ON (tenant_id) tenant_id, status, finished_at, requested_by, radius_km
                FROM discovery_runs ORDER BY tenant_id, created_at DESC
            )
            SELECT l.tenant_id, l.requested_by, l.radius_km
            FROM last l JOIN companies c ON c.tenant_id = l.tenant_id
            WHERE c.deleted_at IS NULL
              AND l.status IN ('completed', 'partial')
              AND l.finished_at < %s
              AND (c.latitude IS NOT NULL OR c.city IS NOT NULL)
              -- Only companies whose plan includes competitor tracking and
              -- grants access (a company that moved to Starter, or whose
              -- trial ended, isn't scanned at our cost).
              -- (No assignment row means the default plan, as in core/usage.py.)
              AND EXISTS (
                  SELECT 1 FROM usage_plan_entitlements e
                  LEFT JOIN tenant_plan_assignments a ON a.tenant_id = l.tenant_id
                  WHERE e.feature_code = 'competitor_management'
                    AND e.plan_key = COALESCE(a.plan_key, %s)
                    AND (a.tenant_id IS NULL OR (a.status IN ('active', 'trialing')
                         AND NOT (a.source = 'trial' AND a.current_period_end < CURRENT_DATE)))
              )
            ORDER BY l.finished_at
            LIMIT %s;
            """,
            (cutoff, DEFAULT_PLAN_KEY, limit),
        )
        return [(str(t), str(u) if u else None, float(r) if r is not None else None) for t, u, r in cursor.fetchall()]


def refresh_once(system_connection=None, tenant_connection=None, now: Optional[datetime] = None, providers=None) -> dict:
    """One pass. Connections and sources are injectable for tests."""
    from src.ai import db
    from src.market_scraper.market_discovery import pipeline

    system_connection = system_connection or db.system_connection
    tenant_connection = tenant_connection or db.dedicated_tenant_connection
    conn = system_connection()
    try:
        tenants = due(conn, now=now)
    finally:
        conn.close()
    result = {"due": len(tenants), "refreshed": 0, "busy": 0, "failed": 0}
    for tenant_id, user_id, radius_km in tenants:
        conn = tenant_connection(tenant_id, user_id)
        try:
            run_id = pipeline.start_run(conn, tenant_id, user_id, radius_km)
            conn.commit()
            pipeline.execute_run(conn, tenant_id, run_id, radius_km, providers=providers or pipeline.PROVIDERS)
            result["refreshed"] += 1
        except pipeline.DiscoveryBusy:
            conn.rollback()
            result["busy"] += 1
        except Exception:  # noqa: BLE001 - one company's failure never stops the others
            logger.exception("scheduled discovery refresh failed for a company")
            result["failed"] += 1
        finally:
            conn.close()
            tenant_cache.bump(tenant_id)  # this thread runs in the API process
    return result


def _loop() -> None:
    time.sleep(FIRST_DELAY_SECONDS)
    while True:
        try:
            outcome = refresh_once()
            if outcome["due"]:
                logger.info("scheduled discovery refresh: %s", outcome)
        except Exception:  # noqa: BLE001 - e.g. database briefly unreachable; try next pass
            logger.exception("scheduled discovery refresh pass failed")
        time.sleep(CHECK_SECONDS)


def start_background() -> bool:
    """Starts the refresh thread once per process, unless disabled."""
    global _started
    if os.getenv("DISCOVERY_REFRESH_ENABLED", "true").lower() in ("0", "false", "no"):
        return False
    with _lock:
        if _started:
            return False
        threading.Thread(target=_loop, name="discovery-refresh", daemon=True).start()
        _started = True
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    while True:
        logger.info("scheduled discovery refresh: %s", refresh_once())
        time.sleep(CHECK_SECONDS)
