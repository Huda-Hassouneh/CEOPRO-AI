"""Disposable, offline browser reproduction of trial plan transitions.

Run from the repository root with its configured Python:
    python backend/scripts/verify_trial_transition_browser.py
Uses the same checkout-owned test infrastructure as dev.ps1 test; never Stripe.
"""
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/dev'))
import dev
import testing


def create_app():
    """Test-only Uvicorn factory; no alternate production routes or grants."""
    parsed = urlsplit(os.environ.get('DATABASE_URL', ''))
    if (os.environ.get('KEEL_TRIAL_BROWSER_FIXTURE') != 'YES'
            or parsed.username != 'ceopro_app' or parsed.hostname != '127.0.0.1'
            or not parsed.path.startswith('/keel_billing_test_dev')):
        raise RuntimeError('Offline browser fixture requires a restricted disposable local database')
    from tests.billing.test_trial_plan_transitions import TrialProvider
    from src.ai.billing import stripe_api
    from src.ai.main import app
    provider = None

    def load():
        nonlocal provider
        if provider is None:
            values = json.loads(Path(os.environ['KEEL_TRIAL_BROWSER_STATE']).read_text())
            provider = TrialProvider(values['tenant_id'], 'price_offline_growth')
            provider.live.update(id=values['subscription_id'], customer=values['customer_id'], trial_end=values['trial_end'])
            provider.live['items']['data'][0]['current_period_end'] = values['trial_end']
            provider.original = json.loads(json.dumps(provider.live))
        return provider

    def refuse():
        raise RuntimeError('Real Stripe HTTP is forbidden in the offline browser fixture')

    stripe_api._client = refuse
    for name, method in (('retrieve_subscription','subscription'), ('create_schedule_from_subscription','create'),
                         ('retrieve_schedule','schedule'), ('modify_schedule','modify'),
                         ('release_schedule','release'), ('modify_subscription','upgrade')):
        setattr(stripe_api, name, lambda *a, _method=method, **kw: getattr(load(), _method)(*a, **kw))
    return app


def run():
    import httpx
    import database
    c = dev.config()
    with testing.isolated(c, 'trial-transition-browser') as (local, env, target):
        origin = f"http://127.0.0.1:{local['ports']['frontend']}"
        api = f"http://127.0.0.1:{local['ports']['api']}"
        state_path = target / 'offline-provider.json'
        env = dict(env, FRONTEND_BASE_URL=origin, CORS_ALLOWED_ORIGINS=origin)
        runtime = dict(env, DATABASE_URL=env['SCRAPER_DATABASE_URL'], KEEL_API_PROXY_TARGET=api,
                       VITE_API_BASE_URL='/api', KEEL_TRIAL_BROWSER_FIXTURE='YES',
                       KEEL_TRIAL_BROWSER_STATE=str(state_path), STRIPE_SECRET_KEY='sk_test_offline',
                       STRIPE_WEBHOOK_SECRET='whsec_offline', DISCOVERY_REFRESH_ENABLED='false',
                       NOTIFICATION_DIGEST_ENABLED='false')
        for key in ('AI_TEST_DATABASE_URL','BILLING_TEST_DATABASE_URL','BILLING_DATABASE_TESTS'):
            runtime.pop(key, None)
        dev.start_process('test-api', [dev.PYTHON,'-m','uvicorn','scripts.verify_trial_transition_browser:create_app',
                          '--factory','--host','127.0.0.1','--port',local['ports']['api']], local, env=runtime)
        dev.wait_for('restricted offline test API',lambda:json.loads(dev.http(api+'/health/ready',origin)[0]).get('status')=='ok')
        email,password='trial-transition@keel-ci.example','Ci!Trial-Only-2026'
        testing.logged([dev.PYTHON,'-m','scripts.ci_smoke_account','--api',api,'--email',email,'--password',password,
                        '--test-email-verification-fixture'],target/'account.log',env)
        with closing(database.connect(c,database=env['DATABASE_URL'].rsplit('/',1)[1],external=False)) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT t.tenant_id FROM tenant_users t JOIN users u USING(user_id) WHERE u.email=%s',(email,))
                tid=str(cur.fetchone()[0])
                cur.execute('SELECT ends_at FROM billing_trials WHERE tenant_id=%s',(tid,))
                cutoff=int(cur.fetchone()[0].timestamp())
                # Public names are needed by the actual three-plan React view.
                # These are synthetic provider IDs in this disposable DB only.
                cur.execute("UPDATE billing_plan_prices SET stripe_price_id='price_offline_'||plan_key WHERE period_code='monthly' AND plan_key IN ('starter','growth','enterprise')")
            conn.commit()
            state={'tenant_id':tid,'subscription_id':'sub_offline_browser_'+uuid.uuid4().hex,
                   'customer_id':'cus_offline_browser_'+uuid.uuid4().hex,'trial_end':cutoff}
            state_path.write_text(json.dumps(state))
            event={'id':'evt_offline_browser_'+uuid.uuid4().hex,'type':'customer.subscription.created',
                   'livemode':False,'created':int(time.time()),'data':{'object':{'id':state['subscription_id']}}}
            payload=json.dumps(event).encode(); stamp=str(int(time.time()))
            signature=hmac.new(b'whsec_offline',stamp.encode()+b'.'+payload,hashlib.sha256).hexdigest()
            response=httpx.post(api+'/billing/webhook',content=payload,headers={'Stripe-Signature':f't={stamp},v1={signature}'})
            assert response.status_code==200, response.status_code
            with conn.cursor() as cur:
                cur.execute('SELECT status,current_period_start,current_period_end,trial_end FROM billing_subscriptions WHERE tenant_id=%s',(tid,))
                before=cur.fetchone()
            node=shutil.which('node');vite=ROOT/'frontend/node_modules/vite/bin/vite.js'
            testing.logged([node,vite,'build'],target/'build.log',runtime,cwd=ROOT/'frontend')
            dev.start_process('test-frontend',[node,vite,'preview','--host','127.0.0.1','--port',local['ports']['frontend'],'--strictPort'],local,env=runtime,cwd=ROOT/'frontend')
            dev.wait_for('test frontend readiness',lambda:json.loads(dev.http(origin+'/api/health/ready')[0]).get('status')=='ok')
            chrome=dev.integrations(validate_providers=False).get('CHROMIUM_PATH')
            for base in (os.getenv('ProgramFiles'),os.getenv('ProgramFiles(x86)'),os.getenv('LOCALAPPDATA')):
                if not chrome and base and (Path(base)/'Google/Chrome/Application/chrome.exe').exists():
                    chrome=str(Path(base)/'Google/Chrome/Application/chrome.exe')
            chrome=chrome or next((shutil.which(n) for n in ('google-chrome','chromium','chromium-browser') if shutil.which(n)),None)
            if not chrome:raise RuntimeError('Chrome/Chromium is required; no browser result was assumed')
            browser_env=dict(runtime,APP_URL=origin,API_URL=api,E2E_EMAIL=email,E2E_PASSWORD=password,
                             E2E_EVIDENCE_DIR=str(target),CHROMIUM_PATH=chrome)
            testing.logged([node,ROOT/'frontend/tests/browser/trial-transition.mjs'],target/'browser.log',browser_env,cwd=ROOT/'frontend')
            with conn.cursor() as cur:
                cur.execute('SELECT status,current_period_start,current_period_end,trial_end FROM billing_subscriptions WHERE tenant_id=%s',(tid,))
                assert cur.fetchone()==before
                cur.execute('SELECT count(*) FROM tenant_credit_balances WHERE tenant_id=%s',(tid,))
                assert cur.fetchone()[0]==0
            (target/'database-result.json').write_text(json.dumps({'status':'PASS','trial':'unchanged','periods':'unchanged','credit_rows':0}))
        print('PASS: offline real-browser EN/AR downgrade, cancel, reload; restricted SQL state unchanged; no Stripe requests')


if __name__=='__main__':
    run()
