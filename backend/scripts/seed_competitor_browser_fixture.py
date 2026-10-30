"""Create an isolated tenant and real competitor/product records for Chromium smoke checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import uuid
from urllib.request import Request, urlopen

import psycopg2

from src.ai.core.security import hash_password


API = os.environ.get("KEEL_VERIFY_API_URL", "http://127.0.0.1:8000")
STATE = Path(os.environ.get("KEEL_VERIFICATION_STATE", Path.home() / "AppData/Local/KEEL/verification"))


def _request(path: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{API}{path}", data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read())


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    suffix = secrets.token_hex(5).upper()
    email = f"keel-competitor-{suffix.lower()}@example.test"
    password = f"Local-Test-{secrets.token_urlsafe(20)}-A9!"
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    marker = f"KEEL-COMP-{suffix}"
    with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency,city,industry_key,onboarding_completed_at) "
            "VALUES(%s,%s,'JO','JOD','Amman','bakery',now())",
            (tenant_id, f"{marker} Bakery"),
        )
        cur.execute(
            "INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(%s,%s,%s,%s,now())",
            (user_id, email, hash_password(password), "KEEL Verification Owner"),
        )
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant_id, user_id))
        cur.execute(
            "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source) "
            "VALUES(%s,'growth','active',current_date,current_date+30,'manual')",
            (tenant_id,),
        )

    login = _request("/auth/login", {"email": email, "password": password})
    token = login.get("access_token") or login.get("token")
    if not token:
        raise RuntimeError("Login response did not include an access token.")
    product = _request("/products", {
        "product_name": {"en": f"{marker} Kunafa", "ar": f"{marker} كنافة"},
        "current_price": 9.5, "currency": "JOD",
    }, token)
    product_id = product.get("product_id") or product.get("product", {}).get("product_id")
    if not product_id:
        raise RuntimeError(f"Product endpoint returned no product identity: {product}")
    competitor = _request("/competitors", {
        "name": f"{marker} Rival Bakery", "website_url": "https://example.test",
        "competition_level": "PRODUCT", "product_ids": [product_id],
    }, token)
    competitor_id = competitor.get("competitor_id")
    if not competitor_id:
        raise RuntimeError(f"Competitor endpoint returned no identity: {competitor}")
    price = _request(f"/competitors/{competitor_id}/prices", {
        "product_id": product_id, "price": 8.75, "currency": "JOD",
        "product_url": "https://example.test/kunafa",
    }, token)
    fixture = {
        "email": email, "password": password, "tenant_id": tenant_id,
        "product_id": product_id, "competitor_id": competitor_id,
        "competitor_name": f"{marker} Rival Bakery", "marker": marker,
        "product_response": product, "competitor_response": competitor, "price_response": price,
    }
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / "competitor-browser-fixture.json"
    path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(f"Synthetic browser fixture prepared for {email}; IDs and password are stored outside Git at {path}.")


if __name__ == "__main__":
    main()
