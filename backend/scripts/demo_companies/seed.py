"""
Creates the demo/acceptance companies through the product's own public API,
exactly as real customers would: sign up, fill in the company profile and
target markets, add the catalogue, import 18 months of sales exports, record
competitor prices, import customer reviews and upload business documents.
Nothing is written to the database directly.

Run it against any deployment (local or hosted), then log in as any owner:

  python -m scripts.demo_companies.generate --out-dir /tmp/demo --end 2026-10-05
  python -m scripts.demo_companies.seed --api https://api.example.com --data-dir /tmp/demo \\
      --password 'Choose!AStrong1' [--email-pattern '{local}+{key}@yourdomain.com'] [--only zaytouna]

Re-running is safe: existing accounts are logged into instead of re-created,
imports are de-duplicated by the product, and products that already exist
are left untouched.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scripts.demo_companies.profiles import COMPANIES

DOCUMENTS_DIR = Path(__file__).parent / "documents"


class Client:
    def __init__(self, api: str):
        self.http = httpx.Client(base_url=api.rstrip("/"), timeout=600)
        self.headers = {}

    def request(self, method, path, expected=(200,), **kwargs):
        response = self.http.request(method, path, headers=self.headers, **kwargs)
        if response.status_code not in expected:
            # API bodies can contain registration codes, tokens, JWTs, or
            # echoed request data. Keep CI and seed-script errors secret-free.
            raise RuntimeError(f"API request failed (HTTP {response.status_code}).")
        return response.json() if response.content else None


def sign_in(client: Client, company, email: str, password: str) -> dict:
    login = client.http.post("/auth/login", json={"email": email, "password": password})
    if login.status_code == 200:
        data = login.json()
        created = False
    elif login.status_code == 401:
        signup = client.http.post("/auth/signup", json={
            "email": email, "password": password, "full_name": company.owner_name,
            "business_name": company.business_name, "country_code": company.country,
            "primary_currency": company.currency,
        })
        if signup.status_code == 202:
            raise RuntimeError("Registration is pending email verification; verify the address, then rerun the seed script.")
        if signup.status_code != 200:
            raise RuntimeError(f"Account registration failed (HTTP {signup.status_code}).")
        data = signup.json()
        created = True
    else:
        raise RuntimeError(f"Login failed (HTTP {login.status_code}).")
    client.headers = {"Authorization": f"Bearer {data['access_token']}"}
    return {"tenant_id": data.get("tenant_id"), "created": created}


def configure_company(client: Client, company):
    client.request("PATCH", "/settings/company", json={
        "business_type": company.business_type,
        "preferred_language": company.language if company.language in ("en", "ar") else "en",
        **({"industry_key": company.industry_key} if company.industry_key else {}),
    })
    if company.location:
        client.request("PATCH", "/settings/company/search-scope", json={
            "city": company.city, "latitude": company.location[0], "longitude": company.location[1],
            "search_scope_level": "CITY",
        })
    client.request("PUT", "/settings/company/target-markets", json={"target_markets": company.target_markets})


def create_catalog(client: Client, company) -> dict:
    existing = {}
    offset = 0
    while True:
        page = client.request("GET", "/products", params={"limit": 100, "offset": offset})
        for product in page["products"]:
            existing[product["product_name"]] = product["product_id"]
        offset += 100
        if offset >= page.get("total", 0):
            break
    ids = {}
    for product in company.products:
        if product.name_en in existing:
            ids[product.name_en] = existing[product.name_en]
            continue
        name = {"en": product.name_en}
        if product.name_local:
            name["ar"] = product.name_local
        current_price = product.price_history[-1][1]
        body = {
            "product_name": name, "category": {"en": product.category}, "current_price": current_price,
            "cost_price": product.cost, "currency": company.currency,
            "initial_stock_quantity": product.stock,  # None = stock not tracked (services, made to order)
        }
        if product.brand:
            body["brand"] = {"en": product.brand}
        created = client.request("POST", "/products", json=body)
        ids[product.name_en] = created["product_id"]
    return ids


def import_sales(client: Client, company_dir: Path, manifest: dict) -> list:
    results = []
    for file_name in manifest["sales_files"]:
        with open(company_dir / file_name, "rb") as f:
            started = time.time()
            data = client.request("POST", "/extraction/upload", files={"file": (file_name, f)})
        promotion = data.get("promotion") or {}
        results.append({
            "file": file_name, "seconds": round(time.time() - started, 1), "mode": data.get("template_mode"),
            "promoted": promotion.get("rows_promoted"), "duplicates": promotion.get("rows_duplicate"),
            "incomplete": promotion.get("rows_skipped_incomplete"), "failed": promotion.get("rows_failed"),
            "products_created": promotion.get("products_created"),
        })
        print(f"   {file_name}: {results[-1]}", flush=True)
    return results


def add_competitors(client: Client, company, product_ids: dict, now: datetime) -> list:
    tracked = {c["name"]: c["id"] for c in client.request("GET", "/competitors").get("competitors", [])}
    recorded = []
    for competitor in company.competitors:
        competitor_id = tracked.get(competitor.name)
        if competitor_id is None:
            competitor_id = client.request("POST", "/competitors", json={
                "name": competitor.name, "website_url": competitor.website,
                **({"competition_level": competitor.level} if competitor.level else {}),
            })["competitor_id"]
        elif competitor.level:
            client.request("PATCH", f"/competitors/{competitor_id}/level", json={"competition_level": competitor.level})
        existing = {(p["product_id"], p["price"]) for p in client.request("GET", f"/competitors/{competitor_id}/prices")["prices"]}
        for product_name, observations in competitor.observed_prices.items():
            for days_ago, price in observations:
                if (product_ids[product_name], price) in existing:
                    continue
                client.request("POST", f"/competitors/{competitor_id}/prices", json={
                    "product_id": product_ids[product_name], "price": price,
                    "observed_at": (now - timedelta(days=days_ago)).isoformat(),
                })
                recorded.append((competitor.name, product_name, price))
    return recorded


def import_reviews(client: Client, company_dir: Path) -> dict:
    with open(company_dir / "reviews.csv", "rb") as f:
        return client.request("POST", "/reviews/import", files={"file": ("customer_reviews.csv", f)})


def upload_documents(client: Client, company) -> list:
    already = {d["file_name"] for d in client.request("GET", "/rag/documents")["documents"]}
    results = []
    for path in sorted(DOCUMENTS_DIR.glob(f"{company.key}__*.pdf")):
        file_name = path.stem.split("__", 1)[1].replace("_", " ").title() + ".pdf"
        if file_name in already:
            continue
        with open(path, "rb") as f:
            data = client.request("POST", "/extraction/upload", files={"file": (file_name, f)})
        results.append((file_name, data.get("rag_document_status")))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--email-pattern", default="{local}@{key}.keel-demo.example")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()

    report = {}
    now = datetime.now(timezone.utc)
    for company in COMPANIES:
        if args.only and company.key not in args.only:
            continue
        email = args.email_pattern.format(local=company.email_local, key=company.key)
        company_dir = Path(args.data_dir) / company.key
        manifest = json.loads((company_dir / "manifest.json").read_text())
        client = Client(args.api)
        print(f"== {company.business_name} <{email}>", flush=True)
        account = sign_in(client, company, email, args.password)
        configure_company(client, company)
        product_ids = create_catalog(client, company)
        sales = import_sales(client, company_dir, manifest)
        competitors = add_competitors(client, company, product_ids, now)
        reviews = import_reviews(client, company_dir)
        documents = upload_documents(client, company)
        report[company.key] = {
            "email": email, "tenant_id": account["tenant_id"], "created": account["created"],
            "products": len(product_ids), "sales_files": sales, "competitor_prices_recorded": len(competitors),
            "reviews": reviews, "documents": documents,
        }
        print(json.dumps({k: v for k, v in report[company.key].items() if k != "sales_files"}, ensure_ascii=False), flush=True)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
