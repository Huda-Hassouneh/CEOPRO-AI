"""
Unit tests for backend/image_server/server.py with a fake pipeline (the real
SDXL model is exercised by scripts/real_image_check.py, not in CI): request
checks, one image at a time, the low-memory guard, the optional key, seeds
and the response shape KEEL's local provider reads.
"""
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_server import server


class _FakePipe:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

        class Result:
            images = [Image.new("RGB", (kwargs["width"], kwargs["height"]), (120, 80, 40))]
        return Result()


@pytest.fixture
def client(monkeypatch):
    pipe = _FakePipe()
    monkeypatch.setitem(server._state, "pipe", pipe)
    monkeypatch.setattr(server, "_available_gb", lambda: 8.0)
    monkeypatch.setattr(server, "API_KEY", "")
    yield TestClient(server.app), pipe


def _post(client, **body):
    return client.post("/v1/images/generations", json={"prompt": "a jar of zaatar", **body})


def test_generates_a_jpeg_of_the_requested_size_with_its_seed(client):
    http, pipe = client
    response = _post(http, size="768x1344", seed=42, n=2)
    assert response.status_code == 200
    data = response.json()["data"]
    assert [d["seed"] for d in data] == [42, 43]  # n > 1: consecutive seeds, each its own image
    with Image.open(io.BytesIO(base64.b64decode(data[0]["b64_json"]))) as picture:
        assert picture.format == "JPEG" and picture.size == (768, 1344)
    assert pipe.calls[0]["num_inference_steps"] == server.DEFAULT_STEPS
    assert "text" in pipe.calls[0]["negative_prompt"]


@pytest.mark.parametrize("size", ["1004x1000", "2048x2048", "128x128"])
def test_bad_sizes_are_refused(client, size):
    http, _ = client
    assert _post(http, size=size).status_code in (400, 422)


def test_low_memory_answers_busy_instead_of_risking_the_process(client, monkeypatch):
    http, pipe = client
    monkeypatch.setattr(server, "_available_gb", lambda: 0.4)
    response = _post(http)
    assert response.status_code == 503 and response.headers["Retry-After"] == "60"
    assert pipe.calls == []


def test_one_image_at_a_time(client):
    http, _ = client
    assert server._lock.acquire(blocking=False)
    try:
        response = _post(http)
        assert response.status_code == 503 and "busy" in response.json()["error"]
    finally:
        server._lock.release()


def test_model_not_loaded_is_503(client, monkeypatch):
    http, _ = client
    monkeypatch.setitem(server._state, "pipe", None)
    assert _post(http).status_code == 503


def test_optional_key(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(server, "API_KEY", "s3cret")
    assert _post(http).status_code == 401
    ok = http.post("/v1/images/generations", json={"prompt": "x"}, headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_health_reports_speed_and_memory(client):
    http, _ = client
    _post(http)
    health = http.get("/health").json()
    assert health["ok"] is True and health["images_made"] >= 1 and health["average_seconds_per_image"] is not None
