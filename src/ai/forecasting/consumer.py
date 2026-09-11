"""
CEOPRO AI - Demand Forecast Request Consumer.
Consumes the `demand_forecast_requested` event contract (see
src/infrastructure/DATA_OWNERSHIP_AND_CONTRACTS.md, Event B) from the
`ceopro:stream:demand_forecast_requested` topic provisioned by
src/infrastructure/init_broker.py, and runs the forecasting pipeline.

This is a separate consumer from src/infrastructure/messaging/ai_consumer.py,
which handles the unrelated market-intelligence-raw stream; that file's
ownership is a separate, still-open question (see AI_PLAN_AND_CONTRACT_UPDATES.md)
and is not touched here.
"""

import logging
import os
import time
from typing import Optional

import redis

from src.ai.db import app_role_connection
from src.ai.forecasting.pipeline import run_forecast

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("CEOPRO_AI_FORECAST_CONSUMER")

# Same attempt-tracking/dead-letter/reclaim contract as
# src/market_scraper/worker.py::handle_message()/_claimed_messages() - a
# permanently-failing message (a deleted product_id, a malformed payload)
# used to sit in this consumer group's PEL forever with nothing but a log
# line, silently dropping that forecast request for good. Retried up to
# MAX_ATTEMPTS times (each left pending for xautoclaim to reclaim) before
# moving to DEAD_STREAM and being acked.
DEAD_STREAM = os.getenv("AI_FORECAST_DEAD_STREAM_KEY", "ceopro:stream:demand_forecast_requested:dead")
MAX_ATTEMPTS = int(os.getenv("AI_FORECAST_MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.getenv("AI_FORECAST_CLAIM_IDLE_MS", "300000"))


class ForecastRequestConsumer:
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or os.getenv("REDIS_HOST", "localhost")
        self.port = port or int(os.getenv("REDIS_PORT", "6379"))
        self.group_id = "ceopro-ai-forecast-engine"
        self.stream_key = "ceopro:stream:demand_forecast_requested"
        self.consumer_name = f"ai-forecast-node-{os.getpid()}"

        # A UUID for an active tenant service principal, required by RLS -
        # mirrors src/market_scraper/data_access.py::get_tenant_connection()'s
        # SCRAPER_ACTOR_USER_ID for this consumer's own background-worker
        # identity (there's no live end user behind an async forecast
        # request, just this service acting on the tenant's behalf).
        self.actor_user_id = os.getenv("AI_SERVICE_ACTOR_USER_ID")
        if not self.actor_user_id:
            raise RuntimeError("AI_SERVICE_ACTOR_USER_ID environment variable is not set.")

        self.client = redis.Redis(host=self.host, port=self.port, decode_responses=True)
        try:
            self.client.xgroup_create(self.stream_key, self.group_id, id="0", mkstream=True)
        except redis.exceptions.ResponseError:
            pass
        logger.info(f"Forecast consumer online. Group={self.group_id} Worker={self.consumer_name}")

    def _handle_message(self, payload: dict) -> None:
        """
        Opens its own short-lived, tenant-scoped connection per message
        (app_role_connection() - the restricted ceopro_app role with
        app.current_tenant_id actually set, not the superuser DATABASE_URL
        this used to connect as) rather than reusing one long-lived
        connection across every message this consumer ever processes.
        Reusing a single connection across messages from DIFFERENT tenants
        would mean RLS context only ever reflects whichever tenant's
        message happened to run last - a real cross-tenant data exposure
        risk on every subsequent message until it's reset. A fresh
        connection per message costs a real but small amount of latency
        and is worth it for correctness on tenant isolation.
        """
        tenant_id = payload.get("tenant_id")
        product_id = payload.get("product_id")
        horizon_days = int(payload.get("horizon_days", 7))

        if not tenant_id or not product_id:
            raise ValueError(f"Malformed demand_forecast_requested payload: {payload}")

        conn = app_role_connection(tenant_id, self.actor_user_id)
        try:
            run_forecast(conn, tenant_id, product_id, horizon_days)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _claimed_messages(self):
        """
        Reclaims messages delivered to a PREVIOUS consumer (this process's
        own earlier attempt, or a worker that crashed/restarted) but never
        acked - xreadgroup alone only ever hands out messages no consumer
        has seen yet, so without this a message left pending after a
        failed _process_message() call would sit stuck in this consumer
        group's PEL forever, even across a restart (a fresh os.getpid()-
        based consumer name doesn't inherit the old consumer's pending
        messages on its own). Mirrors
        market_scraper/worker.py::_claimed_messages() exactly.
        """
        try:
            result = self.client.xautoclaim(
                self.stream_key, self.group_id, self.consumer_name, CLAIM_IDLE_MS, "0-0", count=10,
            )
        except (AttributeError, redis.ResponseError):
            return []
        return result[1] if len(result) > 1 else []

    def _process_message(self, message_id: str, payload: dict) -> None:
        """
        Attempt-tracking/dead-letter wrapper around _handle_message() -
        mirrors market_scraper/worker.py::handle_message()'s contract. A
        message that fails is retried up to MAX_ATTEMPTS times (left
        pending each time for _claimed_messages() to reclaim on a later
        loop iteration) before being moved to DEAD_STREAM and acked.
        Before this, either a malformed payload or a genuinely broken
        forecast request (e.g. a deleted product_id) stayed stuck in the
        PEL forever with no alert beyond one log line - that tenant's
        forecast request silently never completed, and nothing else ever
        surfaced it.
        """
        attempts_key = f"{self.stream_key}:attempts"
        try:
            self._handle_message(payload)
            self.client.xack(self.stream_key, self.group_id, message_id)
            self.client.hdel(attempts_key, message_id)
            logger.info(f"Message {message_id} processed and acknowledged.")
        except Exception as exc:
            attempts = int(self.client.hincrby(attempts_key, message_id, 1))
            logger.error(f"Failed to process message {message_id} (attempt {attempts}): {exc}")
            if attempts >= MAX_ATTEMPTS:
                self.client.xadd(DEAD_STREAM, {
                    **{key: str(value) for key, value in payload.items()},
                    "original_message_id": message_id,
                    "attempts": str(attempts),
                    "error": str(exc)[:1000],
                })
                self.client.xack(self.stream_key, self.group_id, message_id)
                self.client.hdel(attempts_key, message_id)
                logger.error(f"Message {message_id} moved to dead-letter stream {DEAD_STREAM} after {attempts} attempts.")

    def listen(self) -> None:
        logger.info(f"Listening on stream {self.stream_key}")
        try:
            while True:
                messages = self._claimed_messages()
                if not messages:
                    response = self.client.xreadgroup(
                        groupname=self.group_id,
                        consumername=self.consumer_name,
                        streams={self.stream_key: ">"},
                        count=10,
                        block=1500,
                    )
                    messages = [message for _, batch in response for message in batch]

                for message_id, message_payload in messages:
                    self._process_message(message_id, message_payload)

                time.sleep(0.01)
        except KeyboardInterrupt:
            logger.info("Shutdown signal received.")
        finally:
            self.client.close()


if __name__ == "__main__":
    ForecastRequestConsumer().listen()
