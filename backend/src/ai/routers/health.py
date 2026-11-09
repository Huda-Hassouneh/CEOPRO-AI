import logging
import time

import psycopg2
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.ai import db
from src.ai.core.redis_client import get_redis_client

router = APIRouter(tags=["health"])
logger = logging.getLogger("KEEL_HEALTH")


@router.get("/health")
def health() -> dict:
    """The process is up. Render's health check: deliberately independent of
    the database and Redis, so a brief outage of either doesn't make Render
    restart a healthy API."""
    return {"status": "ok"}


def _timed(check) -> dict:
    started = time.monotonic()
    try:
        check()
        return {"ok": True, "ms": round((time.monotonic() - started) * 1000)}
    except Exception as err:  # noqa: BLE001 - reported, never raised
        logger.warning("readiness check failed: %s", err)
        return {"ok": False, "ms": round((time.monotonic() - started) * 1000), "error": type(err).__name__}


def _database():
    conn = psycopg2.connect(db._app_database_url(), connect_timeout=3)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET statement_timeout = 2000; SELECT 1;")
            cursor.fetchone()
    finally:
        conn.close()


def _redis():
    get_redis_client(socket_connect_timeout=2, socket_timeout=2).ping()


@router.get("/health/ready")
def ready():
    """Whether the API can serve requests: the database (as the app's own
    restricted role) and Redis both answer. 503 otherwise. For an external
    uptime monitor; never exposes connection details."""
    checks = {"database": _timed(_database), "redis": _timed(_redis)}
    healthy = all(check["ok"] for check in checks.values())
    return JSONResponse(status_code=200 if healthy else 503, content={"status": "ok" if healthy else "unavailable", "checks": checks})


_STORAGE_CACHE_SECONDS = 300
_storage_cache: dict = {}


@router.get("/health/storage")
def storage():
    """Object storage (core/object_storage.py), separate from /health/ready so
    an object-storage outage never fails the API's readiness. Cached for five
    minutes: every check is a billable request on hosted storage. Only the
    mode and how full storage is - never the endpoint, bucket or keys."""
    from src.ai.core import object_storage

    now = time.monotonic()
    cached = _storage_cache.get("result")
    if cached and now - cached[0] < _STORAGE_CACHE_SECONDS:
        status_code, body = cached[1], cached[2]
    else:
        started = time.monotonic()
        try:
            store = db.minio_client()
        except object_storage.StorageUnavailable as err:
            not_configured = "must all be set" in str(err)
            status_code, body = (200 if not_configured else 503), {
                "status": "not_configured" if not_configured else "unavailable", "error": type(err).__name__}
        else:
            try:
                store.bucket_exists(store.settings.bucket or "ceopro-rag-knowledge")
                summary = store.usage_summary()
                full = summary["used_percent"] is not None and summary["used_percent"] >= 100
                status_code, body = 200, {"status": "full" if full else "ok", **summary}
            except Exception as err:  # noqa: BLE001 - reported, never raised
                logger.warning("storage check failed: %s", err)
                status_code, body = 503, {"status": "unavailable", "error": type(err).__name__}
        body["ms"] = round((time.monotonic() - started) * 1000)
        _storage_cache["result"] = (now, status_code, body)
    return JSONResponse(status_code=status_code, content=body)


@router.get("/health/processor")
def processor():
    """The external processor that runs heavy work (src/offload), checked separately from the API:
    an uptime monitor sees "API up, processor down" instead of one combined status. 200 when it
    answers or none is configured, 503 when configured but unreachable. Load counters only - no
    task data, URLs or secrets. A request here also wakes a processor host that sleeps when idle."""
    from src.market_scraper.market_discovery.providers import overture
    from src.offload import client as offload

    if not offload.configured():
        return {"status": "not_configured", "overture": overture.execution_mode()}
    client = offload.get_client()
    started = time.monotonic()
    answer = client.health()
    body = {"status": "ok" if answer else "unavailable", "ms": round((time.monotonic() - started) * 1000),
            "calls_paused": not client.breaker.allow()}
    if answer:
        body.update({key: answer.get(key) for key in ("running", "queued", "max_parallel", "warm")})
    return JSONResponse(status_code=200 if answer else 503, content=body)
