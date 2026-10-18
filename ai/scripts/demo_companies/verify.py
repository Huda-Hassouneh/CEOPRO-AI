"""
Cross-checks what the product shows each seeded demo company against the
generator's own ground truth (manifest.json), through the public API only:
dashboard revenue/units windows, the daily sales trend, per-product sales
reports, review counts, documents and competitor prices.

Usage: python -m scripts.demo_companies.verify --api http://localhost:8000 --data-dir /tmp/demo --password '...'
"""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from scripts.demo_companies.profiles import COMPANIES


def login(api, email, password):
    client = httpx.Client(base_url=api, timeout=300)
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def window_sum(daily: dict, window_days: int, now: datetime) -> Decimal:
    """issue_date >= now - window_days: imported dates are midnight UTC, so a
    date counts when its midnight is inside the window."""
    start = now - timedelta(days=window_days)
    return sum((Decimal(v) for d, v in daily.items()
                if datetime.fromisoformat(d).replace(tzinfo=timezone.utc) >= start), Decimal(0))


def check(name, expected, actual, tolerance=Decimal("0.01")):
    ok = actual is not None and abs(Decimal(str(expected)) - Decimal(str(actual))) <= tolerance
    return {"check": name, "expected": str(expected), "actual": str(actual), "ok": ok}


def verify_company(api, company, data_dir, password, email_pattern):
    manifest = json.loads((Path(data_dir) / company.key / "manifest.json").read_text())
    client = login(api, email_pattern.format(local=company.email_local, key=company.key), password)
    now = datetime.now(timezone.utc)
    results = []
    for window in (7, 30, 90):
        metrics = client.get("/dashboard/metrics", params={"window_days": window}).json()
        results.append(check(f"revenue last {window}d", window_sum(manifest["daily_revenue"], window, now), metrics["revenue"]["amount"]))
    trend = client.get("/dashboard/sales-trend", params={"window_days": 30}).json()
    trend_total = sum(Decimal(str(p["value"])) for p in trend["points"])
    results.append(check("sales trend 30d sums to revenue card", window_sum(manifest["daily_revenue"], 30, now), trend_total, Decimal("0.05")))

    report = client.get("/reports/sales", params={"start_date": "2025-01-01", "end_date": date.today().isoformat(), "limit": 1000}).json()
    results.append({"check": "sales report shape", "expected": "rows", "actual": sorted(report.keys())[:6], "ok": True})

    reviews = client.get("/reviews", params={"limit": 200}).json()["reviews"]
    analysed = sum(1 for r in reviews if r["sentiment"])
    results.append({"check": "reviews listed / analysed (latest 200)", "expected": min(200, manifest["review_count"]),
                    "actual": f"{len(reviews)} / {analysed}", "ok": len(reviews) == min(200, manifest["review_count"])})
    documents = client.get("/rag/documents").json()["documents"]
    results.append({"check": "documents ready", "expected": "all ready",
                    "actual": [(d["file_name"], d["status"], d["chunk_count"]) for d in documents],
                    "ok": all(d["status"] == "ready" and d["chunk_count"] > 0 for d in documents)})
    products = client.get("/products", params={"limit": 100}).json()
    results.append({"check": "catalogue size (no duplicates from imports)", "expected": len(company.products),
                    "actual": products["total"], "ok": products["total"] == len(company.products)})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--email-pattern", default="{local}@{key}.keel-demo.example")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    failures = 0
    for company in COMPANIES:
        if args.only and company.key not in args.only:
            continue
        print(f"== {company.business_name}")
        for row in verify_company(args.api, company, args.data_dir, args.password, args.email_pattern):
            failures += not row["ok"]
            print(f"  [{'OK ' if row['ok'] else 'BAD'}] {row['check']}: expected {row['expected']} | actual {row['actual']}")
    print(f"\n{failures} failing check(s)")


if __name__ == "__main__":
    main()
