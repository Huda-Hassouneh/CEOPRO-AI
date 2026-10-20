"""Shared daily YouTube search counters (Redis).

YouTube's free quota is 10,000 units a day, one search costs 100, and the quota resets at midnight
Pacific time, so the counters are keyed by the Pacific date (not UTC). Two counters:

* the scheduled-refresh budget (YOUTUBE_DAILY_SEARCH_BUDGET, default 40) - taken by the weekly refresh only;
* the hard daily cap (YOUTUBE_DAILY_SEARCH_LIMIT, default 90 = 9,000 units) - taken by every search, owner
  Retry included, so no mix of retries and refreshes can use up the key and block everyone.

A Redis outage must not stop collection that would otherwise work, so the cap fails open (and logs).
"""
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

DAILY_SEARCH_LIMIT = int(os.getenv("YOUTUBE_DAILY_SEARCH_LIMIT", "90"))


def quota_day() -> str:
    return f"{datetime.now(ZoneInfo('America/Los_Angeles')):%Y%m%d}"


def take(client, name: str, limit: int) -> bool:
    """Takes one search from today's counter `name`; False once `limit` searches were already taken."""
    key = f"market.comments.{name}:{quota_day()}"
    used = int(client.incr(key))
    client.expire(key, 172800)
    return used <= limit


def take_search(limit: int = None) -> bool:
    """One search against the hard daily cap. True when allowed."""
    import redis
    from src.ai.core.redis_client import get_redis_client

    try:
        return take(get_redis_client(), "searches", DAILY_SEARCH_LIMIT if limit is None else limit)
    except redis.RedisError:
        logger.warning("YouTube search cap unavailable (Redis); allowing this search")
        return True
