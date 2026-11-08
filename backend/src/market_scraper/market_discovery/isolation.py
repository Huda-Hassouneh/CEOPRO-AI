"""Runs a competitor discovery in its own low-priority process instead of an API thread.

Why: a discovery is seconds of CPU-bound Python (merging, scoring, reading websites). In an API
thread it holds the interpreter lock, and on a small host (Render free: 0.1 CPU) every request
then waits through throttled CPU periods for each hand-off - measured at 3 s per request and up
to 9.9 s during refreshes, past Render's 5 s health check, which restarts the API. A child
process has its own interpreter lock and runs at nice 19, so the kernel gives API threads the
CPU first. Measured cost: ~85 MiB for the child (torch and the other model libraries are never
imported), one run at a time (pipeline.MAX_CONCURRENT_RUNS).

    python -m src.market_scraper.market_discovery.isolation <tenant_id> <user_id|-> <run_id> <radius_km|->

The child connects with the same restricted tenant connection the thread used and receives only
ids on its command line (never credentials: it reads the same environment as the API).
DISCOVERY_RUN_ISOLATION=thread keeps the previous in-thread behaviour.
"""
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
BACKEND_DIR = Path(__file__).resolve().parents[3]
CHILD_TIMEOUT_SECONDS = int(os.getenv("DISCOVERY_CHILD_TIMEOUT_SECONDS", "1800"))


def mode() -> str:
    return "thread" if os.getenv("DISCOVERY_RUN_ISOLATION", "process").strip().lower() == "thread" else "process"


def _command(tenant_id: str, user_id: Optional[str], run_id: str, radius_km: Optional[float]) -> list:
    command = [sys.executable, "-m", "src.market_scraper.market_discovery.isolation",
               str(tenant_id), str(user_id or "-"), str(run_id), "-" if radius_km is None else repr(float(radius_km))]
    nice = shutil.which("nice")
    return [nice, "-n", "19", *command] if nice else command


def _close_if_unfinished(conn, run_id: str, error: str) -> None:
    """A child that died (out of memory, killed, crashed on start) cannot record its own end."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE discovery_runs SET status = 'failed', error = %s, finished_at = %s "
            "WHERE run_id = %s AND status IN ('queued', 'running');",
            (error, datetime.now(timezone.utc), run_id),
        )
    conn.commit()


def execute(conn, tenant_id: str, user_id: Optional[str], run_id: str, radius_km: Optional[float] = None,
            providers=None) -> int:
    """Run discovery `run_id` to completion; returns the child's exit code (0 in thread mode).
    `conn` is the caller's tenant connection, used only to close a run the child abandoned."""
    from src.market_scraper.market_discovery import pipeline

    if providers is not None or mode() == "thread":
        pipeline.execute_run(conn, tenant_id, run_id, radius_km, **({"providers": providers} if providers else {}))
        return 0
    # The parent holds the lease and the slot while the child works, so a run waiting for its turn
    # (or a child that is starting) is never mistaken for an abandoned one.
    with pipeline._RunLease(run_id):  # noqa: SLF001
        if not pipeline._RUN_SLOTS.acquire(timeout=pipeline.STALE_RUN_MINUTES * 60):  # noqa: SLF001
            _close_if_unfinished(conn, run_id, "timed_out")
            return 1
        try:
            child = subprocess.Popen(_command(tenant_id, user_id, run_id, radius_km), cwd=str(BACKEND_DIR),
                                     env=dict(os.environ, DISCOVERY_RUN_ISOLATION="thread"),
                                     stdin=subprocess.DEVNULL)
            try:
                code = child.wait(timeout=CHILD_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(10)
                code = -9
        finally:
            pipeline._RUN_SLOTS.release()  # noqa: SLF001
    if code != 0:
        logger.warning("discovery run %s child exited with %s", run_id, code)
        _close_if_unfinished(conn, run_id, "interrupted")
    return code


def _main(argv) -> int:
    tenant_id, user_id, run_id, radius = argv
    if not logging.getLogger().handlers:
        logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        os.nice(19)  # when `nice` was not available to start us at low priority
    except OSError:
        pass
    from src.ai import db
    from src.market_scraper.market_discovery import pipeline

    conn = db.dedicated_tenant_connection(tenant_id, None if user_id == "-" else user_id)
    try:
        pipeline.execute_run(conn, tenant_id, run_id, None if radius == "-" else float(radius))
        return 0
    except Exception:  # noqa: BLE001 - recorded on the run row by execute_run
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
