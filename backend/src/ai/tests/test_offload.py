"""Heavy work offloaded to the processor (src/offload): signed requests, one run per identical
task, a crashing task failing only itself, a full processor saying so, and the API side
retrying, giving up in time and falling back."""
import os
import time

os.environ["OFFLOAD_ENABLE_TEST_TASKS"] = "1"  # before src.offload.tasks is imported (and its fork server preloads it)

import httpx
import pytest
from fastapi.testclient import TestClient

from src.offload import client as offload_client
from src.offload import protocol, tasks
from src.offload.processor import create_app

SECRET = "s" * 40
tasks.TASKS.setdefault("test.sleep", tasks._sleep_task)


def _signed(method, path, body=b""):
    return protocol.sign(SECRET, method, path, body)


def _submit(client, kind, params):
    body = protocol.canonical({"kind": kind, "params": params})
    return client.post("/v1/jobs", content=body, headers={**_signed("POST", "/v1/jobs", body), "Content-Type": "application/json"})


def _status(client, job_id):
    path = f"/v1/jobs/{job_id}"
    return client.get(path, headers=_signed("GET", path))


def _wait(client, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        body = _status(client, job_id).json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.fixture
def processor():
    with TestClient(create_app(SECRET, max_parallel=2, max_queue=2, job_timeout=10)) as client:
        yield client


# --- protocol ---------------------------------------------------------------

def test_a_signature_is_bound_to_the_secret_the_request_and_the_time():
    headers = protocol.sign(SECRET, "POST", "/v1/jobs", b"{}", now=1_000_000)
    ts, sig = headers[protocol.TIMESTAMP_HEADER], headers[protocol.SIGNATURE_HEADER]
    assert protocol.verify(SECRET, "POST", "/v1/jobs", b"{}", ts, sig, now=1_000_010)
    assert not protocol.verify("x" * 40, "POST", "/v1/jobs", b"{}", ts, sig, now=1_000_010)
    assert not protocol.verify(SECRET, "POST", "/v1/jobs", b'{"a":1}', ts, sig, now=1_000_010)
    assert not protocol.verify(SECRET, "GET", "/v1/jobs", b"{}", ts, sig, now=1_000_010)
    assert not protocol.verify(SECRET, "POST", "/v1/jobs", b"{}", ts, sig, now=1_000_000 + 301)  # replayed later
    assert not protocol.verify(SECRET, "POST", "/v1/jobs", b"{}", None, sig)


def test_the_same_task_always_gets_the_same_job_id():
    assert protocol.job_key("k", {"a": 1, "b": [1, 2]}) == protocol.job_key("k", {"b": [1, 2], "a": 1})
    assert protocol.job_key("k", {"a": 1}) != protocol.job_key("k", {"a": 2})


def test_only_place_and_trade_words_leave_the_api():
    from src.market_scraper.market_discovery.models import DiscoveryQuery

    query = DiscoveryQuery(tenant_id="tenant-secret", industry_key="cafe", industry_label="Cafe", keywords=["cafe"],
                           latitude=31.953912345, longitude=35.910612345, own_name="Our Cafe", own_website="https://ours.jo",
                           osm_tags=(("amenity", "cafe"),))
    params = tasks.overture_params(query)
    assert "tenant_id" not in params and "own_name" not in params and "own_website" not in params
    assert params["latitude"] == 31.95391 and params["osm_tags"] == [["amenity", "cafe"]]
    rebuilt = tasks.overture_query(params)
    assert rebuilt.osm_tags == (("amenity", "cafe"),) and rebuilt.keywords == ["cafe"] and rebuilt.tenant_id == "offload"


# --- processor --------------------------------------------------------------

def test_the_processor_refuses_unsigned_and_wrongly_signed_requests(processor):
    body = protocol.canonical({"kind": "test.sleep", "params": {}})
    assert processor.post("/v1/jobs", content=body).status_code == 401
    bad = protocol.sign("y" * 40, "POST", "/v1/jobs", body)
    assert processor.post("/v1/jobs", content=body, headers=bad).status_code == 401
    assert processor.get("/healthz").json()["ok"] is True  # uptime checks need no secret


def test_an_oversized_body_is_refused_before_it_is_read_or_verified(processor):
    from src.offload import processor as processor_module

    big = b"x" * (processor_module.MAX_BODY_BYTES + 1)
    assert processor.post("/v1/jobs", content=big).status_code == 413  # declared length

    def chunked():  # no Content-Length: refused once the stream passes the limit
        for _ in range(processor_module.MAX_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024

    assert processor.post("/v1/jobs", content=chunked()).status_code == 413
    ok = _submit(processor, "test.sleep", {"seconds": 0.01})  # normal signed work still accepted
    assert ok.status_code in (200, 202)


def test_a_task_runs_in_a_child_process_and_its_result_comes_back(processor):
    response = _submit(processor, "test.sleep", {"seconds": 0.1})
    assert response.status_code == 202
    job = _wait(processor, response.json()["job_id"])
    assert job["status"] == "done" and job["result"]["pid"] != os.getpid()


def test_a_repeated_request_joins_the_running_job_instead_of_running_it_again(processor):
    first = _submit(processor, "test.sleep", {"seconds": 0.5, "n": 1}).json()
    second = _submit(processor, "test.sleep", {"seconds": 0.5, "n": 1}).json()
    assert second["job_id"] == first["job_id"] and second["joined"] == 1
    _wait(processor, first["job_id"])
    again = _submit(processor, "test.sleep", {"seconds": 0.5, "n": 1})
    assert again.status_code == 200 and again.json()["status"] == "done"  # served from the result cache
    stats = processor.get("/healthz").json()["stats"]
    assert stats["submitted"] == 1 and stats["deduplicated"] == 1 and stats["cache_hits"] == 1


def test_a_task_that_dies_fails_alone_and_the_processor_keeps_working(processor):
    crashed = _submit(processor, "test.sleep", {"seconds": 0.05, "crash": True}).json()
    healthy = _submit(processor, "test.sleep", {"seconds": 0.3, "n": 2}).json()
    assert _wait(processor, crashed["job_id"])["error"] == "worker_crashed"
    assert _wait(processor, healthy["job_id"])["status"] == "done"
    assert processor.get("/healthz").json()["stats"]["child_crashes"] == 1
    later = _submit(processor, "test.sleep", {"seconds": 0.05, "n": 3}).json()
    assert _wait(processor, later["job_id"])["status"] == "done"


def test_a_full_processor_answers_429_rather_than_taking_more_work(processor):
    accepted = [_submit(processor, "test.sleep", {"seconds": 1.0, "n": i}).status_code for i in range(4)]
    assert accepted == [202, 202, 202, 202]  # 2 running + 2 waiting
    full = _submit(processor, "test.sleep", {"seconds": 1.0, "n": 99})
    assert full.status_code == 429 and full.headers["Retry-After"]


def test_a_task_past_its_time_limit_is_stopped():
    with TestClient(create_app(SECRET, max_parallel=1, max_queue=1, job_timeout=0.5)) as client:
        job = _submit(client, "test.sleep", {"seconds": 5}).json()
        assert _wait(client, job["job_id"])["error"] == "timeout"


def test_an_unknown_task_kind_is_refused(processor):
    assert _submit(processor, "shell.exec", {}).status_code == 400


# --- API-side client ----------------------------------------------------------

def _client(handler, **kw):
    return offload_client.OffloadClient("http://processor", SECRET, transport=httpx.MockTransport(handler), **kw)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(offload_client.OffloadClient, "_sleep", staticmethod(lambda seconds, deadline: None))


def test_the_client_retries_a_busy_processor_then_returns_the_result():
    replies = iter([httpx.Response(503), httpx.Response(429, headers={"Retry-After": "1"}),
                    httpx.Response(202, json={"status": "queued"}), httpx.Response(200, json={"status": "running"}),
                    httpx.Response(200, json={"status": "done", "result": {"ok": 1}})])
    seen = []

    def handler(request):
        assert protocol.verify(SECRET, request.method, request.url.path, request.content,
                               request.headers[protocol.TIMESTAMP_HEADER], request.headers[protocol.SIGNATURE_HEADER])
        seen.append(request.method)
        return next(replies)

    assert _client(handler).run("k", {"a": 1}) == {"ok": 1}
    assert seen == ["POST", "POST", "POST", "GET", "GET"]


def test_the_client_resubmits_when_the_processor_restarted_and_forgot_the_job():
    replies = iter([httpx.Response(202, json={"status": "queued"}), httpx.Response(404),
                    httpx.Response(200, json={"status": "done", "result": {"ok": 2}})])
    methods = []

    def handler(request):
        methods.append(request.method)
        return next(replies)

    assert _client(handler).run("k", {}) == {"ok": 2}
    assert methods == ["POST", "GET", "POST"]


def test_an_unreachable_processor_opens_the_breaker_and_later_calls_fail_at_once():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("down")

    client = _client(handler, breaker_failures=1, breaker_seconds=60)
    with pytest.raises(offload_client.OffloadUnavailable):
        client.run("k", {})
    made = len(calls)
    with pytest.raises(offload_client.OffloadUnavailable, match="circuit_open"):
        client.run("k", {})
    assert len(calls) == made  # no further network calls while open


def test_a_failed_task_is_reported_as_failed_not_unavailable():
    client = _client(lambda request: httpx.Response(200, json={"status": "failed", "error": "ValueError"}))
    with pytest.raises(offload_client.OffloadFailed):
        client.run("k", {})


def test_the_client_gives_up_at_its_deadline():
    client = _client(lambda request: httpx.Response(202, json={"status": "running"}))
    with pytest.raises(offload_client.OffloadUnavailable, match="deadline"):
        client.run("k", {}, deadline_seconds=0.05)


def test_a_misconfigured_secret_is_refused_up_front():
    with pytest.raises(ValueError):
        offload_client.OffloadClient("http://processor", "short")


def test_a_private_host_gets_its_access_token_and_the_signature_still_applies():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["signed"] = protocol.SIGNATURE_HEADER in request.headers
        return httpx.Response(200, json={"status": "done", "result": {}})

    _client(handler, access_token="hf_readonly").run("k", {})
    assert seen == {"auth": "Bearer hf_readonly", "signed": True}


def test_processor_health_is_reported_separately_from_the_api(monkeypatch):
    from src.ai.routers import health

    monkeypatch.delenv("OFFLOAD_PROCESSOR_URL", raising=False)
    assert health.processor()["status"] == "not_configured"

    class Down:
        breaker = offload_client._Breaker(3, 60)

        def health(self):
            return None

    class Up(Down):
        def health(self):
            return {"running": 1, "queued": 0, "max_parallel": 2, "warm": {"overture_index": "ready"}, "stats": {"x": 1}}

    monkeypatch.setenv("OFFLOAD_PROCESSOR_URL", "http://processor")
    monkeypatch.setenv("OFFLOAD_SHARED_SECRET", SECRET)
    monkeypatch.setattr(offload_client, "get_client", lambda: Down())
    assert health.processor().status_code == 503
    monkeypatch.setattr(offload_client, "get_client", lambda: Up())
    body = health.processor()
    assert body.status_code == 200 and b'"running":1' in body.body and b"stats" not in body.body
