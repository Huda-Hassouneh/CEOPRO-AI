"""
KEEL - Shared Redis client factory.

docker-compose.yml's local Redis has no auth (`redis:6379`, no password),
so REDIS_HOST/REDIS_PORT alone was always enough there - but every
managed Redis a real deployment would actually use requires more than
that. Two real shapes now supported:

1. REDIS_URL - a single connection string (`redis://` or `rediss://`,
   optionally with a password) - what render.yaml's own Key Value
   resource auto-wires in via `fromService: {type: keyvalue, property:
   connectionString}`, so a Render deploy needs zero manual host/port/
   password copy-pasting.
2. REDIS_HOST/REDIS_PORT/REDIS_PASSWORD/REDIS_TLS - the original
   separate-vars shape, for any host that doesn't hand back one URL.

REDIS_URL wins when both are set. Neither forecasting/consumer.py's
ForecastRequestConsumer nor routers/extraction.py's discovery-stream
publish ever read either shape before this module existed, so both
would fail to authenticate against any real managed Redis the moment
this service left docker-compose.
"""
import os
import threading
from urllib.parse import urlparse

import redis


# One client (and so one connection pool) per configuration, for the checks
# made on every API request (signed-out tokens and sessions, the read-model
# cache's shared generation): a new client per call opened a new TCP
# connection per call - ~15% of the API's CPU under load. redis.Redis() is
# thread-safe. Only for callers that just issue commands: a component that
# holds its client and changes it (the stream consumers) uses
# get_redis_client(). The Redis class is part of the key, so a test that
# swaps in a fake class still gets its fake.
_shared_clients: dict = {}
_shared_lock = threading.Lock()


def get_shared_redis_client(**overrides) -> redis.Redis:
    key = (redis.Redis, os.getenv("REDIS_URL"), os.getenv("REDIS_HOST"), os.getenv("REDIS_PORT"),
           os.getenv("REDIS_PASSWORD"), os.getenv("REDIS_TLS"), tuple(sorted(overrides.items())))
    client = _shared_clients.get(key)
    if client is None:
        with _shared_lock:
            client = _shared_clients.get(key)
            if client is None:
                client = _shared_clients[key] = get_redis_client(**overrides)
    return client


def get_redis_client(**overrides) -> redis.Redis:
    """A new client (with its own connection pool) - see get_shared_redis_client()."""
    return _new_client(**overrides)


def _new_client(**overrides) -> redis.Redis:
    redis_url = os.getenv("REDIS_URL")
    if redis_url and "host" not in overrides and "port" not in overrides:
        parsed = urlparse(redis_url)
        return redis.Redis(
            host=parsed.hostname, port=parsed.port or 6379, password=parsed.password,
            ssl=parsed.scheme == "rediss", decode_responses=True, **overrides,
        )

    host = overrides.pop("host", None) or os.getenv("REDIS_HOST", "localhost")
    port = overrides.pop("port", None) or int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD") or None
    use_tls = os.getenv("REDIS_TLS", "false").strip().lower() in ("1", "true", "yes")
    return redis.Redis(host=host, port=port, password=password, ssl=use_tls, decode_responses=True, **overrides)
