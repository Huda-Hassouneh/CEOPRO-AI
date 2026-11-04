"""Shared operational admission for outbound data providers, never commercial quotas.

Redis is required for atomic, cross-process capacity and duplicate suppression.
Keys contain identities/digests only, never queries, URLs or credentials. Counts
are operational telemetry with 7-day retention, not billable usage/credits.
"""
from contextlib import contextmanager
import hashlib
import json
import logging
import os
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
    try:
        client = get_shared_redis_client(socket_timeout=2, socket_connect_timeout=2)
        limits = [_limit("TENANT_PER_MINUTE", 30), _limit("TENANT_PER_DAY", 500),
                  _limit("PROVIDER_PER_MINUTE", 60), _limit("PROVIDER_PER_DAY", 5000),
                  _limit("TENANT_CONCURRENCY", 3), _limit("PROVIDER_CONCURRENCY", 8)]
        refused = int(client.eval(_ACQUIRE, len(keys), *keys, *limits, token, LEASE_SECONDS))
    except Exception as exc:
        raise SearchCapacityError("Search safety storage unavailable") from exc
    if refused:
        logger.info("search_capacity_refused provider=%s limit=%s", provider, refused)
        raise SearchCapacityError("Search capacity busy; try again shortly")
    outcome = "failed"
    try:
        yield
        outcome = "succeeded"
    finally:
        try:
            client.eval(_RELEASE, 3, *keys[4:], token)
            metric = prefix + f"requests:{namespace}:{int(time.time()) // 86400}"
            with client.pipeline() as pipe:
                pipe.hincrby(metric, f"{operation}:{'free' if free else 'priced'}:{outcome}", 1)
                pipe.expire(metric, 7 * 86400)
                pipe.execute()
        except Exception:
            # Never mask a provider/accounting result or retry a sent request.
            # Leases remain bounded; subsequent admissions fail closed on outage.
            logger.warning("search_capacity_release_unavailable provider=%s", provider)
        logger.info("search_request provider=%s operation=%s free=%s outcome=%s",
                    provider, operation, free, outcome)
