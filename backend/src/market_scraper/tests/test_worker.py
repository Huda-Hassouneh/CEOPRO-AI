import subprocess

import pytest

from src.market_scraper import worker


def test_parse_request_validates_required_ids_and_ignores_code_selection():
    payload = {"tenant_id": "t1", "source_id": "s1", "receipt_id": "r1"}
    assert worker.parse_request(payload) == ("t1", "s1", "r1")
    with pytest.raises(ValueError, match="required"):
        worker.parse_request({"tenant_id": "t1"})
    with pytest.raises(ValueError, match="receipt_id"):
        worker.parse_request({"tenant_id": "t1", "source_id": "s1"})
    assert worker.parse_request({**payload, "spider": "evil"}) == ("t1", "s1", "r1")


class FakeRedis:
    def __init__(self):
        self.attempts = 0
        self.acked = []
        self.dead = []

    def hincrby(self, *_):
        self.attempts += 1
        return self.attempts

    def hdel(self, *_):
        pass

    def xack(self, *args):
        self.acked.append(args[-1])

    def xadd(self, stream, payload):
        self.dead.append((stream, payload))


def test_failed_messages_are_retried_then_dead_lettered(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(worker, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(worker, "_receipt_is_terminal", lambda payload: False)
    monkeypatch.setattr(
        worker, "run_request",
        lambda payload: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "collector")),
    )
    payload = {"tenant_id": "t", "source_id": "s", "receipt_id": "r"}
    assert worker.handle_message(client, "1-0", payload) is False
    assert worker.handle_message(client, "1-0", payload) is True
    assert client.acked == ["1-0"]
    assert client.dead[0][1]["attempts"] == "2"


def test_legacy_stream_is_not_consumed(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(worker, "STREAM", worker.LEGACY_STREAM)
    with pytest.raises(RuntimeError, match="distinct"):
        worker.handle_message(client, "1-0", {"tenant_id": "t", "source_id": "s", "receipt_id": "r"})
    assert client.acked == []


def test_duplicate_delivery_for_uncertain_receipt_is_acknowledged_without_retry(monkeypatch):
    client = FakeRedis()
    runs = []
    monkeypatch.setattr(
        worker, "run_request",
        lambda payload: runs.append(payload) or (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "collector")
        ),
    )
    monkeypatch.setattr(worker, "_receipt_is_terminal", lambda payload: True)
    payload = {"tenant_id": "t", "source_id": "s", "receipt_id": "uncertain-receipt"}

    assert worker.handle_message(client, "2-0", payload) is True
    assert runs == [payload]
    assert client.acked == ["2-0"]
    assert client.dead == []
