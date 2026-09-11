"""Consume post-collection events, classify safe reviews, and refresh scores."""

import logging
import os

import redis

from src.ai.db import minio_client
from src.ai.rag.structured_summaries import regenerate_all_structured_summaries
from src.ai.sentiment.pipeline import classify_and_store_reviews
from src.market_scraper import data_access
from src.market_scraper.intelligence import refresh_score_snapshots

STREAM = "market.analysis.requested"
GROUP = "ceopro-market-analysis"
# Same attempt-tracking/dead-letter/reclaim contract as
# src/market_scraper/worker.py::handle_message()/_claimed_messages() - a
# permanently-failing message (a tenant_id that no longer exists, a
# malformed payload) used to sit in this consumer group's PEL forever
# with nothing but a log line, silently dropping that tenant's post-
# scrape sentiment/score/RAG-summary refresh for good.
DEAD_STREAM = os.getenv("ANALYSIS_DEAD_STREAM_KEY", "market.analysis.dead")
MAX_ATTEMPTS = int(os.getenv("ANALYSIS_MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.getenv("ANALYSIS_CLAIM_IDLE_MS", "300000"))
logger = logging.getLogger(__name__)


def analyze_tenant(tenant_id: str) -> dict:
    """
    Runs on every real market.analysis.requested event - i.e. right after
    a scrape job actually persisted new reviews (PostgresPricePipeline.
    spider_closed() only ever publishes this event when self.review_count
    is nonzero). Sentiment classification and score refresh were already
    wired here; structured summary regeneration (rag/structured_
    summaries.py) is the real fix for "run it automatically right after
    scraping" - the same trigger this module already runs on, not a new,
    separate schedule.

    Summary regeneration failing (e.g. MinIO unreachable) is caught and
    logged, never allowed to fail this whole call: sentiment classification
    and score refresh already succeeded by that point and must not be
    retried from scratch (this worker's own run_forever() retries the
    ENTIRE message on any uncaught exception) just because the summary
    step - a real, but lower-priority, downstream step - had a problem.
    """
    conn = data_access.get_tenant_connection(tenant_id)
    try:
        sentiment = classify_and_store_reviews(conn, tenant_id)
        scores = refresh_score_snapshots(conn, tenant_id)

        summaries = None
        try:
            summaries = regenerate_all_structured_summaries(conn, minio_client(), tenant_id)
        except Exception as exc:
            logger.error("structured summary regeneration failed for tenant=%s: %s", tenant_id, exc)

        return {"sentiment": sentiment, "score_count": len(scores), "summaries": summaries}
    finally:
        conn.close()


def _claimed_messages(client, consumer: str):
    """
    Reclaims messages delivered to a PREVIOUS consumer (this process's own
    earlier attempt, or a worker that crashed/restarted) but never acked -
    xreadgroup alone only ever hands out messages no consumer has seen
    yet, so without this a message left pending after a failed
    handle_message() call would sit stuck in this consumer group's PEL
    forever, even across a worker restart. Mirrors
    market_scraper/worker.py::_claimed_messages() exactly.
    """
    try:
        result = client.xautoclaim(STREAM, GROUP, consumer, CLAIM_IDLE_MS, "0-0", count=10)
    except (AttributeError, redis.ResponseError):
        return []
    return result[1] if len(result) > 1 else []


def handle_message(client, message_id: str, payload: dict) -> None:
    """
    Attempt-tracking/dead-letter wrapper around analyze_tenant() - mirrors
    market_scraper/worker.py::handle_message()'s contract. A message that
    fails is retried up to MAX_ATTEMPTS times (left pending each time for
    _claimed_messages() to reclaim on a later loop iteration) before being
    moved to DEAD_STREAM and acked.
    """
    attempts_key = f"{STREAM}:attempts"
    try:
        result = analyze_tenant(payload["tenant_id"])
        client.xack(STREAM, GROUP, message_id)
        client.hdel(attempts_key, message_id)
        logger.info("analysis %s completed: %s", message_id, result)
    except Exception as exc:
        attempts = int(client.hincrby(attempts_key, message_id, 1))
        logger.error("analysis %s failed attempt %s: %s", message_id, attempts, exc)
        if attempts >= MAX_ATTEMPTS:
            client.xadd(DEAD_STREAM, {
                **{key: str(value) for key, value in payload.items()},
                "original_message_id": message_id,
                "attempts": str(attempts),
                "error": str(exc)[:1000],
            })
            client.xack(STREAM, GROUP, message_id)
            client.hdel(attempts_key, message_id)
            logger.error("analysis %s moved to dead-letter stream %s after %s attempts", message_id, DEAD_STREAM, attempts)


def run_forever():
    logging.basicConfig(level=logging.INFO)
    client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    consumer = f"market-analysis-{os.getpid()}"
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    while True:
        messages = _claimed_messages(client, consumer)
        if not messages:
            batches = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
            messages = [message for _, batch in batches for message in batch]
        for message_id, payload in messages:
            handle_message(client, message_id, payload)


if __name__ == "__main__":
    run_forever()
