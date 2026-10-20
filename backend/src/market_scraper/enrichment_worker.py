"""
Competitor-enrichment worker: consumes market.enrichment.requested and runs
competitor_enrichment on a tenant-scoped connection, so a Retry click or a
"retry all failed" never holds an API request open on slow Google/website calls.

Jobs: one competitor (competitor_id set; optional facets) or a tenant-wide
batch (competitor_id empty; mode "due" or "force", see enrich_tenant_competitors).

It also runs the scheduled sweep: every ENRICHMENT_SWEEP_INTERVAL_SECONDS it
asks the database which tenants have never-attempted competitors or transient
failures due for retry (list_tenants_with_due_enrichment(), a SECURITY DEFINER
function returning tenant ids only - migration 20261017010000) and enqueues one
deduplicated "due" job per tenant. That is what makes quota/provider failures
heal on their own once the cause is gone.

Same attempt-tracking / dead-letter / reclaim contract as discovery_worker.py.
A ValueError (unknown competitor, unsupported facet) is permanent: acked and
logged, not retried. The in-flight dedupe key is released when the job ends.
"""
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import redis

from src.market_scraper import data_access, enrichment_queue, youtube_quota
from src.market_scraper.competitor_enrichment import COMMENTS_REFRESH_DAYS, enrich_competitor, enrich_tenant_comments, enrich_tenant_competitors

STREAM = enrichment_queue.STREAM
GROUP = "ceopro-market-enrichment"
DEAD_STREAM = enrichment_queue.DEAD_STREAM
MAX_ATTEMPTS = int(os.getenv("ENRICHMENT_MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.getenv("ENRICHMENT_CLAIM_IDLE_MS", "300000"))
SWEEP_INTERVAL_SECONDS = int(os.getenv("ENRICHMENT_SWEEP_INTERVAL_SECONDS", "3600"))
logger = logging.getLogger(__name__)

# Same placeholder tenant context connector_worker.py uses for its SECURITY
# DEFINER discovery call: the function ignores tenant context and returns ids only.
_SWEEP_CONTEXT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


# YouTube's free quota is 10,000 units a day and one search costs 100. The scheduled refresh may use this many
# searches a day (default 40 = 4,000 units), leaving the rest for owners pressing Retry.
COMMENTS_DAILY_SEARCH_BUDGET = int(os.getenv("YOUTUBE_DAILY_SEARCH_BUDGET", "40"))


def daily_search_reserve(client, budget: int = COMMENTS_DAILY_SEARCH_BUDGET):
    """A callable that takes one search from today's (Pacific-day) scheduled-refresh budget and says whether one was left."""

    def reserve() -> bool:
        return youtube_quota.take(client, "budget", budget)
    return reserve


def process_job(payload: dict, client=None) -> dict:
    tenant_id = payload["tenant_id"]
    competitor_id = payload.get("competitor_id") or None
    facets = [f for f in (payload.get("facets") or "").split(",") if f] or None
    mode = payload.get("mode") or enrichment_queue.MODE_DUE
    conn = data_access.get_tenant_connection(tenant_id)
    try:
        if mode == enrichment_queue.MODE_COMMENTS:
            if client is None:
                raise ValueError("a comments refresh needs the shared budget counter")
            return enrich_tenant_comments(conn, tenant_id, daily_search_reserve(client))
        if mode == enrichment_queue.MODE_PRICES:
            from src.market_scraper.price_lookup.pipeline import lookup_missing_prices
            return lookup_missing_prices(conn, tenant_id)
        if competitor_id:
            extra = {"deep": True} if payload.get("depth") == "deep" else {}
            return {"results": enrich_competitor(conn, tenant_id, competitor_id, facets=facets, **extra)}
        return enrich_tenant_competitors(conn, tenant_id, mode=mode)
    finally:
        conn.close()


def _release(client, payload: dict) -> None:
    try:
        client.delete(enrichment_queue.inflight_key(
            payload.get("tenant_id", ""), payload.get("competitor_id") or None,
            payload.get("mode") or enrichment_queue.MODE_DUE,
        ))
    except redis.RedisError:
        logger.warning("could not release in-flight marker for %s", payload)


def handle_message(client, message_id: str, payload: dict) -> None:
    attempts_key = f"{STREAM}:attempts"
    try:
        result = process_job(payload, client)
    except ValueError as exc:  # permanent: bad payload / unknown competitor / unsupported facet
        logger.error("enrichment %s rejected, not retrying: %s", message_id, exc)
        client.xack(STREAM, GROUP, message_id)
        client.hdel(attempts_key, message_id)
        _release(client, payload)
        return
    except Exception as exc:  # noqa: BLE001
        attempts = int(client.hincrby(attempts_key, message_id, 1))
        logger.error("enrichment %s failed attempt %s: %s", message_id, attempts, exc)
        if attempts >= MAX_ATTEMPTS:
            client.xadd(DEAD_STREAM, {
                **{key: str(value) for key, value in payload.items()},
                "original_message_id": message_id, "attempts": str(attempts), "error": str(exc)[:1000],
            })
            client.xack(STREAM, GROUP, message_id)
            client.hdel(attempts_key, message_id)
            _release(client, payload)
            logger.error("enrichment %s moved to dead-letter stream %s after %s attempts", message_id, DEAD_STREAM, attempts)
        return
    client.xack(STREAM, GROUP, message_id)
    client.hdel(attempts_key, message_id)
    _release(client, payload)
    logger.info("enrichment %s completed: %s", message_id, result)


def list_tenants_with_due_enrichment() -> list:
    conn = data_access.get_tenant_connection(_SWEEP_CONTEXT_TENANT_ID)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM list_tenants_with_due_enrichment();")
            return [str(row[0]) for row in cursor.fetchall()]
    finally:
        conn.close()


def run_comments_sweep(client) -> dict:
    """Once a day: queue the weekly comments refresh for tenants that have comments gone stale. Never raises."""
    marker = f"market.comments.sweep:{datetime.now(timezone.utc):%Y%m%d}"
    if not os.getenv("YOUTUBE_API_KEY", "").strip() or not os.getenv("EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "").strip():
        return {"skipped": "not_configured"}  # nothing can be collected, so do not queue jobs that would only say so
    try:
        if client.exists(marker):
            return {"skipped": "already_ran_today"}
        conn = data_access.get_tenant_connection(_SWEEP_CONTEXT_TENANT_ID)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM list_tenants_with_due_comments_refresh(%s);", (COMMENTS_REFRESH_DAYS,))
                tenants = [str(row[0]) for row in cursor.fetchall()]
        finally:
            conn.close()
        queued = sum(1 for t in tenants if enrichment_queue.enqueue_enrichment(client, t, mode=enrichment_queue.MODE_COMMENTS))
        client.set(marker, "1", ex=90000)
        return {"tenants_with_stale_comments": len(tenants), "jobs_queued": queued}
    except Exception:  # noqa: BLE001
        logger.exception("comments sweep failed; it will be tried at the next interval")
        return {"error": "comments_sweep_failed"}


def run_sweep(client) -> dict:
    """Enqueues one 'due' job per tenant that has work. Never raises: a failed
    sweep is logged and simply tried again at the next interval."""
    try:
        tenants = list_tenants_with_due_enrichment()
    except Exception:  # noqa: BLE001
        logger.exception("enrichment sweep could not list tenants")
        return {"error": "list_failed"}
    queued = 0
    for tenant_id in tenants:
        try:
            if enrichment_queue.enqueue_enrichment(client, tenant_id, mode=enrichment_queue.MODE_DUE):
                queued += 1
        except redis.RedisError:
            logger.exception("enrichment sweep could not enqueue tenant %s", tenant_id)
    return {"tenants_with_work": len(tenants), "jobs_queued": queued}


def _claimed_messages(client, consumer: str):
    try:
        result = client.xautoclaim(STREAM, GROUP, consumer, CLAIM_IDLE_MS, "0-0", count=10)
    except (AttributeError, redis.ResponseError):
        return []
    return result[1] if len(result) > 1 else []


def run_forever():
    logging.basicConfig(level=logging.INFO)
    client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    consumer = f"market-enrichment-{os.getpid()}"
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    last_sweep: Optional[float] = None
    while True:
        if last_sweep is None or time.monotonic() - last_sweep >= SWEEP_INTERVAL_SECONDS:
            logger.info("enrichment sweep: %s", run_sweep(client))
            logger.info("comments sweep: %s", run_comments_sweep(client))
            last_sweep = time.monotonic()
        messages = _claimed_messages(client, consumer)
        if not messages:
            batches = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
            messages = [message for _, batch in batches for message in batch]
        for message_id, payload in messages:
            handle_message(client, message_id, payload)


if __name__ == "__main__":
    run_forever()
