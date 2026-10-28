"""core/tenant_cache.py: per-company isolation, expiry, invalidation on
writes, single-flight under concurrency, and callers never sharing an
object."""
import threading
import time

from src.ai.core import tenant_cache


def _counter():
    calls = []

    def compute(value):
        def _inner():
            calls.append(value)
            return {"value": value, "items": [1, 2]}
        return _inner
    return calls, compute


def test_a_value_is_reused_until_it_expires():
    calls, compute = _counter()
    first = tenant_cache.get_or_compute("ns", "t1", 30, compute("a"), ttl=0.2)
    second = tenant_cache.get_or_compute("ns", "t1", 30, compute("b"), ttl=0.2)
    assert first == second == {"value": "a", "items": [1, 2]} and calls == ["a"]
    time.sleep(0.25)
    assert tenant_cache.get_or_compute("ns", "t1", 30, compute("c"), ttl=0.2)["value"] == "c"


def test_companies_and_keys_never_share_a_value():
    calls, compute = _counter()
    assert tenant_cache.get_or_compute("ns", "t1", 30, compute("t1"), ttl=10)["value"] == "t1"
    assert tenant_cache.get_or_compute("ns", "t2", 30, compute("t2"), ttl=10)["value"] == "t2"
    assert tenant_cache.get_or_compute("ns", "t1", 90, compute("t1-90"), ttl=10)["value"] == "t1-90"
    assert tenant_cache.get_or_compute("other", "t1", 30, compute("other"), ttl=10)["value"] == "other"
    assert calls == ["t1", "t2", "t1-90", "other"]


def test_bump_forgets_only_that_company():
    calls, compute = _counter()
    tenant_cache.get_or_compute("ns", "t1", 30, compute("t1"), ttl=10)
    tenant_cache.get_or_compute("ns", "t2", 30, compute("t2"), ttl=10)
    tenant_cache.bump("t1")
    assert tenant_cache.get_or_compute("ns", "t1", 30, compute("t1-new"), ttl=10)["value"] == "t1-new"
    assert tenant_cache.get_or_compute("ns", "t2", 30, compute("t2-new"), ttl=10)["value"] == "t2"


def test_a_result_computed_across_a_write_is_not_stored():
    """If the company's data changes while the value is being computed,
    the (possibly outdated) result is returned once but not cached."""
    calls = []

    def slow():
        calls.append(1)
        tenant_cache.bump("t1")  # a write lands mid-computation
        return {"value": len(calls)}

    assert tenant_cache.get_or_compute("ns", "t1", 30, slow, ttl=10) == {"value": 1}
    assert tenant_cache.get_or_compute("ns", "t1", 30, lambda: {"value": "fresh"}, ttl=10) == {"value": "fresh"}


def test_concurrent_requests_compute_once():
    calls = []
    gate = threading.Event()

    def compute():
        calls.append(1)
        gate.wait(1)
        return {"value": "shared"}

    results = []
    threads = [threading.Thread(target=lambda: results.append(tenant_cache.get_or_compute("ns", "t1", 30, compute, ttl=10)))
               for _ in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.1)
    gate.set()
    for t in threads:
        t.join()
    assert calls == [1] and results == [{"value": "shared"}] * 8


def test_a_failed_computation_is_not_cached_and_waiters_retry():
    def boom():
        raise RuntimeError("db down")

    try:
        tenant_cache.get_or_compute("ns", "t1", 30, boom, ttl=10)
    except RuntimeError:
        pass
    assert tenant_cache.get_or_compute("ns", "t1", 30, lambda: {"value": "ok"}, ttl=10) == {"value": "ok"}


def test_callers_get_independent_copies():
    first = tenant_cache.get_or_compute("ns", "t1", 30, lambda: {"items": [1]}, ttl=10)
    first["items"].append(99)
    assert tenant_cache.get_or_compute("ns", "t1", 30, lambda: {"items": []}, ttl=10) == {"items": [1]}


def test_ttl_zero_disables_caching():
    calls, compute = _counter()
    tenant_cache.get_or_compute("ns", "t1", 30, compute("a"), ttl=0)
    tenant_cache.get_or_compute("ns", "t1", 30, compute("b"), ttl=0)
    assert calls == ["a", "b"]


class _FakeRedis:
    def __init__(self):
        self.values, self.calls = {}, 0

    def get(self, key):
        self.calls += 1
        return self.values.get(key)

    def incr(self, key):
        self.values[key] = str(int(self.values.get(key, "0")) + 1)

    def expire(self, *_):
        pass


def test_a_write_in_another_api_process_invalidates_this_ones_entry(monkeypatch):
    """With several worker processes, bump() in one must reach the others."""
    shared = _FakeRedis()
    monkeypatch.setattr(tenant_cache, "_shared_store", lambda: shared)
    computed = []
    compute = lambda: computed.append(1) or len(computed)  # noqa: E731
    assert tenant_cache.get_or_compute("ns", "t1", None, compute, ttl=60) == 1
    assert tenant_cache.get_or_compute("ns", "t1", None, compute, ttl=60) == 1  # cached
    shared.incr(tenant_cache.SHARED_KEY_PREFIX + "t1")  # another process's bump()
    assert tenant_cache.get_or_compute("ns", "t1", None, compute, ttl=60) == 2
    assert tenant_cache.get_or_compute("ns", "t2", None, compute, ttl=60) == 3  # other companies unaffected
    shared.incr(tenant_cache.SHARED_KEY_PREFIX + "t1")
    assert tenant_cache.get_or_compute("ns", "t2", None, compute, ttl=60) == 3


def test_without_redis_the_cache_still_works_and_stops_asking_for_a_while(monkeypatch):
    class Down:
        calls = 0

        def get(self, key):
            Down.calls += 1
            raise ConnectionError("refused")

        incr = get

    down = Down()
    monkeypatch.setattr(tenant_cache, "_shared_down_until", 0.0)
    monkeypatch.setattr("src.ai.core.redis_client.get_shared_redis_client", lambda **_: down)
    computed = []
    compute = lambda: computed.append(1) or len(computed)  # noqa: E731
    assert tenant_cache.get_or_compute("ns", "t1", None, compute, ttl=60) == 1
    assert tenant_cache.get_or_compute("ns", "t1", None, compute, ttl=60) == 1
    tenant_cache.bump("t1")  # this process's own invalidation still works
    assert tenant_cache.get_or_compute("ns", "t1", None, compute, ttl=60) == 2
    assert Down.calls == 1  # Redis was asked once, then left alone for SHARED_RETRY_SECONDS
