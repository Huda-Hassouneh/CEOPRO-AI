"""Periodic stale-job recovery and privacy-retention enforcement."""

import logging
import os
import time

import psycopg2
from prometheus_client import start_http_server

from src.market_scraper.metrics import RETENTION_RUNS, STALE_RECOVERED

logger = logging.getLogger(__name__)


def run_once(database_url: str, stale_minutes: int = 30) -> dict:
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT recover_stale_market_jobs(%s);", (stale_minutes,))
            recovered = int(cursor.fetchone()[0])
            cursor.execute("SELECT * FROM enforce_market_retention();")
            staging_deleted, observations_redacted, reviews_anonymized = cursor.fetchone()
        connection.commit()
        STALE_RECOVERED.inc(recovered)
        RETENTION_RUNS.labels("completed").inc()
        return {
            "stale_jobs_recovered": recovered,
            "staging_deleted": staging_deleted,
            "observations_redacted": observations_redacted,
            "reviews_anonymized": reviews_anonymized,
        }
    except Exception:
        connection.rollback()
        RETENTION_RUNS.labels("failed").inc()
        raise
    finally:
        connection.close()


def run_forever():
    logging.basicConfig(level=logging.INFO)
    database_url = os.getenv("SCRAPER_DATABASE_URL")
    if not database_url:
        raise RuntimeError("SCRAPER_DATABASE_URL must be set")
    stale_minutes = int(os.getenv("SCRAPER_STALE_JOB_MINUTES", "30"))
    interval = int(os.getenv("SCRAPER_MAINTENANCE_INTERVAL_SECONDS", "300"))
    start_http_server(int(os.getenv("SCRAPER_MAINTENANCE_METRICS_PORT", "9109")))
    while True:
        try:
            logger.info("market maintenance result: %s", run_once(database_url, stale_minutes))
        except Exception:
            logger.exception("market maintenance run failed")
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
