"""Error tracking: off without a DSN, and nothing sensitive is ever sent."""
import sentry_sdk
from sentry_sdk.transport import Transport

from src.infrastructure.monitoring import error_tracking


def test_off_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    called = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: called.append(kw))
    assert error_tracking.init_error_tracking("api") is False
    assert called == []


def test_scrub_drops_bodies_cookies_credentials_queries_and_user():
    event = {
        "request": {
            "url": "https://api.example/reports/sales/export?token=abc",
            "data": {"password": "hunter2"},
            "cookies": {"session": "x"},
            "query_string": "token=abc",
            "headers": {"Authorization": "Bearer secret", "X-Api-Key": "k", "User-Agent": "Mozilla", "Accept-Language": "ar"},
        },
        "user": {"email": "owner@example.com"},
    }
    scrubbed = error_tracking.scrub_event(event)
    assert scrubbed["request"]["url"] == "https://api.example/reports/sales/export"
    assert "data" not in scrubbed["request"] and "cookies" not in scrubbed["request"]
    assert "query_string" not in scrubbed["request"]
    assert scrubbed["request"]["headers"] == {"User-Agent": "Mozilla", "Accept-Language": "ar"}
    assert "user" not in scrubbed


class _Capture(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


def test_a_real_exception_is_reported_scrubbed_and_tagged(monkeypatch):
    transport = _Capture()
    real_init = sentry_sdk.init
    monkeypatch.setenv("SENTRY_DSN", "https://public@o0.ingest.sentry.io/0")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: real_init(transport=transport, **kw))
    try:
        assert error_tracking.init_error_tracking("worker-discovery") is True
        try:
            raise ValueError("boom")
        except ValueError:
            sentry_sdk.capture_exception()
        sentry_sdk.flush()
        assert len(transport.events) == 1
        event = transport.events[0]
        assert event["tags"]["service"] == "worker-discovery"
        assert event["environment"] == "test"
        assert event["exception"]["values"][0]["value"] == "boom"
        assert "user" not in event
    finally:
        sentry_sdk.get_client().close()
        # Back to a disabled client for the rest of the run. init() reads
        # SENTRY_DSN from the environment when no DSN is passed, so the test
        # DSN must be gone first, or a live client would leak into later tests.
        monkeypatch.delenv("SENTRY_DSN")
        real_init()
        assert sentry_sdk.get_client().dsn is None and sentry_sdk.get_client().transport is None
