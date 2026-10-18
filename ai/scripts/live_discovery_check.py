"""
A real competitor scan through KEEL's own API, against the live public
sources - for checking discovery somewhere with normal internet access
(GitHub Actions: .github/workflows/live-discovery-check.yml, or a Codespace).

It signs up a fresh company (a bakery & sweets shop in Amman, Jordan by
default - city only, no map pin), adds two of its products, starts a scan
exactly as the Competitors page's "Find competitors" button does, waits
for it, and prints what each source answered and every competitor found
with its source links. It adds no competitor itself and uses no fixtures:
everything listed came back from the sources.

  python -m scripts.live_discovery_check --api http://localhost:8000 --out result.json
"""
import argparse
import json
import os
import sys
import time
import uuid

import httpx


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--city", default="Amman")
    parser.add_argument("--country", default="JO")
    parser.add_argument("--industry", default="")
    parser.add_argument("--business-type", default="Bakery and Arabic sweets")
    parser.add_argument("--products", default="Kunafa,Baklava")
    parser.add_argument("--currency", default="JOD")
    parser.add_argument("--email", default=None)
    parser.add_argument("--password", default="Live!Discovery-Check-2026")
    parser.add_argument("--out", default=None)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    http = httpx.Client(base_url=args.api.rstrip("/"), timeout=120)
    email = args.email or f"live-discovery+{uuid.uuid4().hex[:8]}@keel-ci.example"
    signup = http.post("/auth/signup", json={"email": email, "password": args.password, "full_name": "Live Check",
                                             "business_name": "Live Check Business", "country_code": args.country,
                                             "primary_currency": args.currency})
    if signup.status_code not in (200, 201):
        print(f"signup failed: {signup.status_code} {signup.text[:300]}")
        return 2
    http.headers["Authorization"] = f"Bearer {signup.json()['access_token']}"

    def call(method, path, **kwargs):
        response = http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else None

    # No --industry: KEEL decides from the business type, as for a company
    # that never picked one (a type outside its list is searched by its own words).
    settings = {"business_type": args.business_type}
    if args.industry:
        settings["industry_key"] = args.industry
    call("PATCH", "/settings/company", json=settings)
    call("PATCH", "/settings/company/search-scope", json={"city": args.city, "search_scope_level": "CITY"})
    # "Mansaf:6.5,Shawarma plate:3" - each product with the company's own price.
    for entry in [p.strip() for p in args.products.split(",") if p.strip()]:
        name, _sep, price = entry.partition(":")
        call("POST", "/products", json={"product_name": {"en": name.strip()}, "current_price": float(price or 3.5),
                                        "currency": args.currency, "category": {"en": args.business_type[:40]}})
    call("POST", "/settings/company/onboarding/complete")

    status = call("GET", "/discovery/status")
    print(f"Company: {args.business_type}, city {status['location']['city']} ({args.country}), industry "
          f"{status['industry']['key']} ({status['industry']['label']['en']}, decided by {status['industry']['decided_by']}), "
          f"search words {status['keywords']}, no map pin given")
    started = time.time()
    run = call("POST", "/discovery/runs", json={})
    while True:
        run = call("GET", f"/discovery/runs/{run['run_id']}")
        if run["status"] not in ("queued", "running") or time.time() - started > args.timeout:
            break
        time.sleep(5)
    print(f"\nScan finished in {time.time() - started:.0f}s: status={run['status']} error={run.get('error')} "
          f"found={run.get('found_count')} new={run.get('new_count')} tracked={run.get('tracked_count')} "
          f"searches/pages checked={run.get('sources_checked')} answered={run.get('sources_answered')}")
    print(f"Search centre used: {run.get('center_latitude')}, {run.get('center_longitude')} radius {run.get('radius_km')} km")
    for kind, result in (run.get("providers") or {}).items():
        print(f"  source {kind:18s} {result.get('status'):8s} found={result.get('found')} reason={result.get('reason')}")

    coverage = run.get("coverage") or {}
    print("\nWhat the scan produced (coverage):")
    print(json.dumps({k: v for k, v in coverage.items() if k != "examples"}, ensure_ascii=False, indent=1))
    for example in coverage.get("examples") or []:
        print(f"  matched: your '{example['product']}' = their '{example['item']}' {example['price']} {example['currency']} "
              f"(score {example['score']}) {example['source_url']}")
    listing = call("GET", "/discovery/competitors", params={"limit": 500})
    competitors = listing.get("competitors") or []
    print(f"\nCompetitors saved and listed by GET /discovery/competitors: {len(competitors)}")
    print("By relationship:", listing.get("counts", {}).get("by_relationship"))
    with_items = [c for c in competitors if (c.get("website_read") or {}).get("products")]
    print(f"\nCompetitors with products read from their website: {len(with_items)}")
    for c in with_items[:15]:
        read = c["website_read"]
        print(f"  - {c['name']} [{c.get('relationship')}] {c.get('website_url')}: {read['products']} items, {read['prices']} priced, "
              f"{c.get('matched_prices', 0)} matched to our products")
    for c in with_items[:6]:
        detail = call("GET", f"/discovery/competitors/{c['competitor_id']}")
        items = (detail.get("intel") or {}).get("products") or []
        print(f"    sample from {c['name']}:")
        for item in items[:8]:
            print(f"      {item.get('section') or '-'} > {item['name']} | {item.get('price')} {item.get('currency')}"
                  f"{' (currency inferred)' if item.get('currency_inferred') else ''} | {item.get('source_url')}")
    statuses = {}
    for c in competitors:
        status = (c.get("website_read") or {}).get("status")
        if status:
            statuses[status] = statuses.get(status, 0) + 1
    print("Website read outcomes:", statuses)
    print("\nFirst 40 competitors (relationship, reason, links):")
    for c in competitors[:40]:
        links = ", ".join(f"{s['label']}: {s.get('url') or '-'}" for s in c.get("sources") or [])
        distance = f"{c['distance_km']} km" if c.get("distance_km") is not None else "-"
        why = next((r for r in c.get("reasons") or [] if r.get("code") not in ("relationship", "distance", "sources", "branches", "reviews")), {})
        print(f"- {c['name']}{' / ' + c['name_ar'] if c.get('name_ar') else ''} | {c.get('relationship')} ({why.get('code')}"
              f"{': ' + str(why.get('term')) if why.get('term') else ''}) | {distance} | "
              f"{'tracked' if c['is_tracked'] else 'suggested'} | website {c.get('website_url') or '-'} "
              f"[{(c.get('website_read') or {}).get('status') or 'not read'}] | {links}")
    news = call("GET", "/discovery/news", params={"limit": 10}).get("articles") or []
    if news:
        print(f"\nNews found: {len(news)}")
        for article in news[:10]:
            print(f"- {article['title']} ({article.get('source_domain')}, {article.get('published_at')}) {article['url']}")

    structure = call("GET", "/discovery/market/structure")
    print("\nMarket structure:", json.dumps({k: structure[k] for k in ("businesses", "by_relationship", "chains", "websites")}, ensure_ascii=False))
    for row in structure.get("product_prices") or []:
        print(f"  {row['product']}: yours {row['your_price']} {row['currency']} vs {row['count']} competitors "
              f"{row['min']}-{row['max']} (median {row['median']}) -> {row['position']}")
        for p in row["prices"][:4]:
            print(f"      {p['competitor']}: {p['price']} {row['currency']} {p['source_url']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"email": email, "status": status, "run": run, "competitors": competitors, "news": news}, handle,
                      ensure_ascii=False, indent=2, default=str)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"## Live competitor scan: {args.business_type}, {args.city} ({args.country})\n\n")
            handle.write(f"Status **{run['status']}**, {len(competitors)} competitors listed, "
                         f"{run.get('sources_answered')}/{run.get('sources_checked')} searches and pages answered.\n\n")
            handle.write("| Source | Status | Found | Reason |\n|---|---|---|---|\n")
            for kind, result in (run.get("providers") or {}).items():
                handle.write(f"| {kind} | {result.get('status')} | {result.get('found')} | {result.get('reason') or ''} |\n")
            handle.write("\n| Competitor | Distance km | Sources |\n|---|---|---|\n")
            for c in competitors:
                links = " ".join(f"[{s['label']}]({s['url']})" if s.get("url") else s["label"] for s in c.get("sources") or [])
                handle.write(f"| {c['name']} | {c.get('distance_km') if c.get('distance_km') is not None else ''} | {links} |\n")
    if args.email is None:
        print(f"\nSign in as {email} to see these results in the app.")
    return 0 if competitors else 1


if __name__ == "__main__":
    sys.exit(main())
