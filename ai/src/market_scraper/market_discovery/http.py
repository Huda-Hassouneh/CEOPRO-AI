"""HTTP for discovery providers: one identifying User-Agent, timeouts, and a
24-hour Redis cache so repeated runs don't repeat paid or rate-limited calls."""
import hashlib
import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("APEX_MARKET_DISCOVERY")
USER_AGENT = os.getenv(
    "MARKET_RESEARCH_USER_AGENT",
    "KEEL-MarketResearch/1.0 (business intelligence; respects robots.txt and API terms)",
)
CACHE_TTL_SECONDS = int(os.getenv("DISCOVERY_CACHE_TTL_SECONDS", str(24 * 3600)))


def _cache():
    try:
        from src.ai.core.redis_client import get_redis_client

        return get_redis_client()
    except Exception:  # noqa: BLE001 - no Redis: run uncached
        return None


def _key(method: str, url: str, body, params) -> str:
    material = json.dumps([method, url, body, params], sort_keys=True, default=str)
    return "apex:discovery:" + hashlib.sha256(material.encode()).hexdigest()


def request_json(method: str, url: str, *, json_body=None, data=None, params=None, headers=None,
                 timeout: float = 30.0, cache: bool = True, cache_key_extra: Optional[str] = None,
                 cache_if=None):
    """Returns parsed JSON. Raises httpx.HTTPError (incl. status errors).
    cache_if(payload) -> bool keeps an answer that isn't one (a server's
    "timed out" remark) out of the cache."""
    key = _key(method, url, json_body if json_body is not None else data, [params, cache_key_extra]) if cache else None
    client = _cache() if cache else None
    if client is not None:
        try:
            hit = client.get(key)
            if hit:
                return json.loads(hit)
        except Exception:  # noqa: BLE001
            client = None
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}

    def send():
        with httpx.Client(timeout=timeout, follow_redirects=True) as http:
            response = http.request(method, url, json=json_body, data=data, params=params, headers=merged)
            response.raise_for_status()
            return response.json()

    # A cached answer above cost nothing; a real paid call comes out of the
    # company's Data Credits (refused, never sent, when they don't allow it).
    from src.market_scraper.provider_billing import metered_request

    payload = metered_request(url, send, json_body=json_body)
    if client is not None and (cache_if is None or cache_if(payload)):
        try:
            client.setex(key, CACHE_TTL_SECONDS, json.dumps(payload))
        except Exception:  # noqa: BLE001
            pass
    return payload
