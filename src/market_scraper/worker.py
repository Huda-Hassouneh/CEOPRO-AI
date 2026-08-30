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

logger = logging.getLogger(__name__)
STREAM = os.getenv("SCRAPER_STREAM_KEY", "market.scrape.requested")
DEAD_STREAM = os.getenv("SCRAPER_DEAD_STREAM_KEY", "market.scrape.dead")
GROUP = "ceopro-market-scrapers"
MAX_ATTEMPTS = int(os.getenv("SCRAPER_MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.getenv("SCRAPER_CLAIM_IDLE_MS", "300000"))


def parse_request(payload: dict) -> tuple[str, str]:
    tenant_id = payload.get("tenant_id")
    source_id = payload.get("source_id")
    if not tenant_id or not source_id:
        raise ValueError("tenant_id and source_id are required")
    return tenant_id, source_id


def run_request(payload: dict):
    tenant_id, source_id = parse_request(payload)
    subprocess.run(
        [
            sys.executable, "-m", "src.market_scraper.cli",
            "--tenant-id", tenant_id, "--source-id", source_id,
        ],
        check=True,
    )


def handle_message(client, message_id: str, payload: dict) -> bool:
    """Return True when acknowledged; leave transient failures pending for reclaim."""
    attempts_key = f"{STREAM}:attempts"
    started = time.monotonic()
    try:
        run_request(payload)
        COLLECTIONS.labels("completed").inc()
        COLLECTION_SECONDS.observe(time.monotonic() - started)
        client.xack(STREAM, GROUP, message_id)
        client.hdel(attempts_key, message_id)
        return True
    except (ValueError, subprocess.CalledProcessError) as exc:
        COLLECTIONS.labels("failed").inc()
        COLLECTION_SECONDS.observe(time.monotonic() - started)
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


def _claimed_messages(client, consumer: str):
    try:
        result = client.xautoclaim(STREAM, GROUP, consumer, CLAIM_IDLE_MS, "0-0", count=10)
    except (AttributeError, redis.ResponseError):
        return []
    return result[1] if len(result) > 1 else []


def run_forever():
    logging.basicConfig(level=logging.INFO)
    start_http_server(int(os.getenv("SCRAPER_METRICS_PORT", "9108")))
    client = redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )
    consumer = f"market-scraper-{os.getpid()}"
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info("listening on %s as %s", STREAM, consumer)
    while True:
        try:
            PENDING_MESSAGES.set(client.xpending(STREAM, GROUP).get("pending", 0))
        except redis.RedisError:
            logger.exception("could not update pending-message metric")
        messages = _claimed_messages(client, consumer)
        if not messages:
            batches = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
            messages = [message for _, batch in batches for message in batch]
        for message_id, payload in messages:
            logger.info("processing collection %s payload=%s", message_id, json.dumps(payload))
            handle_message(client, message_id, payload)


if __name__ == "__main__":
    run_forever()
