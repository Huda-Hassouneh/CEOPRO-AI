"""An import's forced forecast refresh is never lost behind a running one."""
import threading
import time
from unittest.mock import patch

from src.ai.forecasting import refresh


def _local(monkeypatch):
    monkeypatch.setattr(refresh, "_redis", lambda: None)
    refresh._local_running.clear()
    refresh._local_rerun.clear()
    monkeypatch.setattr(refresh.tenant_cache, "bump", lambda tenant: None)


def test_a_forced_refresh_during_a_running_one_runs_again_afterwards(monkeypatch):
    _local(monkeypatch)
    calls, release_first = [], threading.Event()

    def fake_refresh(tenant, user, product_ids=None, force=False):
        calls.append(force)
        if len(calls) == 1:
            release_first.wait(5)  # still reading sales when the next import finishes
        return {"done": 1, "failed": 0, "total": 1}

    with patch.object(refresh, "refresh_tenant_forecasts", side_effect=fake_refresh):
        assert refresh.start_refresh("t1", "u1") is True          # e.g. a page visit
        assert refresh.start_refresh("t1", "u1", force=True) is False  # import finished meanwhile: queued
        release_first.set()
        for _ in range(100):
            if len(calls) == 2 and not refresh._local_running.get("t1"):
                break
            time.sleep(0.02)
    assert calls == [False, True]
    assert not refresh._local_rerun


def test_an_unforced_refresh_while_busy_is_simply_skipped(monkeypatch):
    _local(monkeypatch)
    calls, release = [], threading.Event()

    def fake_refresh(tenant, user, product_ids=None, force=False):
        calls.append(force)
        release.wait(5)
        return {"done": 1, "failed": 0, "total": 1}

    with patch.object(refresh, "refresh_tenant_forecasts", side_effect=fake_refresh):
        assert refresh.start_refresh("t2", "u1") is True
        assert refresh.start_refresh("t2", "u1") is False
        release.set()
        for _ in range(100):
            if not refresh._local_running.get("t2"):
                break
            time.sleep(0.02)
    time.sleep(0.1)
    assert calls == [False]


def test_forced_refresh_covers_every_product_with_sales(monkeypatch):
    seen = {}

    class Conn:
        def close(self):
            pass

    monkeypatch.setattr(refresh.db, "dedicated_tenant_connection", lambda t, u: Conn())
    monkeypatch.setattr(refresh, "products_with_sales", lambda conn, t: ["a", "b"])
    monkeypatch.setattr(refresh, "products_needing_forecast", lambda conn, t: ["a"])
    monkeypatch.setattr(refresh, "require_forecast_authorization", lambda *a: None)
    monkeypatch.setattr(refresh, "_write_status", lambda *a, **k: None)
    monkeypatch.setattr(refresh, "generate_or_reuse_forecast",
                        lambda conn, t, p, authorization_check=None, force=False: seen.setdefault(p, force))
    monkeypatch.setattr("src.ai.rag.structured_summaries.regenerate_all_structured_summaries", lambda *a: None, raising=False)
    monkeypatch.setattr(refresh.db, "minio_client", lambda: None)
    assert refresh.refresh_tenant_forecasts("t", "u", force=True)["total"] == 2
    assert seen == {"a": True, "b": True}
