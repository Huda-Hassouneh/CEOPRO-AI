"""Reliable Redis Streams worker for reviewed market-collection jobs."""

import json
import logging
import os
import subprocess
import sys
import time

import redis
from prometheus_client import start_http_server

from src.market_scraper.metrics import (
    COLLECTION_SECONDS, COLLECTIONS, DEAD_LETTERS, PENDING_MESSAGES,
)
from src.ai.core import operation_receipts
from src.market_scraper import data_access

logger = logging.getLogger(__name__)
STREAM = os.getenv("SCRAPER_RECEIPT_STREAM_KEY", "market.scrape.receipt.v1")
LEGACY_STREAM = os.getenv("SCRAPER_STREAM_KEY", "market.scrape.requested")
DEAD_STREAM = os.getenv("SCRAPER_DEAD_STREAM_KEY", "market.scrape.dead")
GROUP = "ceopro-market-scrapers"
MAX_ATTEMPTS = int(os.getenv("SCRAPER_MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.getenv("SCRAPER_CLAIM_IDLE_MS", "300000"))


def parse_request(payload: dict) -> tuple[str, str, str]:
    tenant_id = payload.get("tenant_id")
    source_id = payload.get("source_id")
    receipt_id = payload.get("receipt_id")
    if not tenant_id or not source_id or not receipt_id:
        raise ValueError("tenant_id, source_id, and receipt_id are required")
    return tenant_id, source_id, receipt_id


def run_request(payload: dict):
    tenant_id, source_id, receipt_id = parse_request(payload)
    subprocess.run(
        [
            sys.executable, "-m", "src.market_scraper.cli",
            "--tenant-id", tenant_id, "--source-id", source_id, "--receipt-id", receipt_id,
        ],
        check=True,
    )


def handle_message(client, message_id: str, payload: dict) -> bool:
    """Return True when acknowledged; leave transient failures pending for reclaim."""
    attempts_key = f"{STREAM}:attempts"
    started = time.monotonic()
    try:
        if STREAM == LEGACY_STREAM:
            raise RuntimeError("receipt stream must be distinct from the legacy collection stream")
        run_request(payload)
        COLLECTIONS.labels("completed").inc()
        COLLECTION_SECONDS.observe(time.monotonic() - started)
        client.xack(STREAM, GROUP, message_id)
        client.hdel(attempts_key, message_id)
        return True
    except (ValueError, subprocess.CalledProcessError) as exc:
        COLLECTIONS.labels("failed").inc()
        COLLECTION_SECONDS.observe(time.monotonic() - started)
        if isinstance(exc, subprocess.CalledProcessError):
            try:
                terminal = _receipt_is_terminal(payload)
            except Exception:
                terminal = False  # cannot verify receipt state: leave pending and fail closed
            if terminal:
                client.xack(STREAM, GROUP, message_id)
                client.hdel(attempts_key, message_id)
                return True
        attempts = int(client.hincrby(attempts_key, message_id, 1))
        logger.error("collection %s failed attempt %s: %s", message_id, attempts, exc)
        if attempts >= MAX_ATTEMPTS:
            DEAD_LETTERS.inc()
            client.xadd(DEAD_STREAM, {
                **{key: str(value) for key, value in payload.items()},
                "original_message_id": message_id,
                "attempts": str(attempts),
                "error": str(exc)[:1000],
            })
            client.xack(STREAM, GROUP, message_id)
            client.hdel(attempts_key, message_id)
            return True
        return False


def _receipt_is_terminal(payload: dict) -> bool:
    tenant_id, _source_id, receipt_id = parse_request(payload)
    conn = data_access.get_tenant_connection(tenant_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT state FROM public.keel_operation_receipts "
                "WHERE tenant_id=%s::uuid AND receipt_id=%s::uuid;",
                (tenant_id, receipt_id),
            )
            row = cursor.fetchone()
        return bool(row and row[0] in {"completed", "denied", "failed", "reconciliation_required"})
    finally:
        conn.close()


def _claimed_messages(client, consumer: str):
    try:
        result = client.xautoclaim(STREAM, GROUP, consumer, CLAIM_IDLE_MS, "0-0", count=10)
    except (AttributeError, redis.ResponseError):
        return []
    return result[1] if len(result) > 1 else []


_DISCOVERY_CONTEXT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def dispatch_pending_receipts(client) -> int:
    """Recover DB-committed outbox entries whose Redis signal was lost."""
    discovery = data_access.get_tenant_connection(_DISCOVERY_CONTEXT_TENANT_ID)
    try:
        with discovery.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id FROM public.list_tenants_with_pending_operation_receipts() "
                "UNION SELECT tenant_id FROM public.list_tenants_with_expired_operation_receipts();"
            )
            tenant_ids = [str(row[0]) for row in cursor.fetchall()]
    finally:
        discovery.close()
    dispatched = 0
    for tenant_id in tenant_ids:
        conn = data_access.get_tenant_connection(tenant_id)
        try:
            operation_receipts.recover_expired(conn, tenant_id)
            pending = operation_receipts.dispatch_pending(conn, tenant_id)
            for receipt in pending:
                client.xadd(STREAM, {"tenant_id": tenant_id, **receipt})
                operation_receipts.mark_queued(conn, tenant_id, receipt["receipt_id"])
                dispatched += 1
        finally:
            conn.close()
    return dispatched


def run_forever():
    logging.basicConfig(level=logging.INFO)
    start_http_server(int(os.getenv("SCRAPER_METRICS_PORT", "9108")))
    client = redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )
    if STREAM == LEGACY_STREAM:
        raise RuntimeError("receipt stream must be distinct from the legacy collection stream")
    consumer = f"market-scraper-{os.getpid()}"
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info("listening on %s as %s", STREAM, consumer)
    while True:
        try:
            dispatch_pending_receipts(client)
            PENDING_MESSAGES.set(client.xpending(STREAM, GROUP).get("pending", 0))
        except redis.RedisError:
            logger.exception("could not update pending-message metric")
        except Exception:
            logger.exception("receipt outbox recovery failed; no receipt was acknowledged")
        messages = _claimed_messages(client, consumer)
        if not messages:
            batches = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
            messages = [message for _, batch in batches for message in batch]
        for message_id, payload in messages:
            logger.info("processing collection %s payload=%s", message_id, json.dumps(payload))
            handle_message(client, message_id, payload)


if __name__ == "__main__":
    from src.infrastructure.monitoring.error_tracking import init_error_tracking

    init_error_tracking("worker-prices")
    run_forever()
