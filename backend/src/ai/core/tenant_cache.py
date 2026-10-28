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

Several API worker processes (WEB_CONCURRENCY): each keeps its own entries,
and bump() also increments the company's generation in Redis, which every
process compares before serving an entry - so a write handled by one worker
invalidates the others at once. Without Redis it falls back to this
process's own generation (others see the write within the TTL) and stops
asking Redis for SHARED_RETRY_SECONDS instead of waiting on it every time.
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


SHARED_KEY_PREFIX = "keel:tenant-cache-generation:"
SHARED_RETRY_SECONDS = 15.0
_shared_down_until = 0.0


def _shared_store():
    """The Redis client for cross-process generations, or None while Redis
    was found unreachable in the last SHARED_RETRY_SECONDS."""
    if time.monotonic() < _shared_down_until:
        return None
    from src.ai.core.redis_client import get_shared_redis_client

    return get_shared_redis_client(socket_connect_timeout=0.2, socket_timeout=0.2)


def _shared_failed() -> None:
    global _shared_down_until
    _shared_down_until = time.monotonic() + SHARED_RETRY_SECONDS


def _shared_generation(tenant_id: str) -> str:
    """The company's generation across all processes ('' when unknown)."""
    store = _shared_store()
    if store is None:
        return ""
    try:
        return store.get(SHARED_KEY_PREFIX + tenant_id) or "0"
    except Exception:  # noqa: BLE001 - Redis down: this process's own generation still applies
        _shared_failed()
        return ""


def generation(tenant_id: str) -> int:
    with _lock:
        return _generation.get(str(tenant_id), 0)


def bump(tenant_id) -> None:
    """Forget everything cached for this company (its data just changed), in
    this process and - through Redis - in every other API process."""
    if not tenant_id:
        return
    tenant_id = str(tenant_id)
    with _lock:
        _generation[tenant_id] = _generation.get(tenant_id, 0) + 1
        for key in [k for k in _entries if k[1] == tenant_id]:
            del _entries[key]
    store = _shared_store()
    if store is not None:
        try:
            store.incr(SHARED_KEY_PREFIX + tenant_id)
            store.expire(SHARED_KEY_PREFIX + tenant_id, 7 * 24 * 3600)
        except Exception:  # noqa: BLE001 - other processes then catch up within the TTL
            _shared_failed()


def clear() -> None:
    global _shared_down_until
    with _lock:
        _entries.clear()
        _generation.clear()
    _shared_down_until = 0.0


def get_or_compute(namespace: str, tenant_id, key: Hashable, compute: Callable[[], object], ttl: float = None):
    """The cached value for (namespace, company, key), computing it with
    `compute()` when missing or expired."""
    ttl = TTL_SECONDS if ttl is None else ttl
    if ttl <= 0:
        return compute()
    tenant_id = str(tenant_id)
    full_key = (namespace, tenant_id, key)
    shared = _shared_generation(tenant_id)
    while True:
        with _lock:
            now = time.monotonic()
            gen = (_generation.get(tenant_id, 0), shared)
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
            if _generation.get(tenant_id, 0) == gen[0]:
                _entries[full_key] = (time.monotonic() + ttl, gen, value)
                _entries.move_to_end(full_key)
                while len(_entries) > MAX_ENTRIES:
                    _entries.popitem(last=False)
        return copy.deepcopy(value)
    finally:
        with _lock:
            _inflight.pop(full_key, None)
        event.set()


def cached_read(namespace: str, ctx, key: Hashable, read: Callable[[object], object], ttl: float = None):
    """get_or_compute() for a read on the caller's own company connection:
    `read(conn)` runs on a fresh row-level-security connection for
    ctx.tenant_id / ctx.user_id, and only when the value isn't cached. Only for
    results that depend on the company's data alone, never on who asks
    (role checks belong in the endpoint's dependencies, before this)."""
    from src.ai import db

    def compute():
        conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
        try:
            return read(conn)
        finally:
            conn.rollback()  # reads only: nothing to keep
            conn.close()

    return get_or_compute(namespace, ctx.tenant_id, key, compute, ttl)
