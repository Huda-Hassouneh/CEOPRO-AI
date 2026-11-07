"""The API's side of offloading: send a task to the processor and wait for its result.

Light by design: the waiting thread only makes small HTTP calls, so a slow or
unavailable processor costs the API a sleeping thread, never memory or CPU.

- Retries connection errors, 5xx and 429 with exponential backoff (honouring
  Retry-After), always within the caller's deadline.
- Resubmitting is safe: the job id is derived from the task, so the processor
  joins a retry to the job already running instead of starting it again.
- Circuit breaker: after OFFLOAD_BREAKER_FAILURES consecutive failures the
  processor is not called for OFFLOAD_BREAKER_SECONDS; callers get
  ``OffloadUnavailable`` at once and use their fallback.

Settings: OFFLOAD_PROCESSOR_URL, OFFLOAD_SHARED_SECRET (same value as the processor),
OFFLOAD_PROCESSOR_TOKEN (optional bearer token for a host that admits only its owner, e.g. a
private Hugging Face Space - a read-only token is enough).
"""
import json
import logging
import os
import random
import threading
import time
from typing import Optional

import httpx

from src.offload import protocol

logger = logging.getLogger("KEEL_OFFLOAD_CLIENT")


class OffloadUnavailable(Exception):
    """The processor could not be reached or did not finish in time - use the fallback."""


class OffloadFailed(Exception):
    """The processor ran the task and the task failed."""


class _Breaker:
    def __init__(self, failures: int, cooldown: float):
        self.threshold, self.cooldown = failures, cooldown
        self.failures, self.open_until = 0, 0.0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            return time.monotonic() >= self.open_until

    def success(self):
        with self.lock:
            self.failures, self.open_until = 0, 0.0

    def failure(self):
        with self.lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.monotonic() + self.cooldown
                logger.warning("processor unavailable: pausing calls for %.0fs", self.cooldown)


class OffloadClient:
    def __init__(self, base_url: str, secret: str, transport: Optional[httpx.BaseTransport] = None,
                 breaker_failures: int = 3, breaker_seconds: float = 60.0, access_token: Optional[str] = None):
        if len(secret or "") < protocol.MIN_SECRET_LENGTH:
            raise ValueError("OFFLOAD_SHARED_SECRET must be 32+ characters")
        self.base_url, self.secret = base_url.rstrip("/"), secret
        headers = {"User-Agent": "KEEL-API/offload"}
        if access_token:  # a host that admits only its owner (a private Hugging Face Space)
            headers["Authorization"] = f"Bearer {access_token}"
        self.http = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0), transport=transport, headers=headers)
        self.breaker = _Breaker(breaker_failures, breaker_seconds)

    def _request(self, method: str, path: str, body: bytes = b"") -> httpx.Response:
        headers = protocol.sign(self.secret, method, path, body)
        if body:
            headers["Content-Type"] = "application/json"
        return self.http.request(method, self.base_url + path, content=body or None, headers=headers)

    def run(self, kind: str, params: dict, deadline_seconds: float = 180.0) -> dict:
        """Submit (or join) the task and wait for its result until the deadline."""
        if not self.breaker.allow():
            raise OffloadUnavailable("circuit_open")
        deadline = time.monotonic() + deadline_seconds
        body = protocol.canonical({"kind": kind, "params": params})
        job_id = protocol.job_key(kind, params)
        attempt, delay, submitted = 0, 1.0, False
        while time.monotonic() < deadline:
            try:
                if not submitted:
                    response = self._request("POST", "/v1/jobs", body)
                else:
                    response = self._request("GET", f"/v1/jobs/{job_id}")
            except httpx.HTTPError as exc:
                attempt += 1
                logger.info("processor not reachable (%s), attempt %d", type(exc).__name__, attempt)
                if attempt >= 4:
                    self.breaker.failure()
                    raise OffloadUnavailable(type(exc).__name__)
                self._sleep(min(2 ** attempt * 0.5, 8), deadline)
                continue
            if response.status_code in (200, 202):
                job = response.json()
                if job.get("status") == "done":
                    self.breaker.success()
                    return job["result"]
                if job.get("status") == "failed":
                    self.breaker.success()  # it answered: the processor works, the task did not
                    raise OffloadFailed(job.get("error") or "failed")
                submitted, attempt = True, 0
                self._sleep(delay, deadline)
                delay = min(delay * 1.5, 3.0)
                continue
            if response.status_code == 404 and submitted:
                submitted = False  # the processor restarted and lost the job: send it again
                continue
            if response.status_code == 429 or response.status_code >= 500:
                attempt += 1
                if attempt >= 6:
                    self.breaker.failure()
                    raise OffloadUnavailable(f"http_{response.status_code}")
                retry_after = response.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else min(2 ** attempt * 0.5, 8)
                self._sleep(wait, deadline)
                continue
            # 400/401/413: a configuration or programming error - retrying will not help.
            self.breaker.failure()
            raise OffloadUnavailable(f"http_{response.status_code}")
        self.breaker.failure()
        raise OffloadUnavailable("deadline")

    def health(self) -> Optional[dict]:
        try:
            response = self.http.get(self.base_url + "/healthz", timeout=5.0)
            return response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, json.JSONDecodeError):
            return None

    @staticmethod
    def _sleep(seconds: float, deadline: float):
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(seconds * (0.8 + random.random() * 0.4), remaining))


_client: Optional[OffloadClient] = None
_client_lock = threading.Lock()


def configured() -> bool:
    return bool(os.getenv("OFFLOAD_PROCESSOR_URL")) and len(os.getenv("OFFLOAD_SHARED_SECRET", "")) >= protocol.MIN_SECRET_LENGTH


def get_client() -> OffloadClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = OffloadClient(os.environ["OFFLOAD_PROCESSOR_URL"], os.environ["OFFLOAD_SHARED_SECRET"],
                                    breaker_failures=int(os.getenv("OFFLOAD_BREAKER_FAILURES", "3")),
                                    breaker_seconds=float(os.getenv("OFFLOAD_BREAKER_SECONDS", "60")),
                                    access_token=os.getenv("OFFLOAD_PROCESSOR_TOKEN") or None)
        return _client
