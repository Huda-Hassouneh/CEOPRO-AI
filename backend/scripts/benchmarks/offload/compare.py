"""Old (HEAD) vs new Overture search on real data: identical candidates? peak memory each (separate processes)."""
import importlib.util, json, os, sys, threading, time
import psutil
sys.path.insert(0, sys.argv[1]); which = sys.argv[2]; out_path = sys.argv[3]
proc = psutil.Process(); peak = [0]; stop = threading.Event()
def sample():
    while not stop.is_set():
        peak[0] = max(peak[0], proc.memory_info().rss); time.sleep(0.02)
threading.Thread(target=sample, daemon=True).start()
from src.market_scraper.market_discovery.models import DiscoveryQuery
if which == "old":
    spec = importlib.util.spec_from_file_location("overture_old", os.path.join(os.path.dirname(__file__), "overture_old.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); fn = mod.search
else:
    from src.market_scraper.market_discovery.providers import overture as mod; fn = mod.search_local
cases = [("cafe", "Cafe", ["cafe", "coffee"], 31.9539, 35.9106, 5.0, "Amman", "JO"),
         ("pharmacy", "Pharmacy", ["صيدلية", "pharmacy"], 24.7136, 46.6753, 10.0, "Riyadh", "SA"),
         ("restaurant", "Restaurant", ["restaurant", "مطعم"], 25.2048, 55.2708, 15.0, "Dubai", "AE")]
res = {}
for label in ("cold", "warm"):
    for key, lab, kw, lat, lon, r, city, cc in cases:
        q = DiscoveryQuery(tenant_id="b", industry_key=key, industry_label=lab, keywords=kw, latitude=lat, longitude=lon,
                           radius_km=r, city=city, country_code=cc)
        peak[0] = proc.memory_info().rss; t = time.perf_counter(); r_ = fn(q); dt = time.perf_counter() - t
        res[f"{label}:{city}"] = {"status": r_.status, "n": len(r_.candidates), "s": round(dt, 2), "peak_mb": round(peak[0] / 2**20, 1),
                                 "refs": sorted(c.source_ref for c in r_.candidates)}
stop.set(); res["rss_end_mb"] = round(proc.memory_info().rss / 2**20, 1)
json.dump(res, open(out_path, "w"))
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "refs"} if isinstance(v, dict) else v for k, v in res.items()}))
