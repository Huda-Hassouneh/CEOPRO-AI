"""
KEEL - background image worker.

    python -m src.ai.marketing.image_worker            # threads = number of image servers
    python -m src.ai.marketing.image_worker --threads 2
    python -m src.ai.marketing.image_worker --once     # one job, then exit (tests, cron)

Takes jobs from image_generation_jobs (marketing/image_jobs.py) and makes
each image with the same code the API uses (marketing/image_service.py):
the provider chain, storage, the gallery and the allowance rules. Run as
many workers on as many machines as you like; each job is claimed by one.

Failure handling:
- every image server busy: back in the queue in 30 s, no attempt used;
- a provider error, storage or database hiccup: retried with backoff
  (1, 4, 16 min ...) up to the job's max_attempts, then FAILED with the
  reason;
- the plan's allowance or storage used up, or the campaign gone: FAILED at
  once (retrying can't help);
- the worker itself dies: its RUNNING job stops sending heartbeats and is
  taken over by another worker after MARKETING_IMAGE_JOB_STALE_SECONDS.

By default a job only succeeds with a real AI image; with
MARKETING_IMAGE_WORKER_DESIGNED_FALLBACK=true a designed poster is stored
when no AI image can be made, like the interactive button.
"""
import argparse
import logging
import os
import signal
import socket
import threading
import time
from typing import Optional

from src.ai import db
from src.ai.billing import credits
from src.ai.core import storage_ledger, usage
from src.ai.marketing import data_access, image_generation, image_jobs, image_service

logger = logging.getLogger("CEOPRO_AI_IMAGE_WORKER")

# The background-worker service principal get_current_tenant() trusts for the
# one company a connection is scoped to (migration 20260928000000).
SERVICE_ACTOR = os.getenv("SCRAPER_ACTOR_USER_ID", "00000000-0000-0000-0000-000000000000")
POLL_SECONDS = float(os.getenv("MARKETING_IMAGE_WORKER_POLL_SECONDS", "5"))
HEARTBEAT_SECONDS = float(os.getenv("MARKETING_IMAGE_WORKER_HEARTBEAT_SECONDS", "30"))
BUSY_RETRY_SECONDS = float(os.getenv("MARKETING_IMAGE_WORKER_BUSY_RETRY_SECONDS", "30"))
DESIGNED_FALLBACK = os.getenv("MARKETING_IMAGE_WORKER_DESIGNED_FALLBACK", "false").strip().lower() in ("1", "true", "yes")

_stop = threading.Event()


def _keep_alive(job_id: str, worker_id: str, done: threading.Event, system_connection) -> None:
    conn = None
    try:
        conn = system_connection()
        while not done.wait(HEARTBEAT_SECONDS):
            image_jobs.job_heartbeat(conn, job_id, worker_id)
    except Exception:  # noqa: BLE001 - a missed heartbeat only risks a later takeover
        logger.exception("job heartbeat failed (job %s)", job_id)
    finally:
        if conn is not None:
            conn.close()


def run_one(worker_id: str, system_connection=None, tenant_connection=None) -> Optional[str]:
    """Claims and processes one job. Returns its new status, or None when
    nothing was waiting. Never raises for a job's own failure."""
    system_connection = system_connection or db.system_connection
    tenant_connection = tenant_connection or db.dedicated_tenant_connection
    sys_conn = system_connection()
    try:
        claimed = image_jobs.claim(sys_conn, worker_id)
    finally:
        sys_conn.close()
    if claimed is None:
        return None
    job_id, tenant_id, created_by = claimed
    conn = tenant_connection(tenant_id, SERVICE_ACTOR)
    done = threading.Event()
    keeper = threading.Thread(target=_keep_alive, args=(job_id, worker_id, done, system_connection), daemon=True)
    started = time.monotonic()

    def finish_failed(message: str, retryable: bool, **kwargs) -> str:
        conn.rollback()
        status = image_jobs.fail(conn, tenant_id, job_id, message, retryable=retryable, **kwargs)
        conn.commit()
        logger.warning("image job %s (tenant %s): %s -> %s", job_id, tenant_id, message, status)
        return status

    try:
        job = image_jobs.get_job(conn, tenant_id, job_id)
        campaign = data_access.get_campaign(conn, tenant_id, job["campaign_id"]) if job else None
        conn.commit()
        if job is None or campaign is None:
            return finish_failed("The campaign no longer exists.", retryable=False)
        if campaign["status"] != "COMPLETED":
            return finish_failed("The campaign's copy isn't ready, so no image prompt exists.", retryable=False)
        keeper.start()
        def record_before_upload(bucket: str, object_key: str, size_bytes: int) -> None:
            storage_ledger.record(conn, tenant_id, bucket, object_key, size_bytes, "marketing_generated_image")
            conn.commit()

        try:
            result = image_service.generate_and_store(
                conn, tenant_id, created_by, job["campaign_id"], campaign,
                image_format=job["image_format"], prompt=job["prompt"], channel=job["channel"],
                attach=job["attach"], seed=job["seed"], fallback_to_designed=DESIGNED_FALLBACK,
                on_pre_upload=record_before_upload,
            )
        except image_generation.ImageGenerationError as err:
            attempts = getattr(err, "attempts", None) or []
            if attempts and all(a.get("reason") == "busy" for a in attempts):
                return finish_failed("Every image server was busy.", retryable=True, delay_seconds=BUSY_RETRY_SECONDS,
                                     count_attempt=False)
            return finish_failed(f"No image could be made: {err.message}", retryable=True)
        except (usage.PlanLimitReached, credits.BudgetError) as err:
            return finish_failed(f"Refused: {type(err).__name__}: {getattr(err, 'reason', '') or err}", retryable=False)
        except image_service.ReferenceImageError:
            return finish_failed("The selected product photo couldn't be read.", retryable=True)
        except Exception as err:  # noqa: BLE001 - storage or database hiccup: retry later
            logger.exception("image job %s failed", job_id)
            return finish_failed(f"Unexpected error: {type(err).__name__}", retryable=True)
        if result.get("image_generation_status") != "COMPLETED":
            return finish_failed(result.get("image_generation_error") or "No image was made.", retryable=True)
        image_jobs.complete(conn, tenant_id, job_id, asset_id=result["asset"]["asset_id"],
                            mode=result["image_generation_mode"], seconds=time.monotonic() - started)
        conn.commit()
        logger.info("image job %s done in %.0fs (%s, %s)", job_id, time.monotonic() - started,
                    job["image_format"], result["image_generation_mode"])
        return "COMPLETED"
    finally:
        done.set()
        conn.close()


def _servers() -> int:
    return max(1, len(image_generation._local_image_base_urls()))


def _thread_loop(worker_id: str) -> None:
    while not _stop.is_set():
        try:
            outcome = run_one(worker_id)
        except Exception:  # noqa: BLE001 - e.g. database briefly unreachable
            logger.exception("worker %s: claim failed", worker_id)
            outcome = None
        if outcome is None or outcome == "QUEUED":  # nothing to do, or servers busy / a retry: don't spin
            _stop.wait(POLL_SECONDS)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KEEL background image worker")
    parser.add_argument("--threads", type=int, default=None, help="jobs at once (default: number of image servers)")
    parser.add_argument("--once", action="store_true", help="process at most one job, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    base_id = f"{socket.gethostname()}:{os.getpid()}"
    if args.once:
        print(run_one(f"{base_id}:once"))
        return 0
    threads = args.threads or _servers()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: _stop.set())  # finish the current image, then stop
    workers = [threading.Thread(target=_thread_loop, args=(f"{base_id}:{i}",), daemon=True) for i in range(threads)]
    for w in workers:
        w.start()
    logger.info("image worker %s started with %d thread(s); servers: %d", base_id, threads, _servers())
    while not _stop.is_set():
        try:
            conn = db.system_connection()
            try:
                image_jobs.worker_heartbeat(conn, base_id, socket.gethostname(), threads)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            logger.exception("worker heartbeat failed")
        _stop.wait(HEARTBEAT_SECONDS)
    for w in workers:
        w.join()
    logger.info("image worker %s stopped", base_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
