"""
CEOPRO AI - Web-Search Result Cache.

Real fix for the real multi-tenant scaling problem: Google Custom
Search's free tier is 100 queries/DAY, shared across the whole platform,
not per-tenant. Two tenants selling the same product (or one tenant
re-running discovery) previously hit the live API twice for the exact
same search - a straightforward, avoidable waste of a hard-capped daily
budget. This is a plain Postgres-backed cache (web_search_cache,
migration 20260907010000) keyed on the exact query string, since two
identical query strings will always get the same real answer from
Google's index within a reasonable window - not tenant-scoped on
purpose (see the migration's own comment: this is public search-index
metadata, not tenant data, so sharing the cache across tenants is
exactly the point).

Never fabricates a result: a cache miss returns None, exactly like a
missing API key or a failed call already does elsewhere in this
package - callers fall through to a real live call (or the next
fallback) on a miss, never synthesize a result from a stale/absent
cache entry.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.market_scraper.discovery import CandidateSource

DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days - retail search results don't churn hourly


def get_cached(conn, cache_key: str) -> Optional[List[CandidateSource]]:
    """None on a miss (not found, or found but expired) - never a stale
    result silently served past its own expiry."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT results_json FROM web_search_cache WHERE cache_key = %s AND expires_at > NOW();",
            (cache_key,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return [CandidateSource(**item) for item in row[0]]


def set_cached(conn, cache_key: str, candidates: List[CandidateSource], ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    results_json = json.dumps([
        {"product_name": c.product_name, "url": c.url, "title": c.title} for c in candidates
    ])
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO web_search_cache (cache_key, results_json, expires_at)
            VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (cache_key) DO UPDATE SET
                results_json = EXCLUDED.results_json, cached_at = NOW(), expires_at = EXCLUDED.expires_at;
            """,
            (cache_key, results_json, expires_at),
        )


def build_cache_key(source: str, query: str) -> str:
    """`source` distinguishes which discovery function/vendor produced
    this query (e.g. "google_cse", "searxng") so a cache entry from one
    backend is never mistakenly served to a different one, even if the
    underlying query text happens to match."""
    return f"{source}:{query}"
