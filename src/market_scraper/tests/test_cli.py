from types import SimpleNamespace

from src.market_scraper import cli


SOURCE = {
    "source_name": "Example", "source_url": "https://shop.example",
    "collection_method": "STRUCTURED_DATA", "policy_status": "ALLOWED",
    "approval_reference": "SEC-123", "approved_at": object(),
    "privacy_reviewed_at": object(), "rate_limit_per_minute": 10,
    "render_javascript": False, "collector_config": {}, "collector_key": "standards",
}
TARGET = {"product_url": "https://shop.example/product", "mapping_id": "mapping-1"}


class Connection:
    def close(self):
        pass


class Settings:
    def set(self, *args, **kwargs):
        pass


class Process:
    def __init__(self, settings):
        pass

    def crawl(self, *args, **kwargs):
        pass

    def start(self):
        pass


def arrange(monkeypatch, status):
    monkeypatch.setattr(cli.data_access, "get_tenant_connection", lambda tenant: Connection())
    monkeypatch.setattr(cli.data_access, "recover_stale_ingestion_jobs", lambda *args: [])
    monkeypatch.setattr(cli.data_access, "load_source", lambda *args: SOURCE)
    monkeypatch.setattr(cli.data_access, "load_scrape_targets", lambda *args: [TARGET])
    monkeypatch.setattr(cli.data_access, "create_ingestion_job", lambda *args: "job-1")
    monkeypatch.setattr(cli.data_access, "load_ingestion_job_status", lambda *args: status)
    monkeypatch.setattr(cli, "resolve_public_addresses", lambda url: {"93.184.216.34"})
    monkeypatch.setattr(cli, "resolve_collector", lambda source: SimpleNamespace(
        requires_targets=True, spider=SimpleNamespace(name="market_source")
    ))
    monkeypatch.setattr(cli, "get_project_settings", lambda: Settings())
    monkeypatch.setattr(cli, "CrawlerProcess", Process)


def test_cli_returns_nonzero_when_scrapy_job_finished_failed(monkeypatch):
    arrange(monkeypatch, "FAILED")
    assert cli.run_collection("tenant-1", "source-1") == 1


def test_cli_returns_zero_only_for_completed_job(monkeypatch):
    arrange(monkeypatch, "COMPLETED")
    assert cli.run_collection("tenant-1", "source-1") == 0


def test_cli_finalizes_job_that_crawler_left_processing(monkeypatch):
    arrange(monkeypatch, "PROCESSING")
    finished = []
    monkeypatch.setattr(cli.data_access, "finish_ingestion_job", lambda *args: finished.append(args))
    assert cli.run_collection("tenant-1", "source-1") == 1
    assert finished[0][3] == "FAILED"
