"""Disposable React/FastAPI billing journey using a local Stripe contract fixture.

This is test-only. It refuses non-local/non-test database URLs and does not
perform network calls to Stripe. Webhook bytes are signed and consumed by the
real Stripe SDK and billing router.
"""
import copy
import hashlib
import hmac
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import psycopg2
import uvicorn

from scripts.billing_verification import validate_test_environment


def main():
    if os.getenv("KEEL_SUBSCRIPTION_BROWSER_FIXTURE") != "YES":
        raise RuntimeError("Explicit disposable subscription fixture flag required")
    database_url = validate_test_environment(dict(os.environ), database=True)
    if os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_live_", "rk_live_")):
        raise RuntimeError("Live Stripe keys are refused")
    if os.getenv("APP_BASE_URL") != "http://127.0.0.1:15173":
        raise RuntimeError("Frontend fixture must use the isolated local port")

    from src.ai.core.security import hash_password
    from src.ai.billing import store, stripe_api

    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    email = f"sub-browser-{uuid.uuid4().hex[:12]}@example.test"
    password = f"Billing-{uuid.uuid4().hex[:16]}!aA9"
    price_id = f"price_test_browser_{uuid.uuid4().hex[:12]}"
    stripe_secret = os.environ["STRIPE_WEBHOOK_SECRET"]
    checkout_sessions = {}
    subscription_state = {"value": None}
    invoices = {}
    api_base = "http://127.0.0.1:15174"
    frontend_base = "http://127.0.0.1:15173"
    fixture_base = "http://127.0.0.1:15175"
    os.environ.setdefault("CORS_ALLOWED_ORIGINS", frontend_base)

    with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,%s,'JO','JOD')",
            (tenant_id, f"Browser subscription {tenant_id[:8]}"),
        )
        cur.execute(
            "INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(%s,%s,%s,%s,now())",
            (user_id, email, hash_password(password), "Subscription Browser Owner"),
        )
        cur.execute(
            "INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",
            (tenant_id, user_id),
        )
        cur.execute(
            "UPDATE billing_plan_prices SET stripe_price_id=%s WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL",
            (price_id,),
        )
        if cur.rowcount != 1:
            raise RuntimeError("Expected one current public growth monthly price")
        past = datetime.now(timezone.utc) - timedelta(days=30)
        trial = store.start_trial(conn, tenant_id, now=past, started_by_user_id=user_id, plan_key="growth")
        if not trial:
            raise RuntimeError("Could not seed the user's consumed trial through the existing billing authority")
        conn.commit()

    def send_event(event_type, obj):
        event = {
            "id": f"evt_browser_{uuid.uuid4().hex}", "object": "event", "type": event_type,
            "created": int(time.time()), "data": {"object": obj}, "livemode": False,
        }
        payload = json.dumps(event, separators=(",", ":")).encode()
        timestamp = int(time.time())
        digest = hmac.new(stripe_secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
        req = Request(api_base + "/billing/webhook", data=payload, method="POST", headers={
            "Content-Type": "application/json", "Stripe-Signature": f"t={timestamp},v1={digest}",
        })
        with urlopen(req, timeout=15) as response:
            result = json.loads(response.read())
            if response.status != 200 or result.get("duplicate") is not False:
                raise RuntimeError(f"Fixture event was not processed: {event_type}")

    class CheckoutHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            if self.path == "/portal/session":
                body = (
                    "<!doctype html><html><head><title>Stripe customer portal test fixture</title></head>"
                    "<body><main><h1>Stripe customer portal test fixture</h1>"
                    f"<a href='{frontend_base}/billing'>Return to KEEL</a></main></body></html>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            session_id = self.path.removeprefix("/checkout/")
            session = checkout_sessions.get(session_id)
            if not session:
                self.send_error(404)
                return
            body = (
                "<!doctype html><html><head><title>Stripe test checkout fixture</title></head>"
                "<body><main><h1>Stripe test checkout</h1><p>Disposable local payment fixture.</p>"
                f"<form method='post' action='/checkout/{session_id}'><button type='submit'>Complete test payment</button></form>"
                "</main></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            session_id = self.path.removeprefix("/checkout/")
            session = checkout_sessions.get(session_id)
            if not session:
                self.send_error(404)
                return
            now = int(time.time())
            sub_id = f"sub_browser_{uuid.uuid4().hex[:16]}"
            customer_id = session["params"]["customer"]
            sub = {
                "id": sub_id, "object": "subscription", "customer": customer_id, "status": "active",
                "cancel_at_period_end": False, "canceled_at": None, "trial_end": None, "schedule": None,
                "metadata": {"tenant_id": tenant_id, "plan_key": "growth", "period_code": "monthly"},
                "items": {"data": [{"id": f"si_{uuid.uuid4().hex[:8]}", "price": {"id": price_id},
                                     "current_period_start": now, "current_period_end": now + 30 * 86400}]},
            }
            subscription_state["value"] = sub
            invoice_id = f"in_browser_{uuid.uuid4().hex[:16]}"
            invoice = {
                "id": invoice_id, "object": "invoice", "customer": customer_id, "subscription": sub_id,
                "status": "paid", "paid": True, "amount_paid": 14000, "amount_due": 14000,
                "currency": "usd", "metadata": {"tenant_id": tenant_id},
                "status_transitions": {"paid_at": now}, "hosted_invoice_url": "https://example.test/invoice",
                "invoice_pdf": None,
                "lines": {"data": [{"period": {"start": now, "end": now + 30 * 86400}}]},
            }
            invoices[invoice_id] = invoice
            session_obj = {
                "object": "checkout.session", "id": session_id, "mode": "subscription", "subscription": sub_id,
                "customer": customer_id, "client_reference_id": tenant_id,
                "metadata": {"tenant_id": tenant_id, "plan_key": "growth", "period_code": "monthly"},
            }
            try:
                send_event("checkout.session.completed", session_obj)
                send_event("invoice.paid", invoice)
            except Exception:
                self.send_error(502, "Local billing reconciliation failed")
                return
            target = session["params"]["success_url"].replace("{CHECKOUT_SESSION_ID}", session_id)
            self.send_response(303)
            self.send_header("Location", target)
            self.end_headers()

    checkout_server = ThreadingHTTPServer(("127.0.0.1", 15175), CheckoutHandler)
    checkout_thread = threading.Thread(target=checkout_server.serve_forever, daemon=True)
    checkout_thread.start()

    def create_customer(_email, _name, _tenant, idempotency_key):
        return {"id": f"cus_browser_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}"}

    def create_checkout_session(params, idempotency_key):
        session_id = f"cs_browser_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}"
        checkout_sessions[session_id] = {"params": copy.deepcopy(params)}
        return {"id": session_id, "url": f"{fixture_base}/checkout/{session_id}"}

    def retrieve_subscription(subscription_id):
        sub = subscription_state["value"]
        if not sub or sub["id"] != subscription_id:
            raise RuntimeError("Unknown fixture subscription")
        return copy.deepcopy(sub)

    def retrieve_invoice(invoice_id):
        if invoice_id not in invoices:
            raise RuntimeError("Unknown fixture invoice")
        return copy.deepcopy(invoices[invoice_id])

    def modify_subscription(subscription_id, **params):
        sub = retrieve_subscription(subscription_id)
        if "cancel_at_period_end" in params:
            sub["cancel_at_period_end"] = bool(params["cancel_at_period_end"])
        if params.get("items"):
            sub["items"]["data"][0]["price"]["id"] = params["items"][0]["price"]
        subscription_state["value"] = sub
        send_event("customer.subscription.updated", {"object": "subscription", "id": subscription_id})
        return copy.deepcopy(sub)

    def create_portal_session(_customer_id, return_url):
        del return_url
        return {"url": f"{fixture_base}/portal/session"}

    stripe_api.create_customer = create_customer
    stripe_api.create_checkout_session = create_checkout_session
    stripe_api.retrieve_subscription = retrieve_subscription
    stripe_api.retrieve_invoice = retrieve_invoice
    stripe_api.modify_subscription = modify_subscription
    stripe_api.create_portal_session = create_portal_session

    from src.ai.main import app

    api_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=15174, log_level="info"))
    api_thread = threading.Thread(target=api_server.run, daemon=True)
    api_thread.start()
    try:
        for _ in range(100):
            try:
                with urlopen(api_base + "/health/ready", timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("Disposable FastAPI did not become ready")

        # Separate the backend's actual auth response from browser/proxy
        # navigation so a blocked API request is visible as an exact stage.
        auth_probe = Request(
            api_base + "/auth/login",
            data=json.dumps({"email": email, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(auth_probe, timeout=15) as response:
            probe_body = json.loads(response.read())
            if response.status != 200 or not probe_body.get("access_token"):
                raise RuntimeError("Isolated FastAPI login probe did not issue an access token")
        print("FASTAPI_LOGIN_PROBE: authenticated owner received a real app token")

        env = dict(os.environ)
        env["KEEL_SUBSCRIPTION_TEST_EMAIL"] = email
        env["KEEL_SUBSCRIPTION_TEST_PASSWORD"] = password
        env["KEEL_SUBSCRIPTION_BROWSER_BASE_URL"] = frontend_base
        env.setdefault("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", str(Path.home() / "AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe"))
        browser_script = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "browser" / "subscription-lifecycle.mjs"
        result = subprocess.run(["node", str(browser_script)], cwd=browser_script.parents[2], env=env, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        api_server.should_exit = True
        checkout_server.shutdown()
        checkout_server.server_close()
        with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM billing_webhook_events WHERE tenant_id=%s", (tenant_id,))
            cur.execute("DELETE FROM billing_payments WHERE tenant_id=%s", (tenant_id,))
            cur.execute("DELETE FROM billing_subscriptions WHERE tenant_id=%s", (tenant_id,))
            cur.execute("DELETE FROM billing_customers WHERE tenant_id=%s", (tenant_id,))
            cur.execute("DELETE FROM tenant_plan_assignments WHERE tenant_id=%s", (tenant_id,))
            cur.execute("DELETE FROM billing_trials WHERE tenant_id=%s", (tenant_id,))
            cur.execute("DELETE FROM companies WHERE tenant_id=%s", (tenant_id,))
            cur.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
            cur.execute("UPDATE billing_plan_prices SET stripe_price_id=NULL WHERE plan_key='growth' AND period_code='monthly' AND stripe_price_id=%s", (price_id,))
            conn.commit()


if __name__ == "__main__":
    main()
