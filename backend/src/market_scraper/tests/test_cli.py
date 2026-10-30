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
    receipt = {
        "receipt_id": "receipt-1", "tenant_id": "tenant-1", "source_id": "source-1",
        "actor_user_id": "actor-1", "principal_kind": "service", "period_start": "2026-10-01",
        "worker_id": "worker-1", "lease_generation": 1, "lease_seconds": 1800,
    }
    monkeypatch.setattr(cli.data_access, "get_tenant_connection", lambda tenant: Connection())
    monkeypatch.setattr(cli.operation_receipts, "recover_expired", lambda *args: {})
    monkeypatch.setattr(cli.operation_receipts, "claim", lambda *args: dict(receipt))
    monkeypatch.setattr(cli.operation_receipts, "begin_provider", lambda *args: None)
    monkeypatch.setattr(cli.operation_receipts, "finish", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.data_access, "load_source", lambda *args: SOURCE)
    monkeypatch.setattr(cli.data_access, "load_scrape_targets", lambda *args: [TARGET])
    monkeypatch.setattr(cli.data_access, "create_ingestion_job", lambda *args, **kwargs: "job-1")
    monkeypatch.setattr(cli.data_access, "load_ingestion_job_status", lambda *args: status)
    monkeypatch.setattr(cli, "resolve_public_addresses", lambda url: {"93.184.216.34"})
    monkeypatch.setattr(cli, "resolve_collector", lambda source: SimpleNamespace(
        requires_targets=True, spider=SimpleNamespace(name="market_source")
    ))
    monkeypatch.setattr(cli, "get_project_settings", lambda: Settings())
    monkeypatch.setattr(cli, "CrawlerProcess", Process)


def test_cli_returns_nonzero_when_scrapy_job_finished_failed(monkeypatch):
    arrange(monkeypatch, "FAILED")
    assert cli.run_collection("tenant-1", "source-1", "receipt-1") == 1


def test_cli_returns_zero_only_for_completed_job(monkeypatch):
    arrange(monkeypatch, "COMPLETED")
    assert cli.run_collection("tenant-1", "source-1", "receipt-1") == 0


def test_cli_finalizes_job_that_crawler_left_processing(monkeypatch):
    arrange(monkeypatch, "PROCESSING")
    finished = []
    monkeypatch.setattr(cli.data_access, "finish_ingestion_job", lambda *args, **kwargs: finished.append((args, kwargs)))
    assert cli.run_collection("tenant-1", "source-1", "receipt-1") == 1
    assert finished[0][0][3] == "FAILED"
    assert finished[0][1]["receipt"] is not None


def test_cli_no_target_completion_is_fenced(monkeypatch):
    arrange(monkeypatch, "COMPLETED")
    monkeypatch.setattr(cli.data_access, "load_scrape_targets", lambda *args: [])
    finished = []
    monkeypatch.setattr(
        cli.data_access, "finish_ingestion_job",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )
    assert cli.run_collection("tenant-1", "source-1", "receipt-1") == 0
    assert finished[0][1]["receipt"] is not None
    assert finished[0][1]["receipt_allow_pre_provider"] is True


def test_cli_marks_provider_exception_uncertain_and_never_retryable(monkeypatch):
    arrange(monkeypatch, "FAILED")
    transitions = []
    job_finishes = []
    monkeypatch.setattr(
        cli, "CrawlerProcess",
        lambda settings: SimpleNamespace(
            crawl=lambda *args, **kwargs: None,
            start=lambda: (_ for _ in ()).throw(RuntimeError("provider outcome unknown")),
        ),
    )
    monkeypatch.setattr(
        cli.data_access, "finish_ingestion_job",
        lambda *args, **kwargs: job_finishes.append((args, kwargs)),
    )
    monkeypatch.setattr(
        cli.operation_receipts, "finish",
        lambda conn, receipt, state, error=None: transitions.append((state, error)),
    )

    assert cli.run_collection("tenant-1", "source-1", "receipt-1") == 1
    assert job_finishes[0][1]["receipt"] is not None
    assert transitions == [("reconciliation_required", "PROVIDER_OUTCOME_UNKNOWN")]
