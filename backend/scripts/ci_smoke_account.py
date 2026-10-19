"""
Creates one company that has finished setup, for the browser smoke test
(frontend/tests/browser/smoke.mjs) in CI. Uses the same public API calls as
scripts/demo_companies/seed.py - sign-up, company profile, target markets,
catalogue, competitor prices - but skips the sales, review and document
imports, which need object storage and the ML models. Every screen then has
real products and competitors to show; the rest shows its empty state.

  python -m scripts.ci_smoke_account --api http://localhost:8000 --email ci@example.com --password '...'

Re-running is safe: an existing account is signed into instead.
"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone

from scripts.demo_companies.profiles import COMPANIES
from scripts.demo_companies.seed import Client, add_competitors, configure_company, create_catalog, sign_in


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--company", default="zaytouna")
    args = parser.parse_args()

    company = next(c for c in COMPANIES if c.key == args.company)
    company = replace(company, products=company.products[:10])
    client = Client(args.api)
    account = sign_in(client, company, args.email, args.password)
    configure_company(client, company)
    product_ids = create_catalog(client, company)
    names = set(product_ids)
    company = replace(company, competitors=[
        replace(c, observed_prices={p: obs for p, obs in c.observed_prices.items() if p in names}) for c in company.competitors
    ])
    prices = add_competitors(client, company, product_ids, datetime.now(timezone.utc))
    client.request("POST", "/settings/company/onboarding/complete")
    print(f"{company.business_name}: tenant {account['tenant_id']}, {len(product_ids)} products, "
          f"{len(company.competitors)} competitors, {len(prices)} competitor prices", flush=True)


if __name__ == "__main__":
    main()
