"""Closed-loop load on /chat: CONC clients, each sending the next request when the last returns.
Optionally starts discoveries at DISCOVER_AT seconds. Records every request's latency and outcome,
and samples the API's memory once a second. Errors are what a browser shows as "Couldn't reach KEEL"."""
import asyncio, json, statistics, sys, time
import httpx

base, conc, duration = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
discover_at = float(sys.argv[4]) if len(sys.argv) > 4 else -1
discover_cities = sys.argv[5].split(",") if len(sys.argv) > 5 else ["amman"]


async def main():
    results, mem = [], []
    t0 = time.perf_counter()
    limits = httpx.Limits(max_connections=conc + 4)
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as c:
        async def worker():
            while time.perf_counter() - t0 < duration:
                s = time.perf_counter()
                try:
                    r = await c.get("/chat")
                    ok = r.status_code == 200
                    err = None if ok else f"http_{r.status_code}"
                except httpx.HTTPError as e:
                    ok, err = False, type(e).__name__
                    await asyncio.sleep(0.2)
                results.append((round(s - t0, 3), round(time.perf_counter() - s, 4), ok, err))

        async def sampler():
            fired = False
            while time.perf_counter() - t0 < duration:
                if discover_at >= 0 and not fired and time.perf_counter() - t0 >= discover_at:
                    fired = True
                    for spec in discover_cities:
                        city, _, radius = spec.partition(":")
                        try:
                            await c.post("/discovery", params={"city": city, "radius": float(radius or 5)})
                        except httpx.HTTPError as e:
                            mem.append((round(time.perf_counter() - t0, 1), "discovery_post_failed", type(e).__name__))
                try:
                    st = (await c.get("/state", timeout=5)).json()
                    mem.append((round(time.perf_counter() - t0, 1), st["rss_mb"], st["pid"]))
                except httpx.HTTPError as e:
                    mem.append((round(time.perf_counter() - t0, 1), None, type(e).__name__))
                await asyncio.sleep(1)
            try:
                return (await c.get("/state", timeout=5)).json()
            except httpx.HTTPError:
                return None

        tasks = [asyncio.create_task(worker()) for _ in range(conc)]
        final = await sampler()
        await asyncio.gather(*tasks)
    lat = sorted(r[1] for r in results if r[2])
    errs = {}
    for r in results:
        if not r[2]:
            errs[r[3]] = errs.get(r[3], 0) + 1
    pct = lambda p: round(lat[min(len(lat) - 1, int(p * len(lat)))] * 1000, 1) if lat else None
    rss = [m[1] for m in mem if isinstance(m[1], (int, float))]
    pids = sorted({m[2] for m in mem if isinstance(m[2], int)})
    summary = {"concurrency": conc, "requests": len(results), "ok": len(lat), "errors": errs,
               "throughput_rps": round(len(lat) / duration, 1), "p50_ms": pct(0.5), "p95_ms": pct(0.95), "p99_ms": pct(0.99),
               "max_ms": round(lat[-1] * 1000, 1) if lat else None, "api_rss_max_mb": max(rss) if rss else None,
               "api_rss_min_mb": min(rss) if rss else None, "api_pids_seen": pids, "final_state": final}
    json.dump({"summary": summary, "memory": mem, "requests": results}, open(sys.argv[6] if len(sys.argv) > 6 else "/dev/null", "w"))
    print(json.dumps(summary))

asyncio.run(main())
