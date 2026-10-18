"""P2 (QA_TEST_STRATEGY.md): infrastructure watchdog alerting. All I/O mocked."""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.monitoring.watchdog import InfrastructureWatchdog


@pytest.fixture
def wd(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    return InfrastructureWatchdog()


def test_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        InfrastructureWatchdog()


def _db(total, failed):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (total, failed)
    return conn


def test_error_rate_above_threshold_alerts(wd):
    with patch("psycopg2.connect", return_value=_db(100, 6)), patch.object(wd, "_dispatch_alert") as alert:
        wd._audit_postgres()
    assert alert.call_args.args[:2] == ("PostgreSQL-Ingestion", "ERROR_RATE_EXCEEDED")


@pytest.mark.parametrize("total,failed", [(100, 5), (100, 0), (0, 0)])
def test_error_rate_at_or_below_threshold_does_not_alert(wd, total, failed):
    with patch("psycopg2.connect", return_value=_db(total, failed)), patch.object(wd, "_dispatch_alert") as alert:
        wd._audit_postgres()
    alert.assert_not_called()


def test_database_down_raises_connection_lost_alert(wd):
    with patch("psycopg2.connect", side_effect=Exception("refused")), patch.object(wd, "_dispatch_alert") as alert:
        wd._audit_postgres()
    assert alert.call_args.args[:2] == ("PostgreSQL", "CONNECTION_LOST")


def test_redis_backlog_over_limit_alerts(wd):
    with patch("redis.Redis") as r, patch.object(wd, "_dispatch_alert") as alert:
        r.return_value.ping.return_value = True
        r.return_value.xlen.return_value = 10001
        wd._audit_redis()
    assert alert.call_args.args[:2] == ("Redis-Pipeline", "STREAM_BACKLOG_OVERFLOW")


def test_redis_healthy_does_not_alert(wd):
    with patch("redis.Redis") as r, patch.object(wd, "_dispatch_alert") as alert:
        r.return_value.ping.return_value = True
        r.return_value.xlen.return_value = 10000
        wd._audit_redis()
    alert.assert_not_called()


def test_redis_down_raises_connection_lost_alert(wd):
    with patch("redis.Redis", side_effect=Exception("down")), patch.object(wd, "_dispatch_alert") as alert:
        wd._audit_redis()
    assert alert.call_args.args[:2] == ("Redis", "CONNECTION_LOST")


def test_alert_without_webhook_makes_no_network_call(wd):
    with patch("urllib.request.urlopen") as urlopen:
        wd._dispatch_alert("c", "t", "d")
    urlopen.assert_not_called()


def test_alert_posts_json_to_the_webhook(wd):
    wd.webhook_url = "https://hooks.example/x"
    with patch("urllib.request.urlopen") as urlopen:
        wd._dispatch_alert("Redis", "CONNECTION_LOST", "boom")
    req = urlopen.call_args.args[0]
    assert req.full_url == "https://hooks.example/x" and req.get_method() == "POST"
    assert "boom" in json.loads(req.data)["text"]


def test_webhook_failure_never_raises(wd):
    wd.webhook_url = "https://hooks.example/x"
    with patch("urllib.request.urlopen", side_effect=OSError("net")):
        wd._dispatch_alert("c", "t", "d")  # must not raise
