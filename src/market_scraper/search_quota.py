"""
CEOPRO AI - Daily Google Custom Search Quota Tracking.

The real zero-dollar answer to "the free 100/day quota isn't enough for
a 1k-10k SKU catalog": pace the (bounded, one-time) onboarding job across
days for free, rather than pay for overage or lean on SearXNG as the
primary volume strategy. SearXNG needs a real running instance - self-
hosted, it competes for RAM on the same free-tier box already carrying
Postgres/Redis/Playwright; a public instance risks hammering someone
else's free community resource with a whole catalog's worth of queries,
which many public instances explicitly disable their JSON API to
prevent. It stays wired in as a genuine resilience fallback for a real
Google outage/error - just not the lever for "the quota ran out today,
what now."

This module is that lever: web_product_discovery.py checks has_budget()
before making a real Google call and skips it once today's count hits
the limit (so the account never accidentally exceeds the free tier and
incurs charges neither asked for), and tenant_discovery.py's
skip_already_discovered default means a repeated daily invocation of the
same discovery call naturally makes incremental progress - already-
mapped products are skipped, so the SAME cron-scheduled call each day
just picks up where free budget left off yesterday, with zero new queue/
resume-tracking machinery needed.

Not tenant-scoped (search_quota_usage, migration 20260907020000): the
quota itself is per Google API key, i.e. platform-wide - a tenant-scoped
counter would miss the real shared constraint every other tenant's
discovery calls also draw against.
"""
from datetime import date, timezone
from datetime import datetime as _datetime


def _today() -> date:
    return _datetime.now(timezone.utc).date()


def record_query(conn, count: int = 1) -> None:
    """Call once per real Google Custom Search HTTP request actually
    made - success or failure both count against the real quota, since
    that's how Google's own limit works."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO search_quota_usage (usage_date, query_count)
            VALUES (%s, %s)
            ON CONFLICT (usage_date) DO UPDATE SET query_count = search_quota_usage.query_count + EXCLUDED.query_count;
            """,
            (_today(), count),
        )


def queries_used_today(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT query_count FROM search_quota_usage WHERE usage_date = %s;", (_today(),))
        row = cursor.fetchone()
    return row[0] if row else 0


def has_budget(conn, daily_limit: int = 100) -> bool:
    """True while today's real Google call count is still under
    daily_limit - checked BEFORE a call is attempted, never after, so a
    call that would exceed the free tier is never made at all."""
    return queries_used_today(conn) < daily_limit
