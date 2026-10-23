"""End-to-end demand forecast smoke using disposable local PostgreSQL/Redis and Chromium."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

import psycopg2


def wait_http(url, timeout=45):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"Disposable application did not become ready: {url}")


def main():
    os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
    from src.ai.core.security import hash_password

    database_url = os.environ["DATABASE_URL"]
    api_port, web_port = 18071, 15171
    email = f"demand-browser-{secrets.token_hex(6)}@example.test"
    password = f"Demand-{secrets.token_urlsafe(18)}-Aa9!"
    tenant, user, product = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    product_name = f"Forecast Browser Product {secrets.token_hex(4)}"
    app_process = web_process = None
    log_handles = []
    log_dir = tempfile.TemporaryDirectory(prefix="keel-demand-browser-")
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.update({
        "JWT_SECRET": env.get("JWT_SECRET") or secrets.token_urlsafe(48),
        "REQUIRE_EMAIL_VERIFICATION": "true",
        "VITE_API_BASE_URL": "/api",
        "KEEL_API_PROXY_TARGET": f"http://127.0.0.1:{api_port}",
        "FORECAST_BROWSER_EMAIL": email,
        "FORECAST_BROWSER_PASSWORD": password,
        "FORECAST_BROWSER_PRODUCT": product_name,
        "FORECAST_BROWSER_PRODUCT_ID": product,
        "APP_URL": f"http://127.0.0.1:{web_port}",
        "CHROMIUM_PATH": env.get("CHROMIUM_PATH") or str(Path.home() / "AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe"),
    })
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", api_port))
        sock.close()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", web_port))
        sock.close()
    try:
        with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,%s,'JO','JOD')",
                (tenant, "Disposable demand browser workspace"),
            )
            cur.execute(
                "INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(%s,%s,%s,%s,now())",
                (user, email, hash_password(password), "Demand Browser Owner"),
            )
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant, user))
            cur.execute(
                "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) VALUES(%s,'growth','active','manual')",
                (tenant,),
            )
            cur.execute(
                "INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) VALUES(%s,%s,%s::jsonb,10,'JOD')",
                (product, tenant, json.dumps({"en": product_name, "ar": product_name})),
            )
            # Actual canonical PAID invoice rows are the forecasting source. They are
            # synthetic test sales, never provider staging or inventory observations.
            now = datetime.now(timezone.utc)
            for offset in range(1, 121):
                invoice_id = str(uuid.uuid4())
                amount = 5 * 10
                cur.execute(
                    "INSERT INTO invoices(invoice_id,tenant_id,invoice_number,issue_date,subtotal,total_amount,currency,payment_status) "
                    "VALUES(%s,%s,%s,%s,%s,%s,'JOD','PAID')",
                    (invoice_id, tenant, f"DBR-{invoice_id[:12]}", now - timedelta(days=offset), amount, amount),
                )
                cur.execute(
                    "INSERT INTO invoice_items(tenant_id,invoice_id,product_id,quantity,unit_price,total_price) "
                    "VALUES(%s,%s,%s,5,10,50)",
                    (tenant, invoice_id, product),
                )
            cur.execute("SELECT plan_key FROM usage_plan_entitlements WHERE plan_key='growth' AND feature_code='demand_prediction'")
            if cur.fetchone() is None:
                raise RuntimeError("Growth plan fixture does not include the established demand_prediction grant")

        app_log = open(Path(log_dir.name) / "api.log", "w", encoding="utf-8")
        web_log = open(Path(log_dir.name) / "web.log", "w", encoding="utf-8")
        log_handles.extend((app_log, web_log))
        app_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.ai.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=root / "backend", env=env, stdout=app_log, stderr=app_log,
        )
        web_process = subprocess.Popen(
            ["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
            cwd=root / "frontend", env=env, stdout=web_log, stderr=web_log,
        )
        wait_http(f"http://127.0.0.1:{api_port}/health/ready")
        wait_http(f"http://127.0.0.1:{web_port}/login")
        # Complete the existing guided setup through its authenticated owner API
        # before the forecast journey. This keeps the fixture's account state
        # truthful while isolating the browser test to its approved feature.
        login_request = Request(
            f"http://127.0.0.1:{api_port}/auth/login",
            data=json.dumps({"email": email, "password": password}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(login_request, timeout=15) as response:
            token = json.loads(response.read())["access_token"]
        complete_request = Request(
            f"http://127.0.0.1:{api_port}/settings/company/onboarding/complete",
            data=b"", headers={"Authorization": f"Bearer {token}"}, method="POST",
        )
        with urlopen(complete_request, timeout=15) as response:
            if response.status != 200 or not json.loads(response.read()).get("onboarding_completed_at"):
                raise RuntimeError("Existing authenticated onboarding completion endpoint did not initialize the test workspace")
        browser = subprocess.run(
            ["node", "tests/browser/demand-prediction.mjs"], cwd=root / "frontend", env=env,
            check=False,
        )
        if browser.returncode:
            raise RuntimeError(f"Chromium demand workflow failed with exit {browser.returncode}")
        with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*),max(expected_demand) FROM demand_forecasts WHERE tenant_id=%s AND product_id=%s", (tenant, product))
            count, expected = cur.fetchone()
            if count != 1 or expected is None:
                raise RuntimeError(f"Expected one durable forecast, found {count}")
        print("FASTAPI health/ready: PASS; authenticated Chromium demand workflow: English desktop + Arabic RTL mobile: 2/2 PASS")
        print("Post-browser PostgreSQL check: exactly one durable demand_forecasts row for the seeded tenant/product")
    finally:
        for process in (web_process, app_process):
            if process:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for handle in log_handles:
            handle.close()
        try:
            with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM invoice_items WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM invoices WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM demand_forecasts WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM evidence_records WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM products WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM tenant_plan_assignments WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM tenant_users WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM companies WHERE tenant_id=%s", (tenant,))
                cur.execute("DELETE FROM users WHERE user_id=%s", (user,))
        finally:
            log_dir.cleanup()


if __name__ == "__main__":
    main()
