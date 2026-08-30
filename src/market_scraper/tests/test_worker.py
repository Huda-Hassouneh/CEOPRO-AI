import subprocess

import pytest

from src.market_scraper import worker


def test_parse_request_validates_required_ids_and_ignores_code_selection():
    assert worker.parse_request({"tenant_id": "t1", "source_id": "s1"}) == ("t1", "s1")
    with pytest.raises(ValueError, match="required"):
        worker.parse_request({"tenant_id": "t1"})
    assert worker.parse_request({"tenant_id": "t1", "source_id": "s1", "spider": "evil"}) == ("t1", "s1")


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
    monkeypatch.setattr(
        worker, "run_request",
        lambda payload: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "collector")),
    )
    assert worker.handle_message(client, "1-0", {"tenant_id": "t", "source_id": "s"}) is False
    assert worker.handle_message(client, "1-0", {"tenant_id": "t", "source_id": "s"}) is True
    assert client.acked == ["1-0"]
    assert client.dead[0][1]["attempts"] == "2"
