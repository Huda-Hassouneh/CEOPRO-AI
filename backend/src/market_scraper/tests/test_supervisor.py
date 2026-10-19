"""The worker supervisor: which workers run, restart backoff, and a clean stop."""
import subprocess
import sys

import pytest

from src.market_scraper import supervisor
from src.market_scraper.supervisor import Supervisor, next_backoff, selected_workers


def test_all_workers_run_by_default():
    assert selected_workers(None) == list(supervisor.WORKERS)
    assert selected_workers("  ") == list(supervisor.WORKERS)


def test_a_subset_can_be_chosen_and_typos_are_errors():
    assert selected_workers("discovery, maintenance") == ["discovery", "maintenance"]
    with pytest.raises(ValueError, match="unknown worker"):
        selected_workers("discovery,maintainance")


def test_every_worker_module_exists():
    import importlib.util
    for module in supervisor.WORKERS.values():
        assert importlib.util.find_spec(module) is not None, module


def test_backoff_doubles_on_crash_loops_caps_and_resets_after_healthy_uptime():
    assert next_backoff(1, uptime=2) == 2
    assert next_backoff(32, uptime=2) == 60
    assert next_backoff(60, uptime=2) == 60
    assert next_backoff(60, uptime=supervisor.HEALTHY_AFTER) == supervisor.MIN_BACKOFF


class FakeProcess:
    _next_pid = 100

    def __init__(self):
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


def test_a_crashed_worker_is_restarted_after_its_backoff():
    now = [0.0]
    spawned = []

    def spawn(module):
        process = FakeProcess()
        spawned.append((module, process))
        return process

    sup = Supervisor(["discovery"], spawn=spawn, clock=lambda: now[0])
    sup.poll()
    assert len(spawned) == 1
    spawned[0][1].code = 1          # crashes right away
    now[0] = 1
    sup.poll()                      # noticed; restart scheduled, not immediate
    assert len(spawned) == 1 and sup.children[0].restarts == 1
    now[0] = 1 + sup.children[0].backoff
    sup.poll()
    assert len(spawned) == 2 and spawned[1][0] == "src.market_scraper.discovery_worker"


def test_stop_terminates_every_running_worker():
    processes = []
    sup = Supervisor(["prices", "maintenance"], spawn=lambda m: processes.append(FakeProcess()) or processes[-1])
    sup.poll()
    sup.stop()
    assert all(p.terminated for p in processes) and sup.stopping


def test_real_child_processes_are_started_and_stopped():
    """End to end with real processes standing in for the workers."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    sup = Supervisor(["prices", "analysis"], spawn=lambda module: subprocess.Popen(sleeper))
    sup.poll()
    pids = [child.process.pid for child in sup.children]
    assert all(child.process.poll() is None for child in sup.children)
    sup.stop()
    assert len(set(pids)) == 2
    assert all(child.process.poll() is not None for child in sup.children)
