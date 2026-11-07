"""Processor capacity on real Overture tasks: duplicate suppression, cache hits, distinct-job throughput."""
import json, os, sys, threading, time
sys.path.insert(0, os.environ.get("KEEL_BACKEND", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))))
import httpx
from src.offload import tasks
from src.offload.client import OffloadClient
from src.market_scraper.market_discovery.models import DiscoveryQuery

URL, SECRET = sys.argv[1], os.environ["SECRET"]
CITIES = [(31.9539, 35.9106, "cafe", ["cafe"]), (24.7136, 46.6753, "pharmacy", ["pharmacy"]), (25.2048, 55.2708, "restaurant", ["restaurant"]),
          (30.0444, 31.2357, "bakery", ["bakery"]), (33.8938, 35.5018, "cafe", ["cafe"]), (21.4858, 39.1925, "pharmacy", ["pharmacy"])]
def params(i, radius):
    lat, lon, key, kw = CITIES[i % len(CITIES)]
    return tasks.overture_params(DiscoveryQuery(tenant_id="b", industry_key=key, industry_label=key, keywords=kw, latitude=lat, longitude=lon, radius_km=radius))
def health():
    return httpx.get(URL + "/healthz").json()["stats"]

def run_many(param_list):
    out = [None] * len(param_list); client = OffloadClient(URL, SECRET)
    def go(i, p):
        t = time.perf_counter()
        try:
            r = client.run(tasks.OVERTURE_SEARCH, p, deadline_seconds=600); out[i] = ("ok", len(r["candidates"]), round(time.perf_counter() - t, 2))
        except Exception as e:
            out[i] = (type(e).__name__, 0, round(time.perf_counter() - t, 2))
    th = [threading.Thread(target=go, args=(i, p)) for i, p in enumerate(param_list)]
    t = time.perf_counter(); [x.start() for x in th]; [x.join() for x in th]
    return out, round(time.perf_counter() - t, 2)

report = {}
before = health()
res, total = run_many([params(0, 4.4)] * 20)
after = health()
report["dedup_20_identical_concurrent"] = {"wall_s": total, "all_ok": all(r[0] == "ok" for r in res),
    "executions": after["submitted"] - before["submitted"], "joined": after["deduplicated"] - before["deduplicated"],
    "cache_hits": after["cache_hits"] - before["cache_hits"]}
t = time.perf_counter(); res, _ = run_many([params(0, 4.4)]); report["cached_repeat_ms"] = round((time.perf_counter() - t) * 1000, 1)
lat = []
for _ in range(50):
    t = time.perf_counter(); run_many([params(0, 4.4)]); lat.append((time.perf_counter() - t) * 1000)
lat.sort(); report["cached_repeat_50x_ms"] = {"p50": round(lat[25], 1), "p95": round(lat[47], 1), "max": round(lat[-1], 1)}
before = health()
res, total = run_many([params(i, 3.0 + i * 0.1) for i in range(12)])
after = health()
report["distinct_12_concurrent"] = {"wall_s": total, "results": res, "executions": after["submitted"] - before["submitted"],
    "jobs_per_minute": round(12 / total * 60, 1), "failed": after["failed"] - before["failed"]}
print(json.dumps(report, indent=1))
