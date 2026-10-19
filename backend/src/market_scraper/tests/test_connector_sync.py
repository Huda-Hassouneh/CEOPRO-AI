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
