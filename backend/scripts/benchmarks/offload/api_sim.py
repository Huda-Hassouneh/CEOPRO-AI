"""A stand-in for the KEEL API under Render's limits, for benchmarks only.

- /chat: what a chatbot request costs the API process itself: a little CPU (parsing,
  regex, JSON) and then waiting on the language model (SIM_LLM_SECONDS, like the Groq call).
- /discovery: starts a discovery in a background thread, exactly as routers/discovery.py
  does: SIM_MODE=inprocess runs the CURRENT (old) Overture code inside this process,
  SIM_MODE=offload sends it to the processor (src/offload) and only waits.
- SIM_BALLAST_MB of memory is held to match the real API's idle size (~364 MB measured on Render).
"""
import importlib.util, json, os, re, sys, threading, time

sys.path.insert(0, os.environ.get("KEEL_BACKEND", os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))))
from fastapi import FastAPI

ballast = bytearray(int(os.getenv("SIM_BALLAST_MB", "0")) * 1024 * 1024)
ballast[::4096] = b"x" * len(ballast[::4096])
MODE = os.getenv("SIM_MODE", "offload")
LLM = float(os.getenv("SIM_LLM_SECONDS", "0.3"))
app = FastAPI()
state = {"discoveries": [], "started": time.time()}

from src.market_scraper.market_discovery.models import DiscoveryQuery
if MODE == "inprocess":
    spec = importlib.util.spec_from_file_location("overture_old", os.path.join(os.path.dirname(__file__), "overture_old.py"))
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    search = old.search
else:
    from src.market_scraper.market_discovery.providers import overture
    search = overture.search_remote

CITIES = {"amman": (31.9539, 35.9106, "Amman", "JO", "cafe", ["cafe", "coffee"]),
          "riyadh": (24.7136, 46.6753, "Riyadh", "SA", "pharmacy", ["صيدلية", "pharmacy"]),
          "dubai": (25.2048, 55.2708, "Dubai", "AE", "restaurant", ["restaurant", "مطعم"]),
          "cairo": (30.0444, 31.2357, "Cairo", "EG", "bakery", ["bakery", "مخبز"]),
          "beirut": (33.8938, 35.5018, "Beirut", "LB", "cafe", ["cafe", "قهوة"])}


def _discover(city, radius):
    lat, lon, name, cc, key, kw = CITIES[city]
    q = DiscoveryQuery(tenant_id="sim", industry_key=key, industry_label=key.title(), keywords=kw, latitude=lat,
                       longitude=lon, radius_km=radius, city=name, country_code=cc)
    t = time.time(); r = search(q)
    state["discoveries"].append({"city": city, "status": r.status, "reason": r.reason, "n": len(r.candidates),
                                 "seconds": round(time.time() - t, 2)})


@app.get("/chat")
def chat(q: str = "كم بعنا هذا الشهر؟ what were sales this month"):
    text = " ".join([q] * 50)
    tokens = re.findall(r"\w+", text.lower())
    json.dumps({"tokens": tokens[:500], "n": len(tokens)})
    time.sleep(LLM)  # waiting on the language model provider
    return {"answer": "ok", "tokens": len(tokens)}


@app.post("/discovery")
def discovery(city: str = "amman", radius: float = 5.0):
    threading.Thread(target=_discover, args=(city, radius), daemon=True).start()
    return {"status": "queued"}


@app.get("/state")
def get_state():
    import psutil
    return {"rss_mb": round(psutil.Process().memory_info().rss / 2**20, 1), "discoveries": state["discoveries"],
            "uptime": round(time.time() - state["started"], 1), "pid": os.getpid()}
