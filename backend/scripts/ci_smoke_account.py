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
import os
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlparse
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.demo_companies.profiles import COMPANIES
from scripts.demo_companies.seed import Client, add_competitors, configure_company, create_catalog


def _verify_synthetic_account(client: Client, company, email: str, password: str) -> dict:
    """Create a CI-only account through signup and email verification, in memory.

    This fixture is deliberately restricted to a loopback API and a reserved
    synthetic email domain. Production email verification remains enabled.
    The intercepted verification code and registration token never leave this
    process and are never printed or persisted.
    """
    parsed = urlparse(str(client.http.base_url))
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Synthetic email verification requires a loopback HTTP API.")
    domain = email.rsplit("@", 1)[-1].casefold() if "@" in email else ""
    if not (domain.endswith(".example") or domain.endswith(".test")):
        raise RuntimeError("Synthetic email verification requires a reserved .example or .test address.")

    login = client.http.post("/auth/login", json={"email": email, "password": password})
    if login.status_code == 200:
        data = login.json()
        client.headers = {"Authorization": f"Bearer {data['access_token']}"}
        return {"tenant_id": data.get("tenant_id"), "created": False}
    if login.status_code != 401:
        raise RuntimeError(f"Login failed (HTTP {login.status_code}).")

    from src.ai.core import notifications
    from src.ai.routers import auth

    captured_codes = {}

    def capture_verification_code(recipient: str, code: str) -> bool:
        if recipient.casefold() == email.casefold():
            captured_codes[recipient.casefold()] = code
            return True
        return False

    fixture_app = FastAPI()
    fixture_app.include_router(auth.router)
    signup_payload = {
        "email": email,
        "password": password,
        "full_name": company.owner_name,
        "business_name": company.business_name,
        "country_code": company.country,
        "primary_currency": company.currency,
    }
    # Keep the real verification requirement on. Only the mail transport is
    # replaced, as in test_email_verification_integration_db.py.
    with patch.dict(os.environ, {"REQUIRE_EMAIL_VERIFICATION": "true"}), patch.object(
        notifications, "send_email_verification_email", capture_verification_code
    ), TestClient(fixture_app) as verification_client:
        signup = verification_client.post("/auth/signup", json=signup_payload)
        if signup.status_code != 202:
            raise RuntimeError(f"Synthetic account registration failed (HTTP {signup.status_code}).")
        registration = signup.json()
        code = captured_codes.get(email.casefold())
        registration_token = registration.get("registration_token")
        if registration.get("status") != "pending_verification" or not code or not registration_token:
            raise RuntimeError("Synthetic registration did not produce the expected verification challenge.")
        verified = verification_client.post("/auth/email/verify", json={
            "email": email,
            "registration_token": registration_token,
            "code": code,
        })
        if verified.status_code != 200 or verified.json().get("email_verified") is not True:
            raise RuntimeError(f"Synthetic email verification failed (HTTP {verified.status_code}).")

    # Exercise the actual running API's login contract after verified account
    # state has been committed by the same isolated database.
    login = client.http.post("/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        raise RuntimeError(f"Verified-account login failed (HTTP {login.status_code}).")
    data = login.json()
    if data.get("email_verified") is not True or not data.get("access_token"):
        raise RuntimeError("Verified-account login returned an incomplete session.")
    client.headers = {"Authorization": f"Bearer {data['access_token']}"}
    return {"tenant_id": data.get("tenant_id"), "created": True}


def _sign_in_existing_account(client: Client, email: str, password: str) -> dict:
    login = client.http.post("/auth/login", json={"email": email, "password": password})
    if login.status_code != 200:
        raise RuntimeError(f"A pre-verified account is required (login returned HTTP {login.status_code}).")
    data = login.json()
    if data.get("email_verified") is not True or not data.get("access_token"):
        raise RuntimeError("Login did not return a verified session.")
    client.headers = {"Authorization": f"Bearer {data['access_token']}"}
    return {"tenant_id": data.get("tenant_id"), "created": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--company", default="zaytouna")
    parser.add_argument(
        "--test-email-verification-fixture",
        action="store_true",
        help="Capture the verification code in memory for a loopback CI/test account only.",
    )
    args = parser.parse_args()

    company = next(c for c in COMPANIES if c.key == args.company)
    company = replace(company, products=company.products[:10])
    client = Client(args.api)
    account = (
        _verify_synthetic_account(client, company, args.email, args.password)
        if args.test_email_verification_fixture
        else _sign_in_existing_account(client, args.email, args.password)
    )
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
