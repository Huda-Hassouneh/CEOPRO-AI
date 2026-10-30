"""Focused browser/accounting acceptance using the existing disposable runner.

Run: .dev/venv/Scripts/python.exe tools/dev/provider_accounting_browser.py
Never targets the normal checkout database or imports paid provider credentials.
"""
import contextlib
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path
import sys

import dev
import testing


def start_runtime(config, env, target):
    """Use the existing owned test-process lifecycle, focused on this feature."""
    origin = f"http://127.0.0.1:{config['ports']['frontend']}"
    api = f"http://127.0.0.1:{config['ports']['api']}"
    runtime = dict(env, DATABASE_URL=env["SCRAPER_DATABASE_URL"], FRONTEND_BASE_URL=origin,
                   CORS_ALLOWED_ORIGINS=origin, KEEL_API_PROXY_TARGET=api, VITE_API_BASE_URL="/api",
                   DISCOVERY_REFRESH_ENABLED="false", NOTIFICATION_DIGEST_ENABLED="false",
                   BILLING_MAINTENANCE_ENABLED="false")
    for key in ("AI_TEST_DATABASE_URL", "BILLING_TEST_DATABASE_URL", "BILLING_DATABASE_TESTS"):
        runtime.pop(key, None)
    dev.start_process("test-api", [dev.PYTHON, "-m", "uvicorn", "src.ai.main:app", "--host", "127.0.0.1",
                                   "--port", config["ports"]["api"]], config, env=runtime)
    dev.wait_for("test API readiness", lambda: json.loads(dev.http(api + "/health/ready")[0]).get("status") == "ok")
    node = shutil.which("node")
    vite = dev.ROOT / "frontend/node_modules/vite/bin/vite.js"
    testing.logged([node, vite, "build"], target / "build.log", runtime, cwd=dev.ROOT / "frontend")
    dev.start_process("test-frontend", [node, vite, "preview", "--host", "127.0.0.1", "--port",
                                      config["ports"]["frontend"], "--strictPort"], config,
                      env=runtime, cwd=dev.ROOT / "frontend")
    dev.wait_for("test frontend proxy", lambda: json.loads(dev.http(origin + "/api/health/ready")[0]).get("status") == "ok")


def main():
    with dev.command_lock():
        with testing.isolated(dev.config(), "provider-accounting-browser") as (config, env, target):
            start_runtime(config, env, target)
            runtime = dict(env, E2E_API=f"http://127.0.0.1:{config['ports']['api']}",
                           E2E_PASSWORD="Ci!Provider-Accounting-2026", E2E_FIXTURE_FILE=str(target / "owner-fixture.json"))
            testing.logged([dev.PYTHON, "-m", "scripts.owner_billing_browser_fixture"], target / "owner-fixture.log", runtime)
            chrome = next((str(Path(base) / "Google/Chrome/Application/chrome.exe") for base in
                           (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA"))
                           if base and (Path(base) / "Google/Chrome/Application/chrome.exe").exists()), None)
            chrome = chrome or next((shutil.which(name) for name in ("chromium", "google-chrome", "chromium-browser") if shutil.which(name)), None)
            if not chrome:
                raise dev.DevError("Chrome/Chromium required")
            runtime.update(APP_URL=f"http://127.0.0.1:{config['ports']['frontend']}", E2E_OUTPUT=str(target),
                           CHROMIUM_PATH=chrome, KEEL_OWNER_BROWSER_ISOLATED="YES")
            testing.logged([shutil.which("node"), dev.ROOT / "frontend/tests/browser/provider-accounting.mjs"],
                           target / "provider-accounting-browser.log", runtime, cwd=dev.ROOT / "frontend")
            # Same saved schedule -> actual reservation/settlement, fake send only.
            os.environ.update(env)
            sys.path.insert(0, str(dev.ROOT / "backend"))
            import psycopg2
            from src.ai.billing import credits
            from src.market_scraper import provider_billing
            fixture = json.loads((target / "owner-fixture.json").read_text())
            tid, uid = fixture["customer"]["tenant_id"], fixture["customer"]["user_id"]
            with contextlib.closing(psycopg2.connect(env["DATABASE_URL"])) as conn:
                def read(sql, values=()):
                    with conn.cursor() as cur:
                        cur.execute(sql, values)
                        return cur.fetchall()
                rate = credits.schedule(conn, "data", "synthetic_browser_accounting", "search")
                assert rate["request"]["cost"] == Decimal("0.04")
                audit = read("SELECT approved_by,new_value->>'unit_cost_usd' FROM entitlement_audit_log WHERE action='set_price' AND subject='data:synthetic_browser_accounting:search:request' ORDER BY created_at")
                assert len(audit) == 2 and all(row[0] == fixture["owner"]["user_id"] for row in audit)
                provider_billing._PAID[("synthetic.example", "/")] = ("synthetic_browser_accounting", "search", "request")
                with credits.metering(tid, "assistant_question", actor_user_id=uid):
                    provider_billing.metered_request("https://synthetic.example/search", lambda: {"results": []})
                ledger = read("SELECT status,actual_cost_usd,consumed_credits,measured_units FROM usage_ledger WHERE tenant_id=%s AND budget_kind='data'", (tid,))
                expected = credits._to_credits(Decimal("0.04"), credits.policy(conn)["credit_usd_value"])
                assert ledger == [("consumed", Decimal("0.04"), expected, {"request": 1})]
                assert read("SELECT reserved_credits,consumed_credits,consumed_cost_usd FROM tenant_credit_balances WHERE tenant_id=%s AND budget_kind='data'", (tid,)) == [(0, expected, Decimal("0.04"))]
                assert not read("SELECT 1 FROM usage_ledger WHERE tenant_id=%s AND budget_kind='ai'", (tid,))
                (target / "provider-accounting-proof.json").write_text(json.dumps({"status": "PASS", "audit_rows": len(audit), "data_cost_usd": "0.04", "data_credits": str(expected), "reserved": "0", "measured_requests": 1, "transport": "synthetic callback"}, indent=2))
            print("PASS: Owner UI -> API -> admin.set_price -> schedule -> fake Data call -> ledger/balance/audit.")


if __name__ == "__main__":
    main()
