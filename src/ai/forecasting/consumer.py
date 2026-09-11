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

    def listen(self) -> None:
        logger.info(f"Listening on stream {self.stream_key}")
        try:
            while True:
                response = self.client.xreadgroup(
                    groupname=self.group_id,
                    consumername=self.consumer_name,
                    streams={self.stream_key: ">"},
                    count=10,
                    block=1500,
                )

                if not response:
                    continue

                for _stream, messages in response:
                    for message_id, message_payload in messages:
                        try:
                            self._handle_message(message_payload)
                            self.client.xack(self.stream_key, self.group_id, message_id)
                            logger.info(f"Message {message_id} processed and acknowledged.")
                        except Exception as inner_process_err:
                            logger.error(f"Failed to process message {message_id}: {str(inner_process_err)}")
                            continue

                time.sleep(0.01)
        except KeyboardInterrupt:
            logger.info("Shutdown signal received.")
        finally:
            self.client.close()


if __name__ == "__main__":
    ForecastRequestConsumer().listen()
