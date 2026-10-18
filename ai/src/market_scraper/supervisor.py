"""
Runs the market background workers together in one container.

Each worker is its own `python -m` child process (the price collector
starts Scrapy, whose Twisted reactor can only run once per process, so they
can't share one interpreter). A worker that exits is restarted after a
backoff that grows from 1 s to 60 s and resets once it has stayed up for a
minute. SIGTERM/SIGINT stop every worker and then the supervisor, so a
deploy or restart drains cleanly.

    python -m src.market_scraper.supervisor

KEEL_WORKERS limits which workers run (comma-separated names below),
e.g. KEEL_WORKERS=discovery,maintenance. Default: all of them.
"""

import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("KEEL_WORKER_SUPERVISOR")

WORKERS: Dict[str, str] = {
    "prices": "src.market_scraper.worker",
    "analysis": "src.market_scraper.analysis_worker",
    "discovery": "src.market_scraper.discovery_worker",
    "enrichment": "src.market_scraper.enrichment_worker",
    "connectors": "src.market_scraper.connector_worker",
    "maintenance": "src.market_scraper.maintenance",
}
MIN_BACKOFF = 1.0
MAX_BACKOFF = 60.0
HEALTHY_AFTER = 60.0
STOP_GRACE_SECONDS = 20.0


@dataclass
class Child:
    name: str
    module: str
    process: Optional[subprocess.Popen] = None
    started_at: float = 0.0
    backoff: float = MIN_BACKOFF
    restart_at: float = 0.0
    restarts: int = field(default=0)


def selected_workers(value: Optional[str]) -> List[str]:
    """Worker names from KEEL_WORKERS; unknown names are an error, not a silent skip."""
    if not value or not value.strip():
        return list(WORKERS)
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in WORKERS]
    if unknown:
        raise ValueError(f"unknown worker(s) {unknown}; choose from {sorted(WORKERS)}")
    return names


def next_backoff(current: float, uptime: float) -> float:
    """Back off on crash loops; a worker that stayed up long enough starts over."""
    if uptime >= HEALTHY_AFTER:
        return MIN_BACKOFF
    return min(MAX_BACKOFF, max(MIN_BACKOFF, current * 2))


class Supervisor:
    def __init__(self, names: List[str], spawn: Optional[Callable[[str], subprocess.Popen]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.children = [Child(name, WORKERS[name]) for name in names]
        self._spawn = spawn or (lambda module: subprocess.Popen([sys.executable, "-m", module]))
        self._clock = clock
        self.stopping = False

    def start(self, child: Child) -> None:
        child.process = self._spawn(child.module)
        child.started_at = self._clock()
        logger.info("started %s (pid %s)", child.name, child.process.pid)

    def poll(self) -> None:
        """Start, or restart after its backoff, any worker that isn't running."""
        now = self._clock()
        for child in self.children:
            if child.process is None:
                if now >= child.restart_at:
                    self.start(child)
                continue
            code = child.process.poll()
            if code is None:
                continue
            uptime = now - child.started_at
            child.backoff = next_backoff(child.backoff, uptime)
            child.restart_at = now + child.backoff
            child.restarts += 1
            child.process = None
            logger.warning("%s exited with code %s after %.0fs; restarting in %.0fs",
                           child.name, code, uptime, child.backoff)

    def stop(self) -> None:
        self.stopping = True
        running = [c for c in self.children if c.process is not None and c.process.poll() is None]
        for child in running:
            child.process.terminate()
        deadline = self._clock() + STOP_GRACE_SECONDS
        for child in running:
            try:
                child.process.wait(timeout=max(0.0, deadline - self._clock()))
            except subprocess.TimeoutExpired:
                logger.warning("%s did not stop in time; killing it", child.name)
                child.process.kill()
                child.process.wait()
        logger.info("all workers stopped")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        names = selected_workers(os.getenv("KEEL_WORKERS"))
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    supervisor = Supervisor(names)

    def _stop(signum, _frame):
        logger.info("received signal %s, stopping workers", signum)
        supervisor.stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("supervising: %s", ", ".join(names))
    while not supervisor.stopping:
        supervisor.poll()
        time.sleep(1)
    supervisor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
