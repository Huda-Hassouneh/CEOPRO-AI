"""Shared operational admission for outbound data providers, never commercial quotas.

Redis provides atomic, cross-process capacity and duplicate suppression. When
it is unreachable, FREE providers fall back to the same limits enforced inside
this process (degraded mode, logged), so competitor discovery keeps working
during a Redis outage; PRICED providers stay fail-closed, because without the
shared limiter several workers could spend Data Credits in parallel.
Keys contain identities/digests only, never queries, URLs or credentials. Counts
are operational telemetry with 7-day retention, not billable usage/credits.
"""
from collections import deque
from contextlib import contextmanager
import hashlib
import json
import logging
import os
import threading
import time
import uuid

import httpx

from src.ai.billing import credits
from src.ai.core.redis_client import get_shared_redis_client

logger = logging.getLogger("KEEL_SEARCH_CAPACITY")
LEASE_SECONDS = 300

# Check every limit before mutating any counter. Redis TIME avoids worker clock
# skew. The lease covers existing data-actor transports (180s) as well as the
# shorter search transports. Expiry recovers crashed workers without opening
# concurrency slots while a normal actor request is still running.
_ACQUIRE = """
local now=tonumber(redis.call('TIME')[1])
for i=5,6 do redis.call('ZREMRANGEBYSCORE',KEYS[i],'-inf',now) end
for i=1,4 do
 if tonumber(redis.call('GET',KEYS[i]) or '0')>=tonumber(ARGV[i]) then return i end
end
if redis.call('ZCARD',KEYS[5])>=tonumber(ARGV[5]) then return 5 end
if redis.call('ZCARD',KEYS[6])>=tonumber(ARGV[6]) then return 6 end
if redis.call('EXISTS',KEYS[7])==1 then return 7 end
for i=1,4 do
 if redis.call('INCR',KEYS[i])==1 then
  redis.call('EXPIRE',KEYS[i],i%2==1 and 60 or 86400)
 end
end
for i=5,6 do
 redis.call('ZADD',KEYS[i],now+tonumber(ARGV[8]),ARGV[7])
 redis.call('EXPIRE',KEYS[i],tonumber(ARGV[8]))
end
redis.call('SET',KEYS[7],ARGV[7],'EX',ARGV[8])
return 0
"""
_RELEASE = """
for i=1,2 do redis.call('ZREM',KEYS[i],ARGV[1]) end
if redis.call('GET',KEYS[3])==ARGV[1] then redis.call('DEL',KEYS[3]) end
return 1
"""


class SearchCapacityError(httpx.HTTPError):
    """Safe provider-neutral refusal, including unavailable safety storage."""


class _LocalLimiter:
    """In-process stand-in for the Redis limiter (free providers only): the
    same minute/day windows, concurrency caps and duplicate suppression, per
    API process. Bounded memory: windows prune themselves."""

    def __init__(self):
        self._lock = threading.Lock()
        self._events = {}    # key -> deque of admission times
        self._inflight = {}  # key -> set of tokens
        self._dedupe = {}    # key -> expiry time

    def acquire(self, keys, limits, token, now=None):
        now = time.monotonic() if now is None else now
        windows = (60, 86400, 60, 86400)
        with self._lock:
            for key, window in zip(keys[:4], windows):
                events = self._events.setdefault(key, deque())
                while events and events[0] <= now - window:
                    events.popleft()
            for index in range(4):
                if len(self._events[keys[index]]) >= limits[index]:
                    return index + 1
            for index in (4, 5):
                if len(self._inflight.get(keys[index], ())) >= limits[index]:
                    return index + 1
            if self._dedupe.get(keys[6], 0) > now:
                return 7
            for key in keys[:4]:
                self._events[key].append(now)
            for key in keys[4:6]:
                self._inflight.setdefault(key, set()).add(token)
            self._dedupe[keys[6]] = now + LEASE_SECONDS
            if len(self._dedupe) > 10000:
                self._dedupe = {k: v for k, v in self._dedupe.items() if v > now}
            return 0

    def release(self, keys, token):
        with self._lock:
            for key in keys[4:6]:
                self._inflight.get(key, set()).discard(token)
            self._dedupe.pop(keys[6], None)


_local = _LocalLimiter()


def fingerprint(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _limit(name, default):
    # Invalid/zero configuration fails closed; it never disables protection.
    value = int(os.getenv("SEARCH_" + name, str(default)))
    if value <= 0:
        raise ValueError("invalid operational search limit")
    return value


@contextmanager
def admission(provider, operation, *, free, request_key=None):
    ctx = credits.current()
    if ctx is None or not ctx.tenant_id:
        raise SearchCapacityError("Search requires an authorized tenant context")
    credits.ensure_access(ctx.tenant_id)
    tenant = fingerprint(ctx.tenant_id)
    namespace = fingerprint(provider)
    token = uuid.uuid4().hex
    prefix = "keel:search:safety:"
    # Fixed windows anchored at first admission bound burst/day capacity.
    keys = [prefix + k for k in (
        f"tenant:{tenant}:minute", f"tenant:{tenant}:day",
        f"provider:{namespace}:minute", f"provider:{namespace}:day",
        f"tenant:{tenant}:inflight", f"provider:{namespace}:inflight",
        f"dedupe:{tenant}:{namespace}:{request_key or token}",
    )]
    limits = [_limit("TENANT_PER_MINUTE", 30), _limit("TENANT_PER_DAY", 500),
              _limit("PROVIDER_PER_MINUTE", 60), _limit("PROVIDER_PER_DAY", 5000),
              _limit("TENANT_CONCURRENCY", 3), _limit("PROVIDER_CONCURRENCY", 8)]
    client = None
    try:
        client = get_shared_redis_client(socket_timeout=2, socket_connect_timeout=2)
        refused = int(client.eval(_ACQUIRE, len(keys), *keys, *limits, token, LEASE_SECONDS))
    except Exception as exc:
        client = None
        if not free:
            raise SearchCapacityError("Search safety storage unavailable") from exc
        logger.warning("search_capacity_degraded provider=%s: Redis unavailable, enforcing limits in this process",
                       provider)
        refused = _local.acquire(keys, limits, token)
    if refused:
        logger.info("search_capacity_refused provider=%s limit=%s", provider, refused)
        raise SearchCapacityError("Search capacity busy; try again shortly")
    outcome = "failed"
    try:
        yield
        outcome = "succeeded"
    finally:
        if client is None:
            _local.release(keys, token)
            logger.info("search_request provider=%s operation=%s free=%s outcome=%s degraded=true",
                        provider, operation, free, outcome)
        else:
            try:
                client.eval(_RELEASE, 3, *keys[4:], token)
                metric = prefix + f"requests:{namespace}:{int(time.time()) // 86400}"
                with client.pipeline() as pipe:
                    pipe.hincrby(metric, f"{operation}:{'free' if free else 'priced'}:{outcome}", 1)
                    pipe.expire(metric, 7 * 86400)
                    pipe.execute()
            except Exception:
                # Never mask a provider/accounting result or retry a sent request.
                # Leases remain bounded; priced admissions fail closed on outage.
                logger.warning("search_capacity_release_unavailable provider=%s", provider)
            logger.info("search_request provider=%s operation=%s free=%s outcome=%s",
                        provider, operation, free, outcome)
