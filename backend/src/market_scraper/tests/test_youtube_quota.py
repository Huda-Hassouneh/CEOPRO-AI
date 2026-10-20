from datetime import datetime, timezone
from unittest import mock

import redis

from src.market_scraper import youtube_quota as q


class _Redis:
    def __init__(self):
        self.counts = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        pass


def test_a_counter_allows_exactly_its_limit_then_refuses():
    client = _Redis()
    assert [q.take(client, "searches", 2) for _ in range(3)] == [True, True, False]


def test_the_day_rolls_over_at_midnight_pacific_not_utc():
    # 2026-10-20 03:00 UTC is still 2026-10-19 20:00 in Los Angeles
    fake = mock.Mock(wraps=datetime)
    fake.now = lambda tz=None: datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc).astimezone(tz)
    with mock.patch.object(q, "datetime", fake):
        assert q.quota_day() == "20261019"


def test_the_hard_cap_is_shared_and_fails_open_when_redis_is_down():
    client = _Redis()
    with mock.patch("src.ai.core.redis_client.get_redis_client", return_value=client):
        assert [q.take_search(limit=1), q.take_search(limit=1)] == [True, False]
    with mock.patch("src.ai.core.redis_client.get_redis_client", side_effect=redis.ConnectionError("down")):
        assert q.take_search(limit=1) is True
