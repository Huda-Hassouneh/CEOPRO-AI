"""
Tests ForecastRequestConsumer against a real Redis instance - constructing it
requires an actual reachable Redis (xgroup_create is called eagerly in
__init__, and a ConnectionError there isn't caught), so this can't be a pure
mock-based unit test the way test_pipeline.py's DB tests are.

Skipped automatically unless AI_TEST_REDIS_HOST is set, so it never runs in CI
or requires Docker on every machine. Point it at a disposable Redis - tests
create/use a real consumer group on ceopro:stream:demand_forecast_requested.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
import redis

from src.ai.forecasting.consumer import ForecastRequestConsumer

REDIS_HOST = os.getenv("AI_TEST_REDIS_HOST")
REDIS_PORT = int(os.getenv("AI_TEST_REDIS_PORT", "6379"))

pytestmark = pytest.mark.skipif(not REDIS_HOST, reason="AI_TEST_REDIS_HOST not set - skipping live-Redis consumer test")


@pytest.fixture(autouse=True)
def dummy_actor_user_id(monkeypatch):
    # __init__ only checks AI_SERVICE_ACTOR_USER_ID is set, it doesn't connect
    # to Postgres with it - the tests here mock out app_role_connection/
    # run_forecast so no real DB is needed.
    monkeypatch.setenv("AI_SERVICE_ACTOR_USER_ID", "00000000-0000-0000-0000-000000000000")


@pytest.fixture
def redis_client():
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    yield client
    client.flushdb()
    client.close()


@pytest.fixture
def consumer(redis_client):
    return ForecastRequestConsumer(host=REDIS_HOST, port=REDIS_PORT)


def test_init_creates_consumer_group_on_stream(consumer, redis_client):
    groups = redis_client.xinfo_groups(consumer.stream_key)
    assert any(g["name"] == consumer.group_id for g in groups)


def test_init_raises_without_actor_user_id(monkeypatch):
    monkeypatch.delenv("AI_SERVICE_ACTOR_USER_ID", raising=False)
    with pytest.raises(RuntimeError, match="AI_SERVICE_ACTOR_USER_ID"):
        ForecastRequestConsumer(host=REDIS_HOST, port=REDIS_PORT)


def test_handle_message_raises_on_missing_tenant_id(consumer):
    with pytest.raises(ValueError, match="Malformed"):
        consumer._handle_message(payload={"product_id": "p1", "horizon_days": "7"})


def test_handle_message_raises_on_missing_product_id(consumer):
    with pytest.raises(ValueError, match="Malformed"):
        consumer._handle_message(payload={"tenant_id": "t1", "horizon_days": "7"})


def test_handle_message_opens_a_tenant_scoped_connection_and_closes_it(consumer):
    """
    The real fix this covers: _handle_message() must open its own
    RLS-respecting, tenant-scoped connection per message (app_role_connection,
    the restricted ceopro_app role) rather than reusing one long-lived
    superuser connection across messages from potentially different tenants -
    see the module's own docstring on _handle_message for the cross-tenant
    exposure that would otherwise be possible.
    """
    fake_conn = MagicMock()
    with patch("src.ai.forecasting.consumer.app_role_connection", return_value=fake_conn) as mock_app_conn, \
         patch("src.ai.forecasting.consumer.run_forecast") as mock_run_forecast:
        consumer._handle_message(payload={"tenant_id": "t1", "product_id": "p1", "horizon_days": "14"})

    mock_app_conn.assert_called_once_with("t1", consumer.actor_user_id)
    mock_run_forecast.assert_called_once_with(fake_conn, "t1", "p1", 14)
    fake_conn.close.assert_called_once()
    fake_conn.rollback.assert_not_called()


def test_handle_message_defaults_horizon_days_to_seven(consumer):
    fake_conn = MagicMock()
    with patch("src.ai.forecasting.consumer.app_role_connection", return_value=fake_conn), \
         patch("src.ai.forecasting.consumer.run_forecast") as mock_run_forecast:
        consumer._handle_message(payload={"tenant_id": "t1", "product_id": "p1"})
    mock_run_forecast.assert_called_once_with(fake_conn, "t1", "p1", 7)


def test_handle_message_rolls_back_and_closes_on_run_forecast_failure(consumer):
    fake_conn = MagicMock()
    with patch("src.ai.forecasting.consumer.app_role_connection", return_value=fake_conn), \
         patch("src.ai.forecasting.consumer.run_forecast", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            consumer._handle_message(payload={"tenant_id": "t1", "product_id": "p1"})

    fake_conn.rollback.assert_called_once()
    fake_conn.close.assert_called_once()  # connection still cleaned up despite the failure


def test_full_publish_consume_ack_cycle_matches_listen_loop_mechanics(consumer, redis_client):
    """
    Exercises the same xreadgroup -> handle -> xack sequence listen() uses,
    without invoking listen()'s infinite loop.
    """
    redis_client.xadd(consumer.stream_key, {"tenant_id": "t1", "product_id": "p1", "horizon_days": "7"})

    fake_conn = MagicMock()
    with patch("src.ai.forecasting.consumer.app_role_connection", return_value=fake_conn), \
         patch("src.ai.forecasting.consumer.run_forecast") as mock_run_forecast:
        response = consumer.client.xreadgroup(
            groupname=consumer.group_id, consumername=consumer.consumer_name,
            streams={consumer.stream_key: ">"}, count=10, block=1000,
        )
        assert response, "expected the published message to be delivered"

        for _stream, messages in response:
            for message_id, payload in messages:
                consumer._handle_message(payload)
                consumer.client.xack(consumer.stream_key, consumer.group_id, message_id)

    mock_run_forecast.assert_called_once_with(fake_conn, "t1", "p1", 7)

    pending = redis_client.xpending(consumer.stream_key, consumer.group_id)
    assert pending["pending"] == 0  # message was acked, nothing left outstanding


def test_listen_closes_redis_on_keyboard_interrupt(consumer):
    """
    listen()'s own while-loop, KeyboardInterrupt handling, and finally-block
    cleanup - previously untested (only the per-message logic it calls was
    covered). xreadgroup raising KeyboardInterrupt simulates Ctrl+C landing
    during the blocking read. listen() no longer owns a single DB connection
    itself (each message opens/closes its own via _handle_message), so there's
    nothing DB-related left for it to clean up here beyond the Redis client.
    """
    consumer.client.xreadgroup = MagicMock(side_effect=KeyboardInterrupt)
    real_client = consumer.client
    real_client.close = MagicMock(wraps=real_client.close)

    consumer.listen()  # must not raise - KeyboardInterrupt is caught internally

    real_client.close.assert_called_once()


def test_listen_continues_past_empty_responses(consumer):
    """An empty xreadgroup response (timeout, no messages) must not stop the loop."""
    consumer.client.xreadgroup = MagicMock(side_effect=[[], [], KeyboardInterrupt])

    consumer.listen()

    assert consumer.client.xreadgroup.call_count == 3


def test_listen_continues_past_a_message_processing_error(consumer):
    """A malformed message must not crash the loop, and must never be acked."""
    malformed_response = [(consumer.stream_key, [("123-0", {"product_id": "p1"})])]  # missing tenant_id
    consumer.client.xreadgroup = MagicMock(side_effect=[malformed_response, KeyboardInterrupt])
    consumer.client.xack = MagicMock()

    consumer.listen()

    consumer.client.xack.assert_not_called()  # a message that raised must not be acked


def test_listen_acks_only_after_successful_processing(consumer):
    fake_conn = MagicMock()
    good_response = [(consumer.stream_key, [("124-0", {"tenant_id": "t1", "product_id": "p1"})])]
    consumer.client.xreadgroup = MagicMock(side_effect=[good_response, KeyboardInterrupt])
    consumer.client.xack = MagicMock()

    with patch("src.ai.forecasting.consumer.app_role_connection", return_value=fake_conn), \
         patch("src.ai.forecasting.consumer.run_forecast") as mock_run_forecast:
        consumer.listen()

    mock_run_forecast.assert_called_once_with(fake_conn, "t1", "p1", 7)
    consumer.client.xack.assert_called_once_with(consumer.stream_key, consumer.group_id, "124-0")
    fake_conn.rollback.assert_not_called()
