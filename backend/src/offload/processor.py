"""The processor: a small HTTP service that runs heavy KEEL tasks away from the API.

    uvicorn src.offload.processor:app --host 0.0.0.0 --port 7860

POST /v1/jobs            {"kind": ..., "params": {...}}   -> 200 done (cached) | 202 queued/running | 429 full
GET  /v1/jobs/{job_id}   -> {"status": "queued"|"running"|"done"|"failed", "result"?, "error"?}
GET  /healthz            -> liveness and load, no task data (unsigned, for uptime checks)

Guarantees:
- Each task runs in its own child process (a fresh one per task), started from
  a pre-loaded fork server. A task that crashes or is killed for memory fails
  that one job; the server and the other jobs keep running.
- Identical tasks share one job id: while one runs, a second request for it
  joins it, and a finished result is served from memory for OFFLOAD_RESULT_TTL.
- At most OFFLOAD_MAX_PARALLEL tasks run at once and OFFLOAD_MAX_QUEUE wait;
  beyond that the processor answers 429 with Retry-After instead of taking
  more work than the machine can hold.
- Every /v1 request must be signed with OFFLOAD_SHARED_SECRET (protocol.py).

Settings: OFFLOAD_SHARED_SECRET (required, 32+ characters), OFFLOAD_MAX_PARALLEL
(default: CPU count, at most 4), OFFLOAD_MAX_QUEUE (32), OFFLOAD_JOB_TIMEOUT
seconds (240), OFFLOAD_RESULT_TTL seconds (21600), OFFLOAD_MAX_RESULTS kept (512),
OFFLOAD_WARM_OVERTURE=true reads the Overture index at start so the first task is fast.
"""
import asyncio
import concurrent.futures
import logging
import multiprocessing
import os
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from src.offload import protocol, tasks

logger = logging.getLogger("KEEL_OFFLOAD_PROCESSOR")
if not logging.getLogger().handlers:  # uvicorn configures only its own loggers
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WARM = {"overture_index": "off"}  # off | warming | ready | failed

SECRET = os.getenv("OFFLOAD_SHARED_SECRET", "")
MAX_PARALLEL = max(1, int(os.getenv("OFFLOAD_MAX_PARALLEL", str(min(os.cpu_count() or 1, 4)))))
MAX_QUEUE = max(0, int(os.getenv("OFFLOAD_MAX_QUEUE", "32")))
JOB_TIMEOUT = float(os.getenv("OFFLOAD_JOB_TIMEOUT", "240"))
RESULT_TTL = float(os.getenv("OFFLOAD_RESULT_TTL", str(6 * 3600)))
FAILED_TTL = 60.0  # a failed job may be asked again after a minute
MAX_RESULTS = int(os.getenv("OFFLOAD_MAX_RESULTS", "512"))
MAX_BODY_BYTES = 64 * 1024


def _child_main(sender, kind: str, params: dict):
    try:
        sender.send(("ok", tasks.run(kind, params)))
    except Exception as exc:  # noqa: BLE001 - the type only: task data never goes into errors
        sender.send(("error", type(exc).__name__))
    finally:
        sender.close()


@dataclass
class Job:
    job_id: str
    kind: str
    params: dict
    status: str = "queued"
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    joined: int = 0  # duplicate requests that shared this job instead of running it again

    def public(self) -> dict:
        body = {"job_id": self.job_id, "kind": self.kind, "status": self.status, "joined": self.joined}
        if self.started:
            body["queue_seconds"] = round(self.started - self.created, 3)
        if self.finished and self.started:
            body["run_seconds"] = round(self.finished - self.started, 3)
        if self.status == "done":
            body["result"] = self.result
        if self.status == "failed":
            body["error"] = self.error
        return body


class Processor:
    def __init__(self, max_parallel: int = MAX_PARALLEL, max_queue: int = MAX_QUEUE, job_timeout: float = JOB_TIMEOUT):
        self.max_parallel, self.max_queue, self.job_timeout = max_parallel, max_queue, job_timeout
        self.jobs: "OrderedDict[str, Job]" = OrderedDict()
        self.semaphore = asyncio.Semaphore(max_parallel)
        self.children = {}
        self.context = None
        # Threads that only wait on children (one per running task).
        self.waiters = concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="offload-wait")
        self.stats = {"submitted": 0, "deduplicated": 0, "cache_hits": 0, "completed": 0, "failed": 0,
                      "rejected_full": 0, "child_crashes": 0}
        self.started_at = time.time()

    # -- child processes ----------------------------------------------------
    def start(self):
        context = multiprocessing.get_context("forkserver")
        context.set_forkserver_preload(["src.offload.tasks"])
        self.context = context

    def stop(self):
        for process in list(self.children.values()):
            process.kill()

    def _run_in_child(self, job: Job):
        """Blocking: run one task in its own process and wait for it (called in a thread).
        One process per task: a crash or out-of-memory kill ends that process only, and the
        memory a task used goes back to the machine the moment it ends."""
        receiver, sender = self.context.Pipe(duplex=False)
        process = self.context.Process(target=_child_main, args=(sender, job.kind, job.params), daemon=True)
        process.start()
        sender.close()
        self.children[job.job_id] = process
        try:
            if not receiver.poll(self.job_timeout):
                process.kill()
                return "failed", None, "timeout"
            try:
                outcome, value = receiver.recv()
            except EOFError:  # died before answering: killed for memory, segfault
                process.join(5)
                return "failed", None, "worker_crashed"
            return ("done", value, None) if outcome == "ok" else ("failed", None, value)
        finally:
            receiver.close()
            process.join(5)
            if process.is_alive():
                process.kill()
            self.children.pop(job.job_id, None)

    # -- bookkeeping --------------------------------------------------------
    def _expire(self):
        now = time.time()
        for job_id in list(self.jobs):
            job = self.jobs[job_id]
            ttl = RESULT_TTL if job.status == "done" else FAILED_TTL if job.status == "failed" else None
            if ttl is not None and job.finished and now - job.finished > ttl:
                del self.jobs[job_id]
        while len(self.jobs) > MAX_RESULTS:  # oldest finished results go first
            oldest = next((k for k, j in self.jobs.items() if j.status in ("done", "failed")), None)
            if oldest is None:
                break
            del self.jobs[oldest]

    def waiting(self) -> int:
        return sum(1 for j in self.jobs.values() if j.status == "queued")

    def running(self) -> int:
        return sum(1 for j in self.jobs.values() if j.status == "running")

    # -- submission ---------------------------------------------------------
    def submit(self, kind: str, params: dict):
        """(job, http_status). Never runs a task twice while it is queued, running or recently done."""
        if kind not in tasks.TASKS:
            raise HTTPException(status_code=400, detail="unknown task kind")
        self._expire()
        job_id = protocol.job_key(kind, params)
        existing = self.jobs.get(job_id)
        if existing and existing.status in ("queued", "running"):
            existing.joined += 1
            self.stats["deduplicated"] += 1
            return existing, 202
        if existing and existing.status == "done":
            self.jobs.move_to_end(job_id)
            self.stats["cache_hits"] += 1
            return existing, 200
        if self.waiting() + self.running() >= self.max_parallel + self.max_queue:
            self.stats["rejected_full"] += 1
            return None, 429
        job = Job(job_id, kind, params)
        self.jobs[job_id] = job
        self.stats["submitted"] += 1
        asyncio.get_running_loop().create_task(self._execute(job))
        return job, 202

    async def _execute(self, job: Job):
        async with self.semaphore:
            job.status, job.started = "running", time.time()
            loop = asyncio.get_running_loop()
            try:
                status, result, error = await loop.run_in_executor(self.waiters, self._run_in_child, job)
            except Exception as exc:  # noqa: BLE001 - could not start the child
                status, result, error = "failed", None, type(exc).__name__
            job.status, job.result, job.error, job.finished = status, result, error, time.time()
            if status == "done":
                self.stats["completed"] += 1
            else:
                self.stats["failed"] += 1
                if error == "worker_crashed":
                    self.stats["child_crashes"] += 1
                logger.warning("task %s failed: %s", job.kind, error)

    def health(self) -> dict:
        rss = None
        try:
            import psutil

            process = psutil.Process()
            rss = process.memory_info().rss + sum(c.memory_info().rss for c in process.children(recursive=True))
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "protocol": protocol.PROTOCOL_VERSION, "warm": dict(WARM), "uptime_seconds": round(time.time() - self.started_at),
                "running": self.running(), "queued": self.waiting(), "max_parallel": self.max_parallel,
                "max_queue": self.max_queue, "memory_mb": round(rss / 2**20, 1) if rss else None, "stats": self.stats}


def create_app(secret: Optional[str] = None, **options) -> FastAPI:
    secret = SECRET if secret is None else secret
    if len(secret) < protocol.MIN_SECRET_LENGTH:
        raise RuntimeError("OFFLOAD_SHARED_SECRET must be set (32+ characters)")
    if not (os.getenv("OVERTURE_CACHE_SIGNING_KEY") or os.getenv("JWT_SECRET")):
        # Each task is a fresh process: the Overture index must come from the signed disk cache,
        # not be rebuilt per task. Children inherit this environment.
        import hashlib

        os.environ["OVERTURE_CACHE_SIGNING_KEY"] = hashlib.sha256(b"overture-cache:" + secret.encode()).hexdigest()
    processor = Processor(**options)

    @asynccontextmanager
    async def lifespan(_app):
        processor.start()
        if os.getenv("OFFLOAD_WARM_OVERTURE", "").lower() in ("1", "true", "yes"):
            asyncio.get_running_loop().run_in_executor(None, _warm_overture)
        yield
        processor.stop()

    app = FastAPI(title="KEEL processor", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.processor = processor

    async def _authorized(request: Request) -> bytes:
        # Bound the read before anything else: an unsigned client must not make the processor
        # buffer an arbitrarily large body (declared or chunked) just to be refused afterwards.
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
            raise HTTPException(status_code=413, detail="body too large")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="body too large")
            chunks.append(chunk)
        body = b"".join(chunks)
        if not protocol.verify(secret, request.method, request.url.path, body,
                               request.headers.get(protocol.TIMESTAMP_HEADER),
                               request.headers.get(protocol.SIGNATURE_HEADER)):
            raise HTTPException(status_code=401, detail="bad signature")
        return body

    @app.post("/v1/jobs")
    async def submit(request: Request):
        import json

        body = await _authorized(request)
        try:
            payload = json.loads(body)
            kind, params = payload["kind"], payload.get("params") or {}
        except (ValueError, KeyError, TypeError):
            raise HTTPException(status_code=400, detail="expected {kind, params}")
        job, status = processor.submit(kind, params)
        if job is None:
            return JSONResponse({"status": "busy"}, status_code=429, headers={"Retry-After": "5"})
        return JSONResponse(job.public(), status_code=status)

    @app.get("/v1/jobs/{job_id}")
    async def status(job_id: str, request: Request):
        await _authorized(request)
        job = processor.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown or expired job")
        return job.public()

    @app.get("/healthz")
    async def healthz():
        return processor.health()

    return app


def _warm_overture():
    """Read the Overture index once at start (kept on disk), so the first company waits less."""
    WARM["overture_index"] = "warming"
    started = time.time()
    try:
        import httpx

        from src.market_scraper.market_discovery.providers import overture

        with httpx.Client(timeout=60) as client:
            overture._load_index(client)
        WARM["overture_index"] = "ready"
        WARM["overture_index_seconds"] = round(time.time() - started, 1)
        logger.info("Overture index ready in %.1fs", time.time() - started)
    except Exception as exc:  # noqa: BLE001 - only an optimisation
        WARM["overture_index"] = "failed"
        logger.warning("Overture warm-up skipped: %s", type(exc).__name__)


app = create_app() if len(SECRET) >= protocol.MIN_SECRET_LENGTH else None
