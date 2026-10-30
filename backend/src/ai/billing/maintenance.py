"""
Billing upkeep in the API process: every few minutes, reservations whose
call never settled (the process died mid-call) are charged at their
estimate and marked for reconciliation (credits.expire_stale_reservations),
so a crash can neither leak credits nor make spending free.
BILLING_MAINTENANCE_ENABLED=false turns it off (tests).
"""
import logging
import os
import threading
import time

from src.ai.billing import credits

logger = logging.getLogger("KEEL_BILLING_MAINTENANCE")

CHECK_SECONDS = int(os.getenv("BILLING_MAINTENANCE_SECONDS", "300"))
_lock = threading.Lock()
_started = False


def run_once(system_connection=None) -> dict:
    from src.ai import db

    if system_connection is None and os.getenv("CREDIT_ACCOUNTING_DB_PASSWORD"):
        conn = db.credit_accounting_connection("00000000-0000-0000-0000-000000000000")
        try:
            with conn.cursor() as cur:
                timeout = credits.policy(conn)["reservation_timeout_seconds"]
                cur.execute("SELECT public.billing_expired_credit_tenants(%s)", (timeout,))
                tenants = [str(r[0]) for r in cur.fetchall()]
        finally:
            conn.close()
        expired = 0
        for tenant in tenants:
            expired += run_once(lambda: db.credit_accounting_connection(tenant))["expired_reservations"]
        return {"expired_reservations": expired}
    conn = (system_connection or db.system_connection)()
    try:
        expired = credits.expire_stale_reservations(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"expired_reservations": expired}


def _loop() -> None:
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            outcome = run_once()
            if outcome["expired_reservations"]:
                logger.warning("billing upkeep: %s", outcome)
        except Exception:  # noqa: BLE001 - database briefly unreachable; try next pass
            logger.exception("billing upkeep pass failed")


def start_background() -> bool:
    global _started
    if os.getenv("BILLING_MAINTENANCE_ENABLED", "true").lower() in ("0", "false", "no"):
        return False
    with _lock:
        if _started:
            return False
        threading.Thread(target=_loop, name="billing-upkeep", daemon=True).start()
        _started = True
    return True
