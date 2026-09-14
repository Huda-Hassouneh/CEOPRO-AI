"""Scrapy pipeline that persists mapped observations and closes job ledgers."""

import logging
import os

import redis
from scrapy import signals

from src.market_scraper import data_access, market_repository

logger = logging.getLogger(__name__)


class PostgresPricePipeline:
    def __init__(self, crawler):
        self.crawler = crawler
        self.connection = None
        self.persisted = 0
        self.failed = 0
        self.review_count = 0
        self.quarantined = 0
        self.last_error = None

    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls(crawler)
        crawler.signals.connect(pipeline.spider_closed, signal=signals.spider_closed)
        return pipeline

    def process_item(self, item):
        if not item.get("mapping_id"):
            return item
        try:
            if self.connection is None:
                self.connection = data_access.get_tenant_connection(item["tenant_id"])
            persisted = market_repository.save_market_record(self.connection, item)
            if persisted["status"] == "QUARANTINED":
                self.quarantined += 1
            else:
                item["competitor_price_id"] = persisted["price_id"]
                item["observation_id"] = persisted["observation_id"]
                item["market_event_ids"] = persisted["event_ids"]
                item["review_ids"] = persisted["review_ids"]
                self.review_count += len(persisted["review_ids"])
                self.persisted += 1
            data_access.heartbeat_ingestion_job(
                self.connection, item["tenant_id"], item["job_id"]
            )
        except Exception as exc:
            self.failed += 1
            self.last_error = str(exc)
            if self.connection:
                self.connection.rollback()
            raise
        return item

    def spider_closed(self, spider, reason):
        if not getattr(spider, "job_id", None):
            return
        if self.connection is None:
            self.connection = data_access.get_tenant_connection(spider.tenant_id)
        expected = len(getattr(spider, "targets", []))
        self.failed += max(0, expected - self.persisted - self.quarantined - self.failed)
        status = "COMPLETED" if reason == "finished" and self.failed == 0 else "FAILED"
        data_access.finish_ingestion_job(
            self.connection,
            spider.tenant_id,
            spider.job_id,
            status,
            self.persisted,
            self.failed,
            self.last_error or (None if status == "COMPLETED" else reason),
            quarantined=self.quarantined,
        )
        self.connection.close()
        if self.review_count:
            # Fire whenever real reviews were actually persisted, regardless
            # of the job's overall status - a job with one failed target
            # among several still durably wrote the other targets' reviews,
            # and those already-persisted reviews deserve sentiment
            # classification, a score refresh, and RAG summary regeneration
            # the same as any other. Gating this on status == "COMPLETED"
            # silently stranded that data: it stayed in Postgres forever with
            # no sentiment score and no way to reach the RAG chatbot unless
            # someone manually called POST /sentiment/analyze-pending.
            try:
                redis.Redis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
                ).xadd("market.analysis.requested", {
                    "tenant_id": spider.tenant_id,
                    "job_id": spider.job_id,
                    "review_count": str(self.review_count),
                })
            except redis.RedisError as exc:
                logger.error("could not enqueue downstream market analysis: %s", exc)
        logger.info("scrape job %s closed as %s", spider.job_id, status)
