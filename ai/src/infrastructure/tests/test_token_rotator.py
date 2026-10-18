"""P1 (QA_TEST_STRATEGY.md): internal-token rotation - grace window and eviction. Fake Redis, no server."""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.infrastructure.messaging.token_rotator import TokenRotationEngine  # noqa: E402


@pytest.fixture
def engine():
    with patch("redis.Redis") as redis_cls:
        eng = TokenRotationEngine(host="h", port=1)
        eng.client = redis_cls.return_value
        yield eng


def test_requires_jwt_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(RuntimeError):
        TokenRotationEngine()


def test_rotation_issues_a_new_hex_token_and_puts_old_ones_in_grace(engine):
    engine.client.smembers.return_value = {"old1", "old2"}
    pipe = engine.client.pipeline.return_value
    new, old = engine.execute_secure_rotation()
    assert len(new) == 64 and int(new, 16) >= 0
    assert sorted(old) == ["old1", "old2"]
    pipe.sadd.assert_called_once_with(engine.redis_key, new)
    assert pipe.setex.call_count == 2
    assert all(call.args[1] == engine.grace_period for call in pipe.setex.call_args_list)
    pipe.execute.assert_called_once()


def test_two_rotations_never_issue_the_same_token(engine):
    engine.client.smembers.return_value = set()
    assert engine.execute_secure_rotation()[0] != engine.execute_secure_rotation()[0]


def test_rotation_failure_is_raised_not_swallowed(engine):
    engine.client.smembers.side_effect = ConnectionError("redis down")
    with pytest.raises(ConnectionError):
        engine.execute_secure_rotation()


@pytest.mark.parametrize("bad", [None, "", 123, b"bytes"])
def test_non_string_or_empty_tokens_are_invalid(engine, bad):
    assert engine.validate_incoming_token(bad) is False
    engine.client.sismember.assert_not_called()


def test_unknown_token_is_invalid(engine):
    engine.client.sismember.return_value = False
    assert engine.validate_incoming_token("nope") is False


def test_current_token_with_no_grace_tracker_is_valid(engine):
    engine.client.sismember.return_value = True
    engine.client.exists.return_value = 0
    assert engine.validate_incoming_token("cur") is True


def test_token_inside_its_grace_window_is_valid(engine):
    engine.client.sismember.return_value = True
    engine.client.exists.return_value = 1
    engine.client.ttl.return_value = 500
    assert engine.validate_incoming_token("old") is True
    engine.client.srem.assert_not_called()


@pytest.mark.parametrize("ttl", [0, -1, -2])
def test_token_past_its_grace_window_is_evicted_and_invalid(engine, ttl):
    engine.client.sismember.return_value = True
    engine.client.exists.return_value = 1
    engine.client.ttl.return_value = ttl
    assert engine.validate_incoming_token("old") is False
    engine.client.srem.assert_called_once_with(engine.redis_key, "old")
    engine.client.delete.assert_called_once()


def test_redis_error_during_validation_fails_closed(engine):
    engine.client.sismember.side_effect = ConnectionError("down")
    assert engine.validate_incoming_token("x") is False
