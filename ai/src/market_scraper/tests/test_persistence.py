from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.market_scraper.persistence import PostgresPricePipeline


class FakeSignals:
    def connect(self, handler, signal):
        self.handler = handler


class FakeConnection:
    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _crawler_with_spider(spider_name="market_source"):
    """A real Scrapy crawler has `.spider` set before process_item() is
    ever called - matches that, since PostgresPricePipeline now reads
    self.crawler.spider.name to record which collector a real scrape cost
    is attributed to (cost_ledger.py)."""
    return SimpleNamespace(signals=FakeSignals(), spider=SimpleNamespace(name=spider_name))


def test_pipeline_persists_mapped_item_and_completes_job(monkeypatch):
    crawler = _crawler_with_spider()
    connection = FakeConnection()
    finished = []
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.get_tenant_connection",
        lambda tenant_id: connection,
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.market_repository.save_market_record",
        lambda conn, item: {
            "status": "PROMOTED", "price_id": "price-1",
            "observation_id": "observation-1", "event_ids": [], "review_ids": [],
        },
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.cost_ledger.record_scrape_cost",
        lambda *args, **kwargs: "cost-1",
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.finish_ingestion_job",
        lambda *args, **kwargs: finished.append((*args, kwargs)),
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.heartbeat_ingestion_job",
        lambda *args: None,
    )
    pipeline = PostgresPricePipeline.from_crawler(crawler)
    item = {"tenant_id": "tenant-1", "job_id": "job-1", "mapping_id": "mapping-1"}

    assert pipeline.process_item(item)["competitor_price_id"] == "price-1"
    spider = SimpleNamespace(
        tenant_id="tenant-1", job_id="job-1", targets=[{"mapping_id": "mapping-1"}]
    )
    pipeline.spider_closed(spider, "finished")

    assert finished[0][3:6] == ("COMPLETED", 1, 0)
    assert connection.closed is True


def test_pipeline_counts_quarantine_without_creating_canonical_price(monkeypatch):
    crawler = _crawler_with_spider()
    connection = FakeConnection()
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.get_tenant_connection",
        lambda tenant_id: connection,
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.market_repository.save_market_record",
        lambda conn, item: {
            "status": "QUARANTINED", "price_id": None, "observation_id": None,
            "event_ids": [], "review_ids": [],
        },
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.cost_ledger.record_scrape_cost",
        lambda *args, **kwargs: "cost-1",
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.heartbeat_ingestion_job",
        lambda *args: None,
    )
    pipeline = PostgresPricePipeline.from_crawler(crawler)
    item = {"tenant_id": "tenant-1", "job_id": "job-1", "mapping_id": "mapping-1"}
    result = pipeline.process_item(item)
    assert "competitor_price_id" not in result
    assert pipeline.quarantined == 1
    assert pipeline.persisted == 0


def test_pipeline_records_real_scrape_cost_for_every_attempt_persisted_or_quarantined(monkeypatch):
    """The real fix this session's cost-margin gate depends on: a scrape
    costs real money whether the item ends up promoted or quarantined -
    the ledger must record both, attributed to the real collector
    (self.crawler.spider.name), not just the successful ones."""
    for status in ("PROMOTED", "QUARANTINED"):
        crawler = _crawler_with_spider(spider_name="digikey_api")
        connection = FakeConnection()
        recorded = []
        monkeypatch.setattr(
            "src.market_scraper.persistence.data_access.get_tenant_connection",
            lambda tenant_id: connection,
        )
        monkeypatch.setattr(
            "src.market_scraper.persistence.market_repository.save_market_record",
            lambda conn, item, status=status: {
                "status": status,
                "price_id": "price-1" if status == "PROMOTED" else None,
                "observation_id": "observation-1" if status == "PROMOTED" else None,
                "event_ids": [], "review_ids": [],
            },
        )
        monkeypatch.setattr(
            "src.market_scraper.persistence.cost_ledger.record_scrape_cost",
            lambda conn, tenant_id, mapping_id, collector_key: recorded.append(
                (tenant_id, mapping_id, collector_key)
            ) or "cost-1",
        )
        monkeypatch.setattr(
            "src.market_scraper.persistence.data_access.heartbeat_ingestion_job",
            lambda *args: None,
        )
        pipeline = PostgresPricePipeline.from_crawler(crawler)
        item = {"tenant_id": "tenant-1", "job_id": "job-1", "mapping_id": "mapping-1"}
        pipeline.process_item(item)

        assert recorded == [("tenant-1", "mapping-1", "digikey_api")]


def test_pipeline_publishes_analysis_event_even_when_job_status_is_failed(monkeypatch):
    """
    The real fix: a job with one failed target among several still
    durably persisted the OTHER targets' reviews before failing - those
    reviews must still get sentiment/score/RAG-summary treatment, not be
    silently stranded just because the overall job status is FAILED.
    """
    crawler = _crawler_with_spider()
    connection = FakeConnection()
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.get_tenant_connection",
        lambda tenant_id: connection,
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.market_repository.save_market_record",
        lambda conn, item: {
            "status": "PROMOTED", "price_id": "price-1",
            "observation_id": "observation-1", "event_ids": [], "review_ids": ["review-1"],
        },
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.cost_ledger.record_scrape_cost",
        lambda *args, **kwargs: "cost-1",
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.finish_ingestion_job",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.heartbeat_ingestion_job",
        lambda *args: None,
    )
    pipeline = PostgresPricePipeline.from_crawler(crawler)
    item = {"tenant_id": "tenant-1", "job_id": "job-1", "mapping_id": "mapping-1"}
    pipeline.process_item(item)
    # Two targets expected, only one succeeded - the job is FAILED overall,
    # but a review was still actually persisted for the one that succeeded.
    spider = SimpleNamespace(
        tenant_id="tenant-1", job_id="job-1",
        targets=[{"mapping_id": "mapping-1"}, {"mapping_id": "mapping-2"}],
    )

    fake_redis = MagicMock()
    with patch("src.market_scraper.persistence.redis.Redis.from_url", return_value=fake_redis):
        pipeline.spider_closed(spider, "finished")

    fake_redis.xadd.assert_called_once_with(
        "market.analysis.requested",
        {"tenant_id": "tenant-1", "job_id": "job-1", "review_count": "1"},
    )


def test_pipeline_does_not_publish_analysis_event_without_any_persisted_reviews(monkeypatch):
    crawler = SimpleNamespace(signals=FakeSignals())
    connection = FakeConnection()
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.get_tenant_connection",
        lambda tenant_id: connection,
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.finish_ingestion_job",
        lambda *args, **kwargs: None,
    )
    pipeline = PostgresPricePipeline.from_crawler(crawler)
    spider = SimpleNamespace(tenant_id="tenant-1", job_id="job-1", targets=[])

    fake_redis = MagicMock()
    with patch("src.market_scraper.persistence.redis.Redis.from_url", return_value=fake_redis):
        pipeline.spider_closed(spider, "finished")

    fake_redis.xadd.assert_not_called()


def test_pipeline_marks_missing_target_as_failed(monkeypatch):
    crawler = SimpleNamespace(signals=FakeSignals())
    connection = FakeConnection()
    finished = []
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.get_tenant_connection",
        lambda tenant_id: connection,
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.finish_ingestion_job",
        lambda *args, **kwargs: finished.append((*args, kwargs)),
    )
    monkeypatch.setattr(
        "src.market_scraper.persistence.data_access.heartbeat_ingestion_job",
        lambda *args: None,
    )
    pipeline = PostgresPricePipeline.from_crawler(crawler)
    spider = SimpleNamespace(
        tenant_id="tenant-1", job_id="job-1", targets=[{"mapping_id": "mapping-1"}]
    )

    pipeline.spider_closed(spider, "finished")

    assert finished[0][3:6] == ("FAILED", 0, 1)
