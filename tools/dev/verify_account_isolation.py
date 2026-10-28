"""Real signup/OTP/onboarding browser regression on repository-owned disposable infrastructure.
Run with the configured local Python: tools/dev/verify_account_isolation.py.
No external credentials, Stripe sessions or provider mutations are used.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import dev
import testing

def main():
    c = dev.config()
    with dev.command_lock(), testing.isolated(c, "account-isolation") as (local, env, target):
        origin = f"http://127.0.0.1:{local['ports']['frontend']}"
        api = f"http://127.0.0.1:{local['ports']['api']}"
        runtime = dict(env, DATABASE_URL=env['SCRAPER_DATABASE_URL'], FRONTEND_BASE_URL=origin,
                       CORS_ALLOWED_ORIGINS=origin, KEEL_API_PROXY_TARGET=api, VITE_API_BASE_URL='/api',
                       REQUIRE_EMAIL_VERIFICATION='true', DISCOVERY_REFRESH_ENABLED='false', NOTIFICATION_DIGEST_ENABLED='false')
        for key in ('AI_TEST_DATABASE_URL', 'BILLING_TEST_DATABASE_URL', 'BILLING_DATABASE_TESTS'):
            runtime.pop(key, None)
        assert not runtime.get('STRIPE_SECRET_KEY') and runtime['STRIPE_TEST_CLOCK_ENABLED']=='false'
        dev.start_process('test-api', [dev.PYTHON, '-m', 'uvicorn', 'src.ai.main:app', '--host', '127.0.0.1', '--port', local['ports']['api']], local, env=runtime)
        dev.wait_for('isolated API readiness', lambda: json.loads(dev.http(api+'/health/ready')[0])['status']=='ok')
        node=shutil.which('node')
        dev.start_process('test-frontend', [node, dev.ROOT/'frontend/node_modules/vite/bin/vite.js', '--host','127.0.0.1','--port',local['ports']['frontend'],'--strictPort'], local, env=runtime, cwd=dev.ROOT/'frontend')
        dev.wait_for('isolated frontend proxy', lambda: json.loads(dev.http(origin+'/api/health/ready')[0])['status']=='ok')
        chrome=next((str(Path(base)/'Google/Chrome/Application/chrome.exe') for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'), os.environ.get('LOCALAPPDATA')) if base and (Path(base)/'Google/Chrome/Application/chrome.exe').exists()),None)
        if not chrome: raise dev.DevError('Chrome is required; browser verification not skipped.')
        browser_env=dict(runtime, APP_URL=origin, ISOLATED_ACCOUNT_TEST='YES', CHROMIUM_PATH=chrome, MAILPIT_URL=f"http://127.0.0.1:{local['ports']['inbox']}", E2E_OUTPUT=str(target))
        testing.logged([node,dev.ROOT/'frontend/tests/browser/account-isolation.mjs'],target/'account-isolation.log',browser_env,cwd=dev.ROOT/'frontend')
        # No Stripe-backed records are allowed in this browser fixture.
        import database
        from contextlib import closing
        with closing(database.connect(c,database=json.loads((target/'run.json').read_text())['database'],external=False)) as conn, conn.cursor() as cur:
            for table in ('billing_customers','billing_checkout_attempts','billing_subscriptions'):
                cur.execute('SELECT count(*) FROM '+table)
                assert cur.fetchone()[0]==0, table+' unexpectedly populated'
        print('PASS native persistence: no Stripe customers, Checkout attempts or subscriptions created.')

if __name__=='__main__':
    main()
