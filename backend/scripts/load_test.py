"""
Load test: many people from several companies using the app at once.

Each virtual user signs in as one of the given accounts and, until the time
is up, opens the main screens' data in the order a person would (Command
Center, products, sales report, pricing, demand, competitors, alerts, ...),
with a short pause between screens. At the end it prints, per endpoint, the
number of requests, errors and response times (median, 95th percentile,
slowest), and overall requests per second.

  python -m scripts.load_test --api http://localhost:8000 --password '...' \\
      --accounts rania@zaytouna.keel-demo.example mostafa@bytefix.keel-demo.example \\
      --users 40 --duration 120

Run it against a test environment only. The API's per-company rate limit
(core/rate_limit.py) will answer 429 once one company's users go past it;
those count as "limited", not errors. Set API_RATE_LIMIT_ENABLED=false on
the server to measure raw capacity instead.
"""
import argparse
import asyncio
import random
import statistics
import time
from collections import defaultdict

import httpx

SCREENS = [
    "/dashboard/command-center",
    "/products?limit=50",
    "/reports/sales?limit=50",
    "/reports/financial-summary",
    "/dashboard/metrics",
    "/competitors",
    "/forecasting/overview",
    "/discovery/competitors?limit=100",
    "/alerts",
    "/settings/company",
]


async def sign_in(client: httpx.AsyncClient, email: str, password: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


async def user(client, token, deadline, think, stats):
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < deadline:
        for path in SCREENS:
            if time.monotonic() >= deadline:
                return
            started = time.monotonic()
            try:
                response = await client.get(path, headers=headers)
                status = response.status_code
            except httpx.HTTPError:
                status = 0
            stats[path.split("?")[0]].append((time.monotonic() - started, status))
            await asyncio.sleep(random.uniform(0, think))


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--accounts", nargs="+", required=True)
    parser.add_argument("--users", type=int, default=40)
    parser.add_argument("--duration", type=int, default=120, help="seconds")
    parser.add_argument("--think", type=float, default=1.0, help="longest pause between screens, seconds")
    args = parser.parse_args()

    limits = httpx.Limits(max_connections=args.users + 10, max_keepalive_connections=args.users + 10)
    async with httpx.AsyncClient(base_url=args.api.rstrip("/"), timeout=60, limits=limits) as client:
        tokens = [await sign_in(client, email, args.password) for email in args.accounts]
        stats = defaultdict(list)
        started = time.monotonic()
        deadline = started + args.duration
        await asyncio.gather(*(user(client, tokens[i % len(tokens)], deadline, args.think, stats) for i in range(args.users)))
        elapsed = time.monotonic() - started

    total = sum(len(v) for v in stats.values())
    print(f"{args.users} users across {len(tokens)} companies for {elapsed:.0f}s: {total} requests, {total / elapsed:.1f}/s\n")
    print(f"{'endpoint':34} {'requests':>8} {'errors':>6} {'limited':>7} {'median':>8} {'p95':>8} {'slowest':>8}")
    worst_p95 = 0.0
    errors_total = 0
    for path, samples in sorted(stats.items()):
        times = [t for t, _ in samples]
        errors = sum(1 for _, s in samples if s == 0 or s >= 500 or (400 <= s < 500 and s != 429))
        limited = sum(1 for _, s in samples if s == 429)
        errors_total += errors
        p95 = percentile(times, 95)
        worst_p95 = max(worst_p95, p95)
        print(f"{path:34} {len(samples):8} {errors:6} {limited:7} {statistics.median(times) * 1000:7.0f}ms {p95 * 1000:7.0f}ms {max(times) * 1000:7.0f}ms")
    print(f"\nerrors: {errors_total}; slowest endpoint p95: {worst_p95 * 1000:.0f}ms")


if __name__ == "__main__":
    asyncio.run(main())
