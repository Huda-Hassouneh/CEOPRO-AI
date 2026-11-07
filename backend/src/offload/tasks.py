"""The work the processor can run, by kind. Each function takes the task's
JSON params and returns a JSON-serialisable result. They run inside a child
process of the processor, never inside the API."""
import os
from dataclasses import asdict
from typing import Callable, Dict

OVERTURE_SEARCH = "overture.search"

# Only what Overture matching reads: the company's place, radius and the words
# that say what it does. No tenant id, company name, website or anything from
# the database leaves the API.
OVERTURE_QUERY_FIELDS = ("industry_key", "industry_label", "keywords", "latitude", "longitude", "radius_km", "city",
                         "country_code", "language", "osm_tags", "google_types", "category_words", "max_results")


def overture_params(query) -> dict:
    params = {}
    for name in OVERTURE_QUERY_FIELDS:
        value = getattr(query, name)
        if isinstance(value, tuple):
            value = [list(v) if isinstance(v, tuple) else v for v in value]
        params[name] = value
    params["latitude"] = round(params["latitude"], 5) if params["latitude"] is not None else None  # ~1 m: same place, same job
    params["longitude"] = round(params["longitude"], 5) if params["longitude"] is not None else None
    return params


def overture_query(params: dict):
    from src.market_scraper.market_discovery.models import DiscoveryQuery

    values = {name: params.get(name) for name in OVERTURE_QUERY_FIELDS if name in params}
    for name in ("osm_tags",):
        values[name] = tuple(tuple(v) for v in values.get(name) or ())
    for name in ("google_types", "category_words"):
        values[name] = tuple(values.get(name) or ())
    values["keywords"] = list(values.get("keywords") or [])
    return DiscoveryQuery(tenant_id="offload", **{k: v for k, v in values.items() if v is not None})


def run_overture_search(params: dict) -> dict:
    from src.market_scraper.market_discovery.providers import overture

    result = overture.search_local(overture_query(params))
    return {"provider": result.provider, "status": result.status, "reason": result.reason,
            "requests": result.requests, "candidates": [asdict(c) for c in result.candidates]}


def _sleep_task(params: dict) -> dict:  # benchmarks and tests only
    import time

    time.sleep(float(params.get("seconds", 0.1)))
    if params.get("allocate_mb"):
        block = bytearray(int(params["allocate_mb"]) * 1024 * 1024)
        block[::4096] = b"x" * len(block[::4096])
    if params.get("crash"):
        os._exit(137)  # what an out-of-memory kill looks like from outside
    return {"slept": params.get("seconds", 0.1), "pid": os.getpid()}


TASKS: Dict[str, Callable[[dict], dict]] = {OVERTURE_SEARCH: run_overture_search}
if os.getenv("OFFLOAD_ENABLE_TEST_TASKS", "").lower() in ("1", "true", "yes"):
    TASKS["test.sleep"] = _sleep_task


def run(kind: str, params: dict) -> dict:
    try:
        # A task that runs the machine out of memory: the kernel picks this child, never the server.
        with open("/proc/self/oom_score_adj", "w") as handle:
            handle.write("1000")
    except OSError:
        pass
    return TASKS[kind](params)
