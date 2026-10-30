from datetime import datetime, timedelta, timezone

from src.market_scraper.connector_sync import DEFAULT_SYNC_INTERVAL_MINUTES, is_due_for_sync


def test_never_synced_is_always_due():
    assert is_due_for_sync(last_synced_at=None, sync_frequency_minutes=15) is True


def test_recently_synced_is_not_due():
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=5)
    assert is_due_for_sync(last, sync_frequency_minutes=15, now=now) is False


def test_overdue_sync_is_due():
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=20)
    assert is_due_for_sync(last, sync_frequency_minutes=15, now=now) is True


def test_exactly_at_the_interval_boundary_is_due():
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=15)
    assert is_due_for_sync(last, sync_frequency_minutes=15, now=now) is True


def test_missing_sync_frequency_falls_back_to_the_module_default():
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    just_under_default = now - timedelta(minutes=DEFAULT_SYNC_INTERVAL_MINUTES - 1)
    over_default = now - timedelta(minutes=DEFAULT_SYNC_INTERVAL_MINUTES + 1)
    assert is_due_for_sync(just_under_default, sync_frequency_minutes=None, now=now) is False
    assert is_due_for_sync(over_default, sync_frequency_minutes=None, now=now) is True

from types import SimpleNamespace

from src.ai.extraction.ingestion_pipeline import job_completion_state


def test_connector_job_is_completed_when_every_row_is_clean():
    summary = SimpleNamespace(rows_partial=0, rows_failed=0)
    assert job_completion_state(summary) == ("COMPLETED", None)


def test_connector_job_fails_when_rows_are_partial_or_fail():
    assert job_completion_state(SimpleNamespace(rows_partial=1, rows_failed=0))[0] == "FAILED"
    assert job_completion_state(SimpleNamespace(rows_partial=0, rows_failed=1))[0] == "FAILED"
    assert job_completion_state(SimpleNamespace(rows_partial=1, rows_failed=1))[0] == "FAILED"

def test_safe_connector_error_never_persists_raw_exception_details():
    from src.market_scraper.connector_sync import safe_connector_error

    error = RuntimeError("request to https://api.example/sales?token=plain-secret failed")
    safe = safe_connector_error(error, "Connector API request")
    assert "RuntimeError" in safe
    assert "plain-secret" not in safe
    assert "api.example" not in safe
