"""Competitor discovery keeps working when Redis is down (free providers),
while priced providers stay fail-closed. The Redis-backed path is unchanged."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.market_scraper import search_safety


@pytest.fixture
def tenant(monkeypatch):
    monkeypatch.setattr(search_safety.credits, "current", lambda: SimpleNamespace(tenant_id="t-1"))
    monkeypatch.setattr(search_safety.credits, "ensure_access", lambda tenant_id: None)
    monkeypatch.setattr(search_safety, "_local", search_safety._LocalLimiter())


@pytest.fixture
def redis_down(monkeypatch):
    def unavailable(**kwargs):
        raise ConnectionError("redis unreachable")
    monkeypatch.setattr(search_safety, "get_shared_redis_client", unavailable)


def test_free_search_still_runs_when_redis_is_down(tenant, redis_down, caplog):
    ran = []
    with search_safety.admission("osm", "search", free=True, request_key="q1"):
        ran.append(True)
    assert ran == [True]
    assert "search_capacity_degraded" in caplog.text


def test_priced_search_stays_fail_closed_when_redis_is_down(tenant, redis_down):
    with pytest.raises(search_safety.SearchCapacityError, match="unavailable"):
        with search_safety.admission("apify", "actor", free=False):
            pytest.fail("a priced call must not run without the shared limiter")


def test_degraded_mode_still_enforces_the_per_minute_limit(tenant, redis_down, monkeypatch):
    monkeypatch.setenv("SEARCH_TENANT_PER_MINUTE", "3")
    for i in range(3):
        with search_safety.admission("osm", "search", free=True, request_key=f"q{i}"):
            pass
    with pytest.raises(search_safety.SearchCapacityError, match="busy"):
        with search_safety.admission("osm", "search", free=True, request_key="q-over"):
            pass


def test_degraded_mode_bounds_concurrency_and_releases_slots(tenant, redis_down, monkeypatch):
    monkeypatch.setenv("SEARCH_TENANT_CONCURRENCY", "1")
    with search_safety.admission("osm", "search", free=True, request_key="a"):
        with pytest.raises(search_safety.SearchCapacityError):
            with search_safety.admission("osm", "search", free=True, request_key="b"):
                pass
    with search_safety.admission("osm", "search", free=True, request_key="b"):
        pass  # the first slot was released


def test_degraded_mode_suppresses_a_concurrent_duplicate(tenant, redis_down):
    with search_safety.admission("osm", "search", free=True, request_key="same"):
        with pytest.raises(search_safety.SearchCapacityError):
            with search_safety.admission("osm", "search", free=True, request_key="same"):
                pass


def test_errors_inside_a_degraded_search_are_not_swallowed(tenant, redis_down):
    with pytest.raises(RuntimeError, match="provider exploded"):
        with search_safety.admission("osm", "search", free=True, request_key="err"):
            raise RuntimeError("provider exploded")
    with search_safety.admission("osm", "search", free=True, request_key="err"):
        pass  # the slot and duplicate key were released after the error


def test_healthy_redis_path_is_unchanged(tenant, monkeypatch):
    client = MagicMock()
    client.eval.return_value = 0
    monkeypatch.setattr(search_safety, "get_shared_redis_client", lambda **kwargs: client)
    local = MagicMock()
    monkeypatch.setattr(search_safety, "_local", local)
    with search_safety.admission("apify", "actor", free=False, request_key="k"):
        pass
    assert client.eval.call_count == 2  # acquire + release through Redis
    local.acquire.assert_not_called()
    local.release.assert_not_called()


def test_redis_refusal_is_still_a_refusal(tenant, monkeypatch):
    client = MagicMock()
    client.eval.return_value = 1
    monkeypatch.setattr(search_safety, "get_shared_redis_client", lambda **kwargs: client)
    with pytest.raises(search_safety.SearchCapacityError, match="busy"):
        with search_safety.admission("osm", "search", free=True):
            pass
