"""Tenant-scoped RAG search results with durable provider-start fencing."""
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from src.ai.core.redis_client import get_shared_redis_client

logger = logging.getLogger('KEEL_RESEARCH')
TTL_SECONDS = int(os.getenv('RAG_SEARCH_CACHE_TTL_SECONDS', str(24 * 3600)))
LEASE_SECONDS = 120
WAIT_SECONDS = 5


class CacheUnavailable(Exception):
    """A search is pending or its provider outcome needs recovery."""


def cache_key(tenant_id, query, country, limit, provider_config):
    material = {'v': 1, 'tenant': str(tenant_id), 'query': query.strip(),
                'country': (country or '').upper(), 'limit': limit, 'providers': provider_config,
                'mode': 'web', 'tavily_depth': 'basic'}
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return 'keel:rag:search:v1:' + hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _read(client, key):
    try:
        raw = client.get(key)
        parsed = json.loads(raw) if raw is not None else None
        if (not isinstance(parsed, dict) or not isinstance(parsed.get('provider'), str)
                or not isinstance(parsed.get('results'), list)
                or not all(isinstance(row, dict) and all(isinstance(row.get(k), str)
                    for k in ('url', 'title', 'snippet')) for row in parsed['results'])):
            return None
        expires_at = datetime.fromisoformat(parsed['expires_at'])
        if expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
            return None
        return parsed['results']
    except (ValueError, TypeError, KeyError):
        return None


def _claim(conn, tenant, fingerprint, owner):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.rag_search_execution_receipts "
                    "(tenant_id, cache_fingerprint, state, owner_token, lease_expires_at) "
                    "VALUES (%s,%s,'preparing',%s,now()+(%s * interval '1 second')) "
                    "ON CONFLICT (tenant_id,cache_fingerprint) DO NOTHING RETURNING state",
                    (tenant, fingerprint, owner, LEASE_SECONDS))
        if cur.fetchone():
            conn.commit()
            return 'owner', None
        cur.execute("SELECT state, result_json, result_expires_at > now(), lease_expires_at <= now() "
                    "FROM public.rag_search_execution_receipts WHERE tenant_id=%s AND cache_fingerprint=%s FOR UPDATE",
                    (tenant, fingerprint))
        state, result, fresh, stale = cur.fetchone()
        if state == 'succeeded' and fresh:
            conn.commit()
            return 'result', result
        if (state == 'preparing' and stale) or (state == 'succeeded' and not fresh):
            cur.execute("UPDATE public.rag_search_execution_receipts SET state='preparing',owner_token=%s, "
                        "lease_expires_at=now()+(%s * interval '1 second'),provider=NULL,result_json=NULL, "
                        "result_expires_at=NULL,updated_at=now() WHERE tenant_id=%s AND cache_fingerprint=%s",
                        (owner, LEASE_SECONDS, tenant, fingerprint))
            conn.commit()
            return 'owner', None
    conn.commit()
    return 'pending', None


def run(conn, tenant, key, preflight, execute):
    """Only an unexpired preparing owner may durably start provider work.

    A started receipt is never reclaimed automatically, even after Redis loss.
    The result is also stored in the receipt so a Redis eviction cannot turn
    an already successful paid request into a second paid request.
    """
    if TTL_SECONDS <= 0:
        raise CacheUnavailable('invalid search cache TTL')
    client = get_shared_redis_client(socket_connect_timeout=0.5, socket_timeout=1)
    try:
        hit = _read(client, key)
    except Exception:
        hit = None
    if hit is not None:
        logger.info('rag_search_cache_hit')
        return hit
    logger.info('rag_search_cache_miss')
    fingerprint, owner, deadline = key.rsplit(':', 1)[-1], str(uuid.uuid4()), time.monotonic() + WAIT_SECONDS
    while True:
        state, result = _claim(conn, tenant, fingerprint, owner)
        if state == 'result':
            logger.info('rag_search_singleflight_reuse')
            return result
        if state == 'owner':
            break
        if time.monotonic() >= deadline:
            raise CacheUnavailable('search in progress or provider outcome unknown')
        logger.info('rag_search_singleflight_wait')
        time.sleep(0.05)

    try:
        try:
            hit = _read(client, key)
        except Exception:
            hit = None
        if hit is not None:
            with conn.cursor() as cur:
                cur.execute("UPDATE public.rag_search_execution_receipts SET lease_expires_at=now(),updated_at=now() "
                            "WHERE tenant_id=%s AND cache_fingerprint=%s AND state='preparing' AND owner_token=%s",
                            (tenant, fingerprint, owner))
            conn.commit()
            logger.info('rag_search_singleflight_reuse')
            return hit
        preflight()
    except Exception:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("UPDATE public.rag_search_execution_receipts SET lease_expires_at=now(),updated_at=now() "
                        "WHERE tenant_id=%s AND cache_fingerprint=%s AND state='preparing' AND owner_token=%s",
                        (tenant, fingerprint, owner))
        conn.commit()
        raise

    with conn.cursor() as cur:
        cur.execute("UPDATE public.rag_search_execution_receipts SET state='provider_started',lease_expires_at=NULL,updated_at=now() "
                    "WHERE tenant_id=%s AND cache_fingerprint=%s AND state='preparing' AND owner_token=%s "
                    "AND lease_expires_at>now() RETURNING state", (tenant, fingerprint, owner))
        if not cur.fetchone():
            conn.rollback()
            raise CacheUnavailable('search preparation ownership lost')
    conn.commit()
    logger.info('rag_search_provider_execution')
    provider, results = execute()
    with conn.cursor() as cur:
        cur.execute("UPDATE public.rag_search_execution_receipts SET state='succeeded',provider=%s,result_json=%s::jsonb, "
                    "result_expires_at=now()+(%s * interval '1 second'),updated_at=now() "
                    "WHERE tenant_id=%s AND cache_fingerprint=%s AND state='provider_started' AND owner_token=%s RETURNING result_expires_at",
                    (provider, json.dumps(results, ensure_ascii=False), TTL_SECONDS, tenant, fingerprint, owner))
        saved = cur.fetchone()
        if not saved:
            conn.rollback()
            raise CacheUnavailable('search result needs recovery')
    conn.commit()
    try:
        client.setex(key, TTL_SECONDS, json.dumps({'provider': provider, 'results': results,
                                                   'expires_at': saved[0].isoformat()}, ensure_ascii=False))
    except Exception:
        logger.warning('rag_search_result_redis_unavailable')
    return results
