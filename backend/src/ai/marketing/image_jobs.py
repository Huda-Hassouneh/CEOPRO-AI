"""
KEEL - the background image queue (image_generation_jobs; see migration
20261030000000 for the table, the fair claim function and why RLS is
enabled but not forced on it).

Company-side functions take the company's RLS-scoped connection
(db.app_role_connection / dedicated_tenant_connection), so a company only
ever sees or changes its own jobs. Worker-side functions (claim, worker
heartbeat) take the system connection and only ever handle ids.

Limits (each is a setting, documented in backend/.env.example):
- MARKETING_IMAGE_BATCH_MAX (default 200): images one request may queue.
  A guard against a typo queueing tens of thousands of images, not a quota.
- MARKETING_IMAGE_QUEUE_MAX_PER_COMPANY (default 2000): unfinished images a
  company may have queued at once, so one company can't fill the shared
  queue for days. Size it from the measured speed: at about 2 minutes per
  image on one 4-core CPU server, 2000 images is about 3 days of work.
Nothing limits how many images a company makes over time except its
storage and (for hosted providers only) its plan's image allowance.
"""
import os
import random
import uuid
from typing import List, Optional

from src.ai.marketing import image_generation

BATCH_MAX = int(os.getenv("MARKETING_IMAGE_BATCH_MAX", "200"))
QUEUE_MAX_PER_COMPANY = int(os.getenv("MARKETING_IMAGE_QUEUE_MAX_PER_COMPANY", "2000"))
MAX_ATTEMPTS = int(os.getenv("MARKETING_IMAGE_JOB_MAX_ATTEMPTS", "3"))
# Retry backoff: 1 min, 4 min, 16 min ... (capped at 1 h).
RETRY_BASE_SECONDS = float(os.getenv("MARKETING_IMAGE_JOB_RETRY_SECONDS", "60"))
# A RUNNING job whose worker sent no heartbeat for this long is taken over.
STALE_SECONDS = int(os.getenv("MARKETING_IMAGE_JOB_STALE_SECONDS", "900"))
WORKER_ALIVE_SECONDS = int(os.getenv("MARKETING_IMAGE_WORKER_ALIVE_SECONDS", "120"))

UNFINISHED = ("QUEUED", "RUNNING")


class QueueLimit(Exception):
    def __init__(self, message: str, limit: int, pending: int = 0):
        super().__init__(message)
        self.message, self.limit, self.pending = message, limit, pending


def pending_count(conn, tenant_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM image_generation_jobs WHERE tenant_id = %s AND status IN ('QUEUED', 'RUNNING');",
                       (tenant_id,))
        return int(cursor.fetchone()[0])


def enqueue_batch(conn, tenant_id: str, user_id: Optional[str], campaign_id: str, *, formats: List[str],
                  variations: int = 1, prompt: Optional[str] = None, channel: Optional[str] = None,
                  attach_first: bool = False) -> dict:
    """Queues variations x formats images (each a distinct random seed).
    Raises QueueLimit when over MARKETING_IMAGE_BATCH_MAX or the company's
    MARKETING_IMAGE_QUEUE_MAX_PER_COMPANY. Caller commits."""
    formats = list(dict.fromkeys(formats))
    unknown = [f for f in formats if f not in image_generation.IMAGE_FORMATS]
    if not formats or unknown:
        raise ValueError(f"formats must be among {list(image_generation.IMAGE_FORMATS)}")
    if variations < 1:
        raise ValueError("variations must be at least 1")
    total = len(formats) * variations
    if total > BATCH_MAX:
        raise QueueLimit(f"One request can queue at most {BATCH_MAX} images.", BATCH_MAX)
    pending = pending_count(conn, tenant_id)
    if pending + total > QUEUE_MAX_PER_COMPANY:
        raise QueueLimit(f"At most {QUEUE_MAX_PER_COMPANY} images can be waiting at once; {pending} already are.",
                         QUEUE_MAX_PER_COMPANY, pending)
    batch_id = str(uuid.uuid4())
    prompt = (prompt or "").strip()[:2000] or None
    rows = []
    for variation in range(variations):
        for image_format in formats:
            rows.append((tenant_id, campaign_id, batch_id, image_format, prompt, channel,
                         random.randint(0, 2**32 - 1), attach_first and not rows, MAX_ATTEMPTS, user_id))
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO image_generation_jobs
                (tenant_id, campaign_id, batch_id, image_format, prompt, channel, seed, attach, max_attempts, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            rows,
        )
    return {"batch_id": batch_id, "queued": total, "formats": formats, "variations": variations}


_JOB_COLUMNS = ("job_id, campaign_id, batch_id, image_format, channel, status, attempts, max_attempts, "
                "next_attempt_at, asset_id, mode, error, seconds, created_at, started_at, finished_at")


def _job_row(row) -> dict:
    keys = [k.strip() for k in _JOB_COLUMNS.split(",")]
    job = dict(zip(keys, row))
    for key in ("job_id", "campaign_id", "batch_id", "asset_id"):
        job[key] = str(job[key]) if job[key] else None
    for key in ("next_attempt_at", "created_at", "started_at", "finished_at"):
        job[key] = job[key].isoformat() if job[key] else None
    job["seconds"] = float(job["seconds"]) if job["seconds"] is not None else None
    return job


def list_jobs(conn, tenant_id: str, campaign_id: Optional[str] = None, batch_id: Optional[str] = None,
              limit: int = 200) -> dict:
    """The company's jobs (newest first) and their counts by status."""
    where, params = ["tenant_id = %s"], [tenant_id]
    if campaign_id:
        where.append("campaign_id = %s")
        params.append(campaign_id)
    if batch_id:
        where.append("batch_id = %s")
        params.append(batch_id)
    clause = " AND ".join(where)
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT status, COUNT(*) FROM image_generation_jobs WHERE {clause} GROUP BY status;", params)
        counts = {status: int(n) for status, n in cursor.fetchall()}
        cursor.execute(f"SELECT {_JOB_COLUMNS} FROM image_generation_jobs WHERE {clause} "
                       "ORDER BY created_at DESC, job_id LIMIT %s;", (*params, limit))
        jobs = [_job_row(r) for r in cursor.fetchall()]
    totals = {s: counts.get(s, 0) for s in ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")}
    return {"counts": totals, "total": sum(totals.values()), "jobs": jobs}


def cancel(conn, tenant_id: str, campaign_id: str, batch_id: Optional[str] = None) -> int:
    """Cancels waiting jobs (a running one finishes). Returns how many."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE image_generation_jobs SET status = 'CANCELLED', finished_at = NOW() "
            "WHERE tenant_id = %s AND campaign_id = %s AND status = 'QUEUED'" + (" AND batch_id = %s" if batch_id else "")
            + " RETURNING job_id;",
            (tenant_id, campaign_id, *([batch_id] if batch_id else [])),
        )
        return len(cursor.fetchall())


def retry_failed(conn, tenant_id: str, campaign_id: str) -> int:
    """Queues the campaign's failed jobs again from scratch."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE image_generation_jobs SET status = 'QUEUED', attempts = 0, error = NULL, next_attempt_at = NOW(), "
            "finished_at = NULL WHERE tenant_id = %s AND campaign_id = %s AND status = 'FAILED' RETURNING job_id;",
            (tenant_id, campaign_id),
        )
        return len(cursor.fetchall())


def get_job(conn, tenant_id: str, job_id: str) -> Optional[dict]:
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT {_JOB_COLUMNS}, prompt, seed, attach FROM image_generation_jobs "
                       "WHERE tenant_id = %s AND job_id = %s;", (tenant_id, job_id))
        row = cursor.fetchone()
    if row is None:
        return None
    job = _job_row(row[:-3])
    job["prompt"], job["seed"], job["attach"] = row[-3], int(row[-2]) if row[-2] is not None else None, bool(row[-1])
    return job


def complete(conn, tenant_id: str, job_id: str, *, asset_id: Optional[str], mode: Optional[str], seconds: float) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE image_generation_jobs SET status = 'COMPLETED', asset_id = %s, mode = %s, seconds = %s, error = NULL, "
            "finished_at = NOW() WHERE tenant_id = %s AND job_id = %s;",
            (asset_id, mode, round(seconds, 1), tenant_id, job_id),
        )


def fail(conn, tenant_id: str, job_id: str, error: str, *, retryable: bool, delay_seconds: Optional[float] = None,
         count_attempt: bool = True) -> str:
    """Records a failed attempt. Retryable failures go back to QUEUED with
    backoff until max_attempts; then (or when not retryable) FAILED.
    count_attempt=False (the image servers were only busy) re-queues
    without using up an attempt. Returns the new status."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT attempts, max_attempts FROM image_generation_jobs WHERE tenant_id = %s AND job_id = %s;",
                       (tenant_id, job_id))
        row = cursor.fetchone()
        if row is None:
            return "MISSING"
        attempts, max_attempts = row
        if not count_attempt:
            attempts = max(0, attempts - 1)
        if retryable and attempts < max_attempts:
            delay = delay_seconds if delay_seconds is not None else min(3600.0, RETRY_BASE_SECONDS * (4 ** max(0, attempts - 1)))
            cursor.execute(
                "UPDATE image_generation_jobs SET status = 'QUEUED', attempts = %s, error = %s, worker_id = NULL, "
                "next_attempt_at = NOW() + make_interval(secs => %s) WHERE tenant_id = %s AND job_id = %s;",
                (attempts, error[:1000], float(delay), tenant_id, job_id),
            )
            return "QUEUED"
        cursor.execute(
            "UPDATE image_generation_jobs SET status = 'FAILED', attempts = %s, error = %s, finished_at = NOW() "
            "WHERE tenant_id = %s AND job_id = %s;",
            (attempts, error[:1000], tenant_id, job_id),
        )
        return "FAILED"


# --- worker side (system connection; ids only) --------------------------------

def claim(sys_conn, worker_id: str) -> Optional[tuple]:
    """(job_id, tenant_id, created_by) of the next job, or None. Commits."""
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT job_id, tenant_id, created_by FROM claim_image_generation_job(%s, %s);",
                       (worker_id, STALE_SECONDS))
        row = cursor.fetchone()
    sys_conn.commit()
    if row is None or row[0] is None:
        return None
    return str(row[0]), str(row[1]), (str(row[2]) if row[2] else None)


def job_heartbeat(sys_conn, job_id: str, worker_id: str) -> None:
    with sys_conn.cursor() as cursor:
        cursor.execute("UPDATE image_generation_jobs SET heartbeat_at = NOW() WHERE job_id = %s AND worker_id = %s "
                       "AND status = 'RUNNING';", (job_id, worker_id))
    sys_conn.commit()


def worker_heartbeat(sys_conn, worker_id: str, host: str, servers: int, made: int = 0) -> None:
    with sys_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO image_workers (worker_id, host, servers, heartbeat_at, images_made) VALUES (%s, %s, %s, NOW(), %s)
            ON CONFLICT (worker_id) DO UPDATE SET heartbeat_at = NOW(), servers = EXCLUDED.servers,
                images_made = image_workers.images_made + EXCLUDED.images_made;
            """,
            (worker_id, host[:200], servers, made),
        )
    sys_conn.commit()


def capacity(conn, window_minutes: int = 60) -> dict:
    """What the queue can do right now, measured, not assumed: images
    finished in the last window, average seconds per AI image, live workers
    and image servers, and the resulting images per hour and queue wait."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM image_generation_capacity(%s, %s);", (window_minutes, WORKER_ALIVE_SECONDS))
        queued, running, completed, avg_seconds, workers, servers = cursor.fetchone()
    avg = float(avg_seconds) if avg_seconds is not None else None
    parallel = max(int(servers or 0), 0)
    per_hour = round(3600 / avg * parallel) if avg and parallel else None
    backlog = int(queued) + int(running)
    return {
        "queued": int(queued), "running": int(running), "completed_last_hour": int(completed),
        "average_seconds_per_image": avg, "workers": int(workers), "image_servers": parallel,
        "images_per_hour": per_hour, "estimated_wait_minutes": round(backlog / per_hour * 60) if per_hour else None,
        "available": int(workers) > 0, "batch_max": BATCH_MAX, "queue_max_per_company": QUEUE_MAX_PER_COMPANY,
    }
