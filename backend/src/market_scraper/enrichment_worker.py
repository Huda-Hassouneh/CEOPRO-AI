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
from typing import Optional

import redis

from src.market_scraper import data_access, enrichment_queue
from src.market_scraper.competitor_enrichment import enrich_competitor, enrich_tenant_competitors

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


def process_job(payload: dict) -> dict:
    tenant_id = payload["tenant_id"]
    competitor_id = payload.get("competitor_id") or None
    facets = [f for f in (payload.get("facets") or "").split(",") if f] or None
    mode = payload.get("mode") or enrichment_queue.MODE_DUE
    conn = data_access.get_tenant_connection(tenant_id)
    try:
        if competitor_id:
            return {"results": enrich_competitor(conn, tenant_id, competitor_id, facets=facets)}
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
        result = process_job(payload)
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
            last_sweep = time.monotonic()
        messages = _claimed_messages(client, consumer)
        if not messages:
            batches = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
            messages = [message for _, batch in batches for message in batch]
        for message_id, payload in messages:
            handle_message(client, message_id, payload)


if __name__ == "__main__":
    run_forever()
