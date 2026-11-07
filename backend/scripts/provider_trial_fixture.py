"""Offline provider transport fixture for disposable CI databases only.

Uses production Checkout, signed decoding and restricted-role reconciliation.
It is not real Stripe acceptance and is never installed in the application.
"""
from contextlib import ExitStack
import hashlib
import hmac
import json
import os
import time
import uuid
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg2
from fastapi import FastAPI
from fastapi.testclient import TestClient


def confirm_trial(client, plan='growth'):
    from scripts.billing_verification import validate_test_environment
    from src.ai.billing import stripe_api
    from src.ai.routers import billing

    parsed = urlparse(str(client.http.base_url))
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost','127.0.0.1','::1'}:
        raise RuntimeError('Offline provider fixture requires loopback HTTP.')
    database = validate_test_environment(dict(os.environ), database=True)
    target = urlparse(database)
    for key in ('DATABASE_URL','SCRAPER_DATABASE_URL'):
        runtime = urlparse(os.environ.get(key,''))
        if (runtime.hostname,runtime.port,runtime.path) != (target.hostname,target.port,target.path):
            raise RuntimeError('Offline provider fixture requires every runtime connection to use the same disposable test database.')
    current = client.request('GET','/billing/subscription')
    if current.get('hasAccess'):
        return
    if current.get('trialUsed'):
        raise RuntimeError('Offline provider fixture never replaces an issued trial.')
    fixture = uuid.uuid4().hex
    customer, subscription, session = 'cus_fixture_'+fixture, 'sub_fixture_'+fixture, 'cs_fixture_'+fixture
    secret = 'whsec_offline_ci_fixture'
    app = FastAPI()
    app.include_router(billing.router)
    # Only the disposable catalog's opaque mapping is supplied, without prices changing.
    with psycopg2.connect(database) as conn, conn.cursor() as cur:
        cur.execute("SELECT price_id,stripe_price_id FROM billing_plan_prices WHERE plan_key=%s AND period_code='monthly' AND retired_at IS NULL",(plan,))
        price_id, original = cur.fetchone()
        price = original or 'price_fixture_'+fixture
        cur.execute('UPDATE billing_plan_prices SET stripe_price_id=%s WHERE price_id=%s',(price,price_id))
    try:
        request = {}
        def checkout(params, **kwargs):
            request.update(params)
            return {'id':session,'status':'open','url':'https://checkout.stripe.test/offline-ci'}
        live = {}
        customer_object = {'id': customer}
        def prepare_customer(email, name, tenant, operation):
            metadata = {'tenant_id': tenant, 'keel_customer_operation_id': operation}
            customer_object['metadata'] = metadata
            return {'namespace': {'account': 'acct_offline_ci_fixture', 'livemode': False},
                    'api_version': 'offline', 'params': {'email': email, 'name': name, 'metadata': metadata}}
        def unexpected_transport(*args, **kwargs):
            raise AssertionError('Unexpected external Stripe transport in offline CI fixture')
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,{'STRIPE_SECRET_KEY':'sk_test_offline_ci_fixture','STRIPE_WEBHOOK_SECRET':secret,'PUBLIC_FRONTEND_ORIGIN':'http://127.0.0.1:15173','STRIPE_TEST_CLOCK_ENABLED':'false'}))
            for name, function in {
                'prepare_customer_create':prepare_customer,
                'create_customer':lambda *a,**k:dict(customer_object),
                'retrieve_customer':lambda reference:dict(customer_object),
                'recover_customer_create':lambda *a,**k:None,
                '_client':unexpected_transport,
                'customer_subscriptions':lambda *a,**k:[],
                'open_customer_checkouts':lambda *a,**k:[],
                'customer_clock_time':lambda *a,**k:None,
                'create_checkout_session':checkout,
                'retrieve_subscription':lambda *a,**k:live,
            }.items():
                stack.enter_context(patch.object(stripe_api,name,function))
            http = stack.enter_context(TestClient(app))
            started = http.post('/billing/trial',headers=client.headers,json={'plan_key':plan,'period_code':'monthly'})
            if started.status_code != 200:
                raise RuntimeError(f'Offline Checkout fixture failed (HTTP {started.status_code}).')
            assert not client.request('GET','/billing/subscription')['hasAccess']
            now = int(time.time())
            end = now+request['subscription_data']['trial_period_days']*86400
            live.update(id=subscription,customer=request['customer'],status='trialing',trial_start=now,trial_end=end,
                        default_payment_method='pm_offline_ci_fixture',metadata=request['subscription_data']['metadata'],
                        items={'data':[{'id':'si_fixture','price':{'id':price},'quantity':1,'current_period_start':now,'current_period_end':end}]})
            payload = json.dumps({'id':'evt_fixture_'+fixture,'type':'customer.subscription.created','livemode':False,'created':now,'data':{'object':{'id':subscription}}}).encode()
            signature = hmac.new(secret.encode(),str(now).encode()+b'.'+payload,hashlib.sha256).hexdigest()
            confirmed = http.post('/billing/webhook',content=payload,headers={'Stripe-Signature':f't={now},v1={signature}'})
            if confirmed.status_code != 200:
                raise RuntimeError(f'Offline provider confirmation failed (HTTP {confirmed.status_code}).')
            assert client.request('GET','/billing/subscription')['hasAccess']
    except Exception:
        with psycopg2.connect(database) as conn, conn.cursor() as cur:
            cur.execute('UPDATE billing_plan_prices SET stripe_price_id=%s WHERE price_id=%s',(original,price_id))
        raise
