"""Consume post-collection events, classify safe reviews, and refresh scores."""

import logging
import os

import redis

from src.ai.sentiment.pipeline import classify_and_store_reviews
from src.market_scraper import data_access
from src.market_scraper.intelligence import refresh_score_snapshots

STREAM = "market.analysis.requested"
GROUP = "ceopro-market-analysis"
logger = logging.getLogger(__name__)


def analyze_tenant(tenant_id: str) -> dict:
    conn = data_access.get_tenant_connection(tenant_id)
    try:
        sentiment = classify_and_store_reviews(conn, tenant_id)
        scores = refresh_score_snapshots(conn, tenant_id)
        return {"sentiment": sentiment, "score_count": len(scores)}
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
