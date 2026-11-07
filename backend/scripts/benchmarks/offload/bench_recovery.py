"""Failure behaviour, through the real API-side code path (overture.search_remote):
E1 processor down        -> Overture reports processor_unavailable quickly; breaker then answers instantly.
E2 processor killed mid-task and started again -> the client resubmits and the result still arrives.
E3 back-pressure         -> 20 jobs into a processor with 2 slots + 2 queue: 429s are retried, all complete, each runs once."""
import json, os, subprocess, sys, threading, time
sys.path.insert(0, os.environ.get("KEEL_BACKEND", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))))
import httpx
os.environ["OVERTURE_EXECUTION"] = "remote"
os.environ["OFFLOAD_BREAKER_FAILURES"] = "1"; os.environ["OFFLOAD_BREAKER_SECONDS"] = "30"
from src.offload import client as oc, tasks
from src.market_scraper.market_discovery.models import DiscoveryQuery
from src.market_scraper.market_discovery.providers import overture

B = os.path.dirname(os.path.abspath(__file__)); SECRET = os.environ["SECRET"]; S = os.environ["SCRATCH"]
def start(port, **env):
    e = dict(os.environ, SECRET=SECRET, CACHE=f"{S}/overture-cache", PPORT=str(port), **{k: str(v) for k, v in env.items()})
    p = subprocess.Popen([f"{B}/start_processor.sh"], env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200: return p
        except httpx.HTTPError: time.sleep(0.1)
    raise RuntimeError("processor did not start")
def stop(p):
    os.killpg(p.pid, 9); p.wait()
def q(radius):
    return DiscoveryQuery(tenant_id="b", industry_key="cafe", industry_label="Cafe", keywords=["cafe"], latitude=31.9539, longitude=35.9106, radius_km=radius)
report = {}

# E1: nothing listening
os.environ["OFFLOAD_PROCESSOR_URL"] = "http://127.0.0.1:7999"; os.environ["OFFLOAD_SHARED_SECRET"] = SECRET; oc._client = None
t = time.perf_counter(); r = overture.search(q(5.1)); first = time.perf_counter() - t
t = time.perf_counter(); r2 = overture.search(q(5.1)); second = time.perf_counter() - t
report["E1_processor_down"] = {"first_call": [r.status, r.reason, round(first, 2)], "while_breaker_open": [r2.status, r2.reason, round(second * 1000, 2)]}

# E2: killed mid-task, back 3 s later
os.environ["OFFLOAD_PROCESSOR_URL"] = "http://127.0.0.1:7998"; os.environ["OFFLOAD_BREAKER_FAILURES"] = "3"; oc._client = None
p = start(7998); out = {}
def go():
    t = time.perf_counter(); res = overture.search(q(6.3)); out["r"] = (res.status, res.reason, len(res.candidates), round(time.perf_counter() - t, 2))
th = threading.Thread(target=go); th.start(); time.sleep(3)
stop(p); killed_at = time.time(); time.sleep(3)
p = start(7998); th.join(); stop(p)
report["E2_killed_mid_task_then_restarted"] = {"result": out["r"], "downtime_s": 3}

# E3: back-pressure with test tasks
p = start(7997, PAR=2, QUEUE=2, TEST_TASKS=1)
client = oc.OffloadClient("http://127.0.0.1:7997", SECRET); res = [None] * 20
def run(i):
    t = time.perf_counter()
    try: client.run("test.sleep", {"seconds": 1.0, "n": i}, deadline_seconds=180); res[i] = ("ok", round(time.perf_counter() - t, 1))
    except Exception as e: res[i] = (type(e).__name__, round(time.perf_counter() - t, 1))
t = time.perf_counter(); ths = [threading.Thread(target=run, args=(i,)) for i in range(20)]; [x.start() for x in ths]; [x.join() for x in ths]
stats = httpx.get("http://127.0.0.1:7997/healthz").json()["stats"]; stop(p)
report["E3_backpressure_20_jobs_2_slots_2_queue"] = {"wall_s": round(time.perf_counter() - t, 1), "outcomes": {k: sum(1 for r in res if r[0] == k) for k in {r[0] for r in res}},
    "max_wait_s": max(r[1] for r in res), "executions": stats["submitted"], "rejected_429": stats["rejected_full"], "completed": stats["completed"]}
print(json.dumps(report, indent=1))
