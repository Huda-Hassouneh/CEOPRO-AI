"""
Reproducible performance baseline for a running KEEL API.

    PERF_PASSWORD='...' python -m scripts.perf_baseline \\
        --api http://127.0.0.1:8000 --pid <uvicorn pid> \\
        --accounts rania@zaytouna.keel-demo.example mostafa@bytefix.keel-demo.example ... \\
        --levels 35 100 300 --load-seconds 60 --out ../docs/perf/baseline.json

Phases (each one measured separately):
  endpoints  - every main screen's API call, sequentially, --repeat times (warm)
  dashboard_visit - a write, then the Command Center and the alerts bell at
               the same moment (opening the dashboard after data changed)
  assistant  - English and Arabic questions end to end (includes the live LLM call)
  files      - spreadsheet/CSV uploads (into a fresh company it creates via signup,
               so the demo companies are never modified) and report exports
  forecast   - a full forecast refresh for the first account's company
  load       - concurrent virtual users (same screen mix as scripts/load_test.py)
               at each --levels value, then a recovery check

For every phase it records latency P50/P95/max and errors per operation, the
API's process tree (parent + children) peak resident memory and CPU, peak
Postgres connections held by the app role (pool usage) and - when
pg_stat_statements is installed and --admin-db-url can reset it - the
queries that took the most total time. Results go to --out as JSON; a
summary is printed.
"""
import argparse
import asyncio
import io
import json
import os
import statistics
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import httpx
import psutil
import psycopg2

from scripts.load_test import SCREENS, percentile, sign_in

ASSISTANT_QUESTIONS = {
    "en": ["What were my best selling products last month?", "Which products are low on stock?",
           "How are my sales trending this month compared to last month?", "Which competitor is cheapest for olive oil?"],
    "ar": ["شو أكثر منتج بعته الشهر الماضي؟", "أي المنتجات مخزونها قليل؟",
           "كيف مبيعاتي هالشهر مقارنة بالشهر الماضي؟", "مين أرخص منافس بزيت الزيتون؟"],
}


class ProcessSampler:
    """Samples the API process tree (resident memory, CPU) and Postgres
    connections held by the app role every `interval` seconds."""

    def __init__(self, pid, db_url, app_role, interval=0.5):
        self.proc = psutil.Process(pid) if pid else None
        self.db_url, self.app_role, self.interval = db_url, app_role, interval
        self.samples, self._stop = [], threading.Event()

    def _tree(self):
        procs = [self.proc] + self.proc.children(recursive=True)
        rss, cpu = 0, 0.0
        for p in procs:
            try:
                rss += p.memory_info().rss
                cpu += p.cpu_percent(None)
            except psutil.Error:
                pass
        return rss / 2**20, cpu, len(procs)

    def _run(self):
        conn = psycopg2.connect(self.db_url) if self.db_url else None
        if conn:
            conn.autocommit = True
        while not self._stop.is_set():
            rss, cpu, nprocs = self._tree() if self.proc else (0, 0, 0)
            held = None
            if conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE usename = %s;", (self.app_role,))
                    held = cur.fetchone()[0]
            self.samples.append((rss, cpu, nprocs, held))
            self._stop.wait(self.interval)
        if conn:
            conn.close()

    def __enter__(self):
        if self.proc:
            for p in [self.proc] + self.proc.children(recursive=True):
                p.cpu_percent(None)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()

    def summary(self):
        if not self.samples:
            return {}
        rss = [s[0] for s in self.samples]
        cpu = [s[1] for s in self.samples]
        held = [s[3] for s in self.samples if s[3] is not None]
        return {"rss_mb_peak": round(max(rss)), "rss_mb_end": round(rss[-1]),
                "cpu_pct_mean": round(statistics.mean(cpu)), "cpu_pct_peak": round(max(cpu)),
                "processes_peak": max(s[2] for s in self.samples),
                "db_connections_peak": max(held) if held else None}


def stats(samples):
    """samples: list of (seconds, ok)."""
    times = [t for t, _ in samples]
    return {"n": len(samples), "errors": sum(1 for _, ok in samples if not ok),
            "p50_ms": round(statistics.median(times) * 1000), "p95_ms": round(percentile(times, 95) * 1000),
            "max_ms": round(max(times) * 1000)}


def top_queries(admin_url, limit=10):
    try:
        with psycopg2.connect(admin_url) as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT calls, round(total_exec_time::numeric, 1), round(mean_exec_time::numeric, 2),
                       regexp_replace(left(query, 160), '\\s+', ' ', 'g')
                FROM pg_stat_statements WHERE query NOT ILIKE '%%pg_stat%%'
                ORDER BY total_exec_time DESC LIMIT %s;""", (limit,))
            return [{"calls": c, "total_ms": float(t), "mean_ms": float(m), "query": q} for c, t, m, q in cur.fetchall()]
    except psycopg2.Error:
        return None


def reset_queries(admin_url):
    try:
        with psycopg2.connect(admin_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_stat_statements_reset();")
    except psycopg2.Error:
        pass


def timed(client, method, path, ok_statuses=(200,), **kw):
    started = time.monotonic()
    try:
        r = client.request(method, path, **kw)
        return time.monotonic() - started, r.status_code in ok_statuses, r
    except httpx.HTTPError:
        return time.monotonic() - started, False, None


def phase_endpoints(client, headers, repeat):
    out = {}
    for path in SCREENS:
        out[path.split("?")[0]] = stats([timed(client, "GET", path, headers=headers)[:2] for _ in range(repeat)])
    return out


def phase_dashboard_visit(api, headers, repeat):
    """What a person waits for when opening the dashboard right after their
    data changed: a write (marking alerts read) first, then the Command
    Center and the alerts bell requested at the same moment, as the page
    does. "ready" is when both have answered."""
    async def visit(client):
        await client.post("/alerts/read", headers=headers)
        started = time.monotonic()

        async def get(path):
            r = await client.get(path, headers=headers)
            return time.monotonic() - started, r.status_code == 200

        (cc_t, cc_ok), (al_t, al_ok) = await asyncio.gather(get("/dashboard/command-center"), get("/alerts"))
        return cc_t, cc_ok, al_t, al_ok

    async def run():
        async with httpx.AsyncClient(base_url=api, timeout=60) as client:
            return [await visit(client) for _ in range(repeat)]

    rows = asyncio.run(run())
    return {"command_center": stats([(r[0], r[1]) for r in rows]), "alerts": stats([(r[2], r[3]) for r in rows]),
            "dashboard_ready": stats([(max(r[0], r[2]), r[1] and r[3]) for r in rows])}


def phase_assistant(client, headers):
    out = {}
    for lang, questions in ASSISTANT_QUESTIONS.items():
        samples, tokens = [], []
        for q in questions:
            t, ok, r = timed(client, "POST", "/rag/query", params={"query_text": q}, headers=headers, timeout=120)
            samples.append((t, ok and bool((r.json() or {}).get("answer"))))
            if ok:
                tokens.append((r.json().get("token_usage") or {}).get("total_tokens") or 0)
        out[lang] = {**stats(samples), "tokens_mean": round(statistics.mean(tokens)) if tokens else None}
    return out


def _xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["date", "product", "quantity", "unit_price"])
    for i in range(rows):
        ws.append([f"2026-09-{1 + i % 28:02d}", f"Item {i % 40}", 1 + i % 5, 2.5])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv(rows):
    lines = ["date,product,quantity,unit_price"] + [f"2026-08-{1 + i % 28:02d},Item {i % 60},{1 + i % 7},3.25" for i in range(rows)]
    return "\n".join(lines).encode()


def phase_files(client, headers, perf_headers, repeat):
    out = {}
    xlsx, csv = _xlsx(2000), _csv(10000)
    xlsx_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    out["upload_xlsx_2000_rows"] = stats([timed(client, "POST", "/extraction/upload", headers=perf_headers, timeout=300,
                                                files={"file": ("s.xlsx", xlsx, xlsx_type)})[:2] for _ in range(repeat)])
    out["upload_csv_10000_rows"] = stats([timed(client, "POST", "/extraction/upload", headers=perf_headers, timeout=300,
                                                files={"file": ("s.csv", csv, "text/csv")})[:2] for _ in range(repeat)])
    for fmt in ("pdf", "csv"):
        out[f"report_export_{fmt}"] = stats([timed(client, "GET", "/reports/sales/export", params={"format": fmt},
                                                   headers=headers, timeout=300)[:2] for _ in range(repeat)])
    return out


def phase_forecast(client, headers):
    """A full re-forecast of every product with sales (all_products=true),
    timed from the request until the background job stops running."""
    started = time.monotonic()
    t, ok, r = timed(client, "POST", "/forecasting/refresh", params={"all_products": "true"}, headers=headers)
    status = {}
    while ok and time.monotonic() - started < 600:
        time.sleep(0.25)
        status = client.get("/forecasting/status", headers=headers).json()
        if status.get("state") != "running":
            break
    return {"seconds": round(time.monotonic() - started, 2), "state": status.get("state"),
            "products": status.get("total"), "failed": status.get("failed"),
            "started": (r.json() if r is not None and ok else {})}


async def _virtual_user(client, token, deadline, think, samples):
    import random
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < deadline:
        for path in SCREENS:
            if time.monotonic() >= deadline:
                return
            started = time.monotonic()
            try:
                status = (await client.get(path, headers=headers)).status_code
            except httpx.HTTPError:
                status = 0
            samples[path.split("?")[0]].append((time.monotonic() - started, status))
            await asyncio.sleep(random.uniform(0, think))


async def _load(api, tokens, users, seconds, think):
    limits = httpx.Limits(max_connections=users + 10, max_keepalive_connections=users + 10)
    samples = defaultdict(list)
    async with httpx.AsyncClient(base_url=api, timeout=60, limits=limits) as client:
        started = time.monotonic()
        await asyncio.gather(*(_virtual_user(client, tokens[i % len(tokens)], started + seconds, think, samples)
                               for i in range(users)))
        elapsed = time.monotonic() - started
    return samples, elapsed


def phase_load(api, tokens, level, seconds, think):
    samples, elapsed = asyncio.run(_load(api, tokens, level, seconds, think))
    flat = [s for v in samples.values() for s in v]
    ok = lambda s: 0 < s < 400  # noqa: E731
    result = {"users": level, "seconds": round(elapsed), "requests": len(flat), "rps": round(len(flat) / elapsed, 1),
              "rate_limited": sum(1 for _, s in flat if s == 429),
              **stats([(t, ok(s)) for t, s in flat])}
    result["per_endpoint"] = {p: stats([(t, ok(s)) for t, s in v]) for p, v in sorted(samples.items())}
    return result


def recovery(client, headers, sampler_pid):
    time.sleep(10)
    s = stats([timed(client, "GET", "/dashboard/command-center", headers=headers)[:2] for _ in range(10)])
    rss = None
    if sampler_pid:
        p = psutil.Process(sampler_pid)
        rss = round(sum(x.memory_info().rss for x in [p] + p.children(recursive=True)) / 2**20)
    return {"command_center_after_10s": s, "rss_mb": rss}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--pid", type=int, help="API (uvicorn) process id - its whole process tree is sampled")
    ap.add_argument("--accounts", nargs="+", required=True)
    ap.add_argument("--phases", default="endpoints,dashboard_visit,assistant,files,forecast,load")
    ap.add_argument("--repeat", type=int, default=20)
    ap.add_argument("--levels", nargs="+", type=int, default=[35])
    ap.add_argument("--load-seconds", type=int, default=60)
    ap.add_argument("--think", type=float, default=1.0)
    ap.add_argument("--admin-db-url", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--app-role", default="ceopro_app")
    ap.add_argument("--out")
    args = ap.parse_args()
    password = os.environ["PERF_PASSWORD"]
    phases = args.phases.split(",")
    api = args.api.rstrip("/")

    client = httpx.Client(base_url=api, timeout=120)
    tokens = asyncio.run(_sign_in_all(api, args.accounts, password))
    headers = {"Authorization": f"Bearer {tokens[0]}"}
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "api": api, "accounts": len(args.accounts),
              "cpu_count": psutil.cpu_count(), "phases": {}}

    def run(name, fn):
        reset_queries(args.admin_db_url)
        with ProcessSampler(args.pid, args.admin_db_url, args.app_role) as sampler:
            started = time.monotonic()
            data = fn()
        result["phases"][name] = {"result": data, "process": sampler.summary(),
                                  "wall_seconds": round(time.monotonic() - started, 1),
                                  "top_queries": top_queries(args.admin_db_url, 8)}
        print(f"\n== {name}: {json.dumps(result['phases'][name]['process'])}")
        print(json.dumps(data, indent=1, ensure_ascii=False)[:4000])

    if "endpoints" in phases:
        run("endpoints", lambda: phase_endpoints(client, headers, args.repeat))
    if "dashboard_visit" in phases:
        run("dashboard_visit", lambda: phase_dashboard_visit(api, headers, args.repeat))
    if "assistant" in phases:
        run("assistant", lambda: phase_assistant(client, headers))
    if "files" in phases:
        email = f"perf+{uuid.uuid4().hex[:8]}@keel-test.example"
        signup = client.post("/auth/signup", json={"full_name": "Perf Test", "business_name": "Perf Baseline Co", "email": email,
                                                    "country_code": "JO", "primary_currency": "JOD", "password": password + "x1"}).json()
        perf_headers = {"Authorization": f"Bearer {signup['access_token']}"}
        result["perf_company"] = {"email": email, "tenant_id": signup.get("tenant_id")}
        run("files", lambda: phase_files(client, headers, perf_headers, max(3, args.repeat // 5)))
    if "forecast" in phases:
        run("forecast", lambda: phase_forecast(client, headers))
    if "load" in phases:
        for level in args.levels:
            run(f"load_{level}", lambda lv=level: phase_load(api, tokens, lv, args.load_seconds, args.think))
            result["phases"][f"load_{level}"]["recovery"] = recovery(client, headers, args.pid)
            print("recovery:", result["phases"][f"load_{level}"]["recovery"])

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(result, f, indent=1, ensure_ascii=False)
        print(f"\nwritten {args.out}")


async def _sign_in_all(api, accounts, password):
    async with httpx.AsyncClient(base_url=api, timeout=60) as client:
        return [await sign_in(client, email, password) for email in accounts]


if __name__ == "__main__":
    main()
