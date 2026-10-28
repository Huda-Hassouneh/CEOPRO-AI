"""Original owner controls against a disposable, real restricted FastAPI runtime.
No external provider key is loaded and no Stripe operation is permitted.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import dev
import testing

def main():
    c=dev.config()
    with dev.command_lock(), testing.isolated(c,'owner-billing-original') as (local,env,target):
        testing.logged([dev.PYTHON,'-m','pytest','tests/billing/test_owner_promotion_commands_db.py','tests/billing/test_owner_quote_review_evidence_db.py','tests/billing/test_platform_billing_admin_views.py','-q'],target/'owner-regressions.log',env)
        origin=f"http://127.0.0.1:{local['ports']['frontend']}";api=f"http://127.0.0.1:{local['ports']['api']}"
        runtime=dict(env,DATABASE_URL=env['SCRAPER_DATABASE_URL'],FRONTEND_BASE_URL=origin,CORS_ALLOWED_ORIGINS=origin,KEEL_API_PROXY_TARGET=api,VITE_API_BASE_URL='/api',DISCOVERY_REFRESH_ENABLED='false',NOTIFICATION_DIGEST_ENABLED='false')
        for k in ('AI_TEST_DATABASE_URL','BILLING_TEST_DATABASE_URL','BILLING_DATABASE_TESTS'):runtime.pop(k,None)
        assert not runtime.get('STRIPE_SECRET_KEY') and runtime['STRIPE_TEST_CLOCK_ENABLED']=='false'
        dev.start_process('test-api',[dev.PYTHON,'-m','uvicorn','src.ai.main:app','--host','127.0.0.1','--port',local['ports']['api']],local,env=runtime)
        dev.wait_for('isolated owner API readiness',lambda:json.loads(dev.http(api+'/health/ready')[0])['status']=='ok',timeout=180)
        node=shutil.which('node')
        dev.start_process('test-frontend',[node,dev.ROOT/'frontend/node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',local['ports']['frontend'],'--strictPort'],local,env=runtime,cwd=dev.ROOT/'frontend')
        dev.wait_for('isolated owner frontend',lambda:json.loads(dev.http(origin+'/api/health/ready')[0])['status']=='ok')
        password='Synthetic!'+secrets.token_hex(12)
        fixture_env=dict(env,E2E_API=api,E2E_PASSWORD=password,E2E_FIXTURE_FILE=str(target/'fixture.json'))
        testing.logged([dev.PYTHON,'-m','scripts.owner_billing_browser_fixture'],target/'fixture.log',fixture_env)
        chrome=next((str(Path(base)/'Google/Chrome/Application/chrome.exe') for base in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)'),os.environ.get('LOCALAPPDATA')) if base and (Path(base)/'Google/Chrome/Application/chrome.exe').exists()),None)
        if not chrome:raise dev.DevError('Chrome required; browser verification not skipped')
        browser_env=dict(runtime,APP_URL=origin,API_URL=api,E2E_PASSWORD=password,E2E_FIXTURE_FILE=str(target/'fixture.json'),E2E_OUTPUT=str(target),CHROMIUM_PATH=chrome,KEEL_OWNER_BROWSER_ISOLATED='YES')
        testing.logged([node,dev.ROOT/'frontend/tests/browser/owner-billing-original.mjs'],target/'browser.log',browser_env,cwd=dev.ROOT/'frontend')
        # Verify durable results independently of HTTP and the React cache.
        import database
        from contextlib import closing
        name=json.loads((target/'run.json').read_text())['database']
        with closing(database.connect(c,database=name,external=False)) as conn,conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM entitlement_audit_log WHERE action IN ('custom_pricing_policy_draft_created','custom_pricing_policy_activated','custom_pricing_rate_created','custom_pricing_binding_created')")
            audit=cur.fetchone()[0];assert audit>=4
            cur.execute("SELECT count(*) FROM billing_custom_quotes WHERE state='approved'");assert cur.fetchone()[0]>=1
            cur.execute("SELECT status,terms->>'discount_value',stripe_coupon_id,stripe_promotion_code_id FROM billing_promotions WHERE code='SYNTH_BROWSER'")
            assert cur.fetchone()==('draft','11',None,None)
            cur.execute("SELECT limit_value FROM usage_plan_limits WHERE plan_key='starter' AND feature_code='connected_data_sources'")
            assert cur.fetchone()[0]==5
            cur.execute("SELECT count(*) FROM keel_platform_audit WHERE action='feature_catalog_metadata_update' AND subject='connected_data_sources'")
            assert cur.fetchone()[0]>=1
            for table in ('billing_customers','billing_checkout_attempts','billing_subscriptions','billing_custom_quote_checkout_attempts'):
                cur.execute('SELECT count(*) FROM '+table);assert cur.fetchone()[0]==0,table
            cur.execute("SELECT count(*) FROM billing_custom_quote_events WHERE action='approved'");assert cur.fetchone()[0]>=1
            cur.execute("SELECT count(*) FROM billing_custom_pricing_policies WHERE status='active'");assert cur.fetchone()[0]==1
        dev.write_json(target/'persistence.json',{'status':'PASS','audit_events':audit,'no_checkout_subscription_or_customer_created':True,'real_provider':'UNRUN'})
        print('PASS durable pricing/quote/audit persistence; no Stripe customers, Checkout attempts or subscriptions created.')
if __name__=='__main__':main()
