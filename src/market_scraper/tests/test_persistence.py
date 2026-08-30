from types import SimpleNamespace

from src.market_scraper.persistence import PostgresPricePipeline


class FakeSignals:
    def connect(self, handler, signal):
        self.handler = handler


class FakeConnection:
    def rollback(self):
        pass

    def close(self):
        self.closed = True


def test_pipeline_persists_mapped_item_and_completes_job(monkeypatch):
    crawler = SimpleNamespace(signals=FakeSignals())
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
    crawler = SimpleNamespace(signals=FakeSignals())
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
        "src.market_scraper.persistence.data_access.heartbeat_ingestion_job",
        lambda *args: None,
    )
    pipeline = PostgresPricePipeline.from_crawler(crawler)
    item = {"tenant_id": "tenant-1", "job_id": "job-1", "mapping_id": "mapping-1"}
    result = pipeline.process_item(item)
    assert "competitor_price_id" not in result
    assert pipeline.quarantined == 1
    assert pipeline.persisted == 0


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
