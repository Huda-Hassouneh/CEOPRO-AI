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
        batches = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
        for _, messages in batches:
            for message_id, payload in messages:
                try:
                    result = analyze_tenant(payload["tenant_id"])
                    client.xack(STREAM, GROUP, message_id)
                    logger.info("analysis %s completed: %s", message_id, result)
                except Exception:
                    logger.exception("analysis %s failed and remains pending", message_id)


if __name__ == "__main__":
    run_forever()
