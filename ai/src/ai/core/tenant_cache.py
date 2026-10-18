"""
KEEL - short-lived, per-company cache for expensive read models that many
screens need at once (the Command Center is computed for the dashboard AND
for the alerts bell on every page).

Correctness rules:
- Keys always include the company (tenant) id; a value is only ever
  computed through that company's own row-level-security connection, so one
  company can never be served another's result.
- Any write the API makes for a company - every successful or failed
  POST/PUT/PATCH/DELETE (main.py middleware) and the background jobs that
  write after their request returned (forecast refresh, competitor
  discovery, review analysis) - calls bump(), which drops that company's
  entries at once.
- Writes made outside this process (the market workers) are picked up when
  the entry expires: TENANT_CACHE_TTL_SECONDS, 30 by default. 0 disables.
- Concurrent requests for the same missing entry compute it once
  (single-flight); the others wait for that result instead of repeating it.
- Callers get their own copy, so no request can change another's result.

In-process only: each API process has its own cache and bump() reaches only
its own process, so with several API worker processes a write in one
becomes visible in the others within the TTL.
"""
import copy
import os
import threading
import time
from collections import OrderedDict
from typing import Callable, Hashable

TTL_SECONDS = float(os.getenv("TENANT_CACHE_TTL_SECONDS", "30"))
MAX_ENTRIES = int(os.getenv("TENANT_CACHE_MAX_ENTRIES", "512"))

_lock = threading.Lock()
_entries: "OrderedDict[tuple, tuple]" = OrderedDict()  # key -> (expires_at, generation, value)
_generation: dict = {}
_inflight: dict = {}  # key -> threading.Event


def generation(tenant_id: str) -> int:
    with _lock:
        return _generation.get(str(tenant_id), 0)


def bump(tenant_id) -> None:
    """Forget everything cached for this company (its data just changed)."""
    if not tenant_id:
        return
    tenant_id = str(tenant_id)
    with _lock:
        _generation[tenant_id] = _generation.get(tenant_id, 0) + 1
        for key in [k for k in _entries if k[1] == tenant_id]:
            del _entries[key]


def clear() -> None:
    with _lock:
        _entries.clear()
        _generation.clear()


def get_or_compute(namespace: str, tenant_id, key: Hashable, compute: Callable[[], object], ttl: float = None):
    """The cached value for (namespace, company, key), computing it with
    `compute()` when missing or expired."""
    ttl = TTL_SECONDS if ttl is None else ttl
    if ttl <= 0:
        return compute()
    tenant_id = str(tenant_id)
    full_key = (namespace, tenant_id, key)
    while True:
        with _lock:
            now = time.monotonic()
            gen = _generation.get(tenant_id, 0)
            hit = _entries.get(full_key)
            if hit is not None and hit[0] > now and hit[1] == gen:
                _entries.move_to_end(full_key)
                return copy.deepcopy(hit[2])
            waiting = _inflight.get(full_key)
            if waiting is None:
                event = threading.Event()
                _inflight[full_key] = event
                break
        # Someone else is computing it: wait, then read their result (or
        # compute ourselves if they failed or it was invalidated meanwhile).
        waiting.wait(timeout=max(ttl, 30))
    try:
        value = compute()
        with _lock:
            # Only store it if nothing changed for this company while it was
            # being computed - otherwise it may already be out of date.
            if _generation.get(tenant_id, 0) == gen:
                _entries[full_key] = (time.monotonic() + ttl, gen, value)
                _entries.move_to_end(full_key)
                while len(_entries) > MAX_ENTRIES:
                    _entries.popitem(last=False)
        return copy.deepcopy(value)
    finally:
        with _lock:
            _inflight.pop(full_key, None)
        event.set()
