"""Production builder + real isolated HTTP/PG. Never connects to Stripe.

Identity is injected for one synthetic tenant in this acceptance-only app;
the production billing role, restricted sockets, pricing and SQL are unchanged.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import shutil
import socket
import subprocess
import threading
import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg2.extras import Json
import uvicorn

from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.routers import billing
from src.ai.billing import custom_offers
from .test_reconciliation_roles import restricted_runtime  # noqa: F401


def port():
    with closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def browser_executable():
    """Honor explicit CI configuration, then discover a local Chromium browser."""
    configured = os.environ.get('CHROMIUM_PATH')
    if configured:
        browser = Path(configured)
        assert browser.is_file(), 'Configured CHROMIUM_PATH must name an installed browser'
        return browser
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        found = shutil.which(name)
        if found:
            return Path(found)
    for variable, default in (('ProgramFiles', 'C:/Program Files'),
                              ('ProgramFiles(x86)', 'C:/Program Files (x86)')):
        browser = Path(os.environ.get(variable, default)) / 'Google/Chrome/Application/chrome.exe'
        if browser.is_file():
            return browser
    raise AssertionError('Install Chrome/Chromium or set CHROMIUM_PATH for browser acceptance')


@pytest.mark.parametrize('scenario,locale', [('automatic', 'en'), ('quota', 'en'), ('price', 'en'),
                                         ('unverified', 'en'), ('existing', 'en'), ('automatic', 'ar')])
def test_browser_custom_builder(scenario, locale, owner_db, tenant, restricted_runtime, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    chrome = browser_executable()
    tid, uid = tenant
    now = datetime.now(timezone.utc)
    with owner_db.cursor() as cur:
        cur.execute("UPDATE billing_custom_pricing_policies SET status='retired',effective_to=clock_timestamp() WHERE status='active'")
        cur.execute("""INSERT INTO billing_custom_pricing_policies(target_gross_margin,enforce_vendor_cost_ratio_floor,
          fixed_platform_fee_usd,upward_rounding_increment_usd,monthly_shared_infrastructure_cost_usd,active_paying_tenant_count,
          approved_by,approval_evidence,self_service_policy) VALUES(.35,false,0,0,0,1,'test','SYNTHETIC_TEST_ONLY',%s) RETURNING policy_version_id""",
          (Json({'fixedPlatformFee': '25', 'roundingIncrement': '1'}),))
        policy = str(cur.fetchone()[0])
        verification = now.date() + timedelta(days=1 if scenario == 'unverified' else 0)
        cur.execute("""INSERT INTO billing_custom_cost_rates(budget_kind,provider,operation,unit,unit_cost_usd,source,verified_at,
          effective_from,verified_by,verification_evidence) VALUES('data',%s,'source-month','request',1,'SYNTHETIC_TEST_ONLY',%s,%s,'test','test') RETURNING cost_rate_id""",
          ('synthetic-' + uuid4().hex, verification, now - timedelta(minutes=1)))
        rate = str(cur.fetchone()[0])
        cur.execute("""INSERT INTO billing_custom_cost_bindings(policy_version_id,feature_code,cost_category,budget_kind,provider,
          operation,unit,usage_basis,units_per_feature_unit,operational_multiplier,variability_reserve,effective_from,source,created_by,cost_rate_id)
          SELECT %s,'connected_data_sources','vendor',budget_kind,provider,operation,unit,'limit_value',1,1,1,%s,'test','test',cost_rate_id
          FROM billing_custom_cost_rates WHERE cost_rate_id=%s""", (policy, now, rate))
        cur.execute("UPDATE billing_custom_pricing_policies SET status='active',effective_from=%s WHERE policy_version_id=%s", (now, policy))
        if scenario == 'existing':
            cur.execute("""INSERT INTO billing_subscriptions(tenant_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,
              plan_key,period_code,status) VALUES(%s,%s,'cus_synthetic','price_synthetic','starter','monthly','active')""", (tid, 'sub_' + uuid4().hex))
    api_port, frontend_port = port(), port()
    api, frontend = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{frontend_port}'
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=[frontend], allow_methods=['*'], allow_headers=['*'])
    app.include_router(billing.router)
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(tid, uid)
    monkeypatch.setattr(billing.config, 'payments_enabled', lambda: True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=api_port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    env = dict(os.environ, VITE_API_BASE_URL=api, APP_URL=frontend, API_URL=api,
               CHROMIUM_PATH=str(chrome), SCENARIO=scenario, E2E_LOCALE=locale)
    process = subprocess.Popen([shutil.which('node'), 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(frontend_port), '--strictPort'],
                               cwd=root / 'frontend', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        import urllib.request
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(frontend + '/tests/browser/custom-self-service.html', timeout=1):
                    if server.started:
                        break
            except OSError:
                time.sleep(.1)
        result = subprocess.run([shutil.which('node'), 'tests/browser/custom-self-service.mjs'], cwd=root / 'frontend', env=env,
                                capture_output=True, text=True, timeout=55)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        process.terminate()
        process.wait(timeout=10)
        server.should_exit = True
        thread.join(timeout=10)
